"""
app.py - Servidor Principal (Backend Flask + Monitor Automático)
================================================================
Este é o coração do sistema PriceRadar! Ele conecta:
- A interface web (HTML/CSS/JS)
- O banco de dados SQLite (`database.py`)
- O extrator de preços via Web Scraping (`scraper.py`)
- O disparador de alertas por e-mail (`mailer.py`)

Como executar:
  python app.py
Depois, basta abrir http://127.0.0.1:5000 no navegador!
"""

import threading
import time
import random
from flask import Flask, render_template, request, jsonify

import database
import scraper
import mailer

app = Flask(__name__)

# Inicializa o banco de dados ao carregar o aplicativo
database.init_db()

# Se o banco estiver vazio na primeira vez, adiciona 3 produtos de exemplo
# para você já ver os gráficos e comparações funcionando de cara!
if len(database.get_all_products()) == 0:
    database.seed_demo_products()


def check_single_product_and_notify(product_id, forced_price=None):
    """
    Função auxiliar que atualiza o preço de um produto (via Web Scraping ou simulação)
    e verifica se o novo preço atingiu a meta (Preço Alvo) para disparar o e-mail.
    """
    product = database.get_product_by_id(product_id)
    if not product:
        return {"success": False, "error": "Produto não encontrado."}

    if forced_price is not None:
        # Usado pelo botão "Simular Promoção" para testar quedas de preço instantaneamente
        new_price = round(float(forced_price), 2)
        updated_product = database.update_product_price(product_id, new_price)
        scrape_note = "Queda de preço simulada com sucesso!"
    else:
        # Faz o Web Scraping real na URL do produto
        scraped = scraper.scrape_product(product["url"])
        if scraped.get("success") and scraped.get("price"):
            new_price = scraped["price"]
            updated_product = database.update_product_price(
                product_id,
                new_price,
                title=scraped.get("title"),
                image_url=scraped.get("image_url")
            )
            scrape_note = "Preço atualizado via Web Scraping em tempo real!"
        else:
            # Caso o site tenha bloqueado a requisição automática no momento,
            # mantemos o preço atual registrado no histórico para não quebrar o teste
            updated_product = database.update_product_price(product_id, product["current_price"])
            scrape_note = (
                "O site limitou a leitura automática neste instante; "
                "mantivemos o último preço registrado. (Dica: use 'Simular Queda' para testar promoções!)"
            )

    # Verifica se o preço atual atingiu ou ficou abaixo do Preço Alvo (Meta)
    alert_result = None
    if updated_product["current_price"] <= updated_product["target_price"]:
        settings = database.get_settings()
        alert_result = mailer.send_price_alert(updated_product, settings)
        database.mark_alert_sent(product_id)
        updated_product = database.get_product_by_id(product_id)

    return {
        "success": True,
        "product": updated_product,
        "note": scrape_note,
        "alert": alert_result
    }


# =====================================================================
# ROTAS DA INTERFACE E API REST (Comunicação com o Frontend JavaScript)
# =====================================================================

@app.route("/")
def index():
    """
    Rota principal que carrega a interface visual (Dashboard).
    """
    return render_template("index.html")


@app.route("/api/state", methods=["GET"])
def api_get_state():
    """
    Retorna todos os produtos, estatísticas resumidas (KPIs) e configurações atuais.
    """
    products = database.get_all_products()
    settings = database.get_settings()

    # Calcula estatísticas para os cards do topo do Dashboard
    total_products = len(products)
    deals_count = sum(1 for p in products if p["current_price"] <= p["target_price"])
    total_savings = sum(
        max(0.0, p["highest_price"] - p["current_price"])
        for p in products
    )

    # Não enviamos a senha completa para o navegador por boa prática, apenas indicamos se está preenchida
    safe_settings = dict(settings)
    safe_settings["has_password"] = bool(settings.get("smtp_password"))

    return jsonify({
        "products": products,
        "settings": safe_settings,
        "stats": {
            "total_products": total_products,
            "deals_count": deals_count,
            "total_savings": round(total_savings, 2)
        }
    })


@app.route("/api/scrape-preview", methods=["POST"])
def api_scrape_preview():
    """
    Recebe apenas uma URL e tenta extrair nome, preço e imagem via Web Scraping
    para preencher o formulário automaticamente antes de salvar.
    """
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    result = scraper.scrape_product(url)
    return jsonify(result)


@app.route("/api/products", methods=["POST"])
def api_add_product():
    """
    Cadastra um novo produto para monitoramento.
    Se o usuário só colou a URL, o backend faz o Web Scraping automaticamente!
    """
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    target_price = scraper.clean_price_text(data.get("target_price"))
    manual_price = scraper.clean_price_text(data.get("current_price"))
    manual_title = (data.get("title") or "").strip()
    manual_image = (data.get("image_url") or "").strip()
    notify_email = (data.get("notify_email") or "").strip()

    if not url:
        return jsonify({"success": False, "error": "Informe a URL do produto."}), 400
    if not target_price or target_price <= 0:
        return jsonify({"success": False, "error": "Informe um Preço Alvo (meta) válido maior que zero."}), 400

    # Se não veio título ou preço manual, executa o Web Scraping na URL
    scraped = {}
    if not manual_price or not manual_title:
        scraped = scraper.scrape_product(url)

    title = manual_title or scraped.get("title") or "Produto Monitorado"
    current_price = manual_price or scraped.get("price")
    image_url = manual_image or scraped.get("image_url") or scraper.DEFAULT_PRODUCT_IMAGE
    store_name = scraped.get("store_name") or scraper.detect_store_name(url)

    if not current_price:
        return jsonify({
            "success": False,
            "need_manual_price": True,
            "title": title,
            "image_url": image_url,
            "store_name": store_name,
            "error": (
                "Não foi possível ler o preço automaticamente desta página. "
                "Por favor, digite o Preço Atual no campo exibido para concluir o cadastro!"
            )
        }), 422

    product = database.add_product(
        title=title,
        url=url,
        image_url=image_url,
        store_name=store_name,
        current_price=current_price,
        target_price=target_price,
        notify_email=notify_email
    )

    # Se o produto já foi cadastrado com preço abaixo da meta, dispara o alerta imediatamente!
    alert_result = None
    if product["current_price"] <= product["target_price"]:
        settings = database.get_settings()
        alert_result = mailer.send_price_alert(product, settings)
        database.mark_alert_sent(product["id"])
        product = database.get_product_by_id(product["id"])

    return jsonify({
        "success": True,
        "product": product,
        "alert": alert_result,
        "message": "Produto adicionado ao monitoramento com sucesso!"
    })


@app.route("/api/products/<int:product_id>", methods=["PUT"])
def api_update_product(product_id):
    """
    Atualiza o Preço Alvo (meta) ou o e-mail de notificação de um produto.
    """
    data = request.get_json(silent=True) or {}
    target_price = scraper.clean_price_text(data.get("target_price"))
    notify_email = (data.get("notify_email") or "").strip()

    if not target_price or target_price <= 0:
        return jsonify({"success": False, "error": "Preço Alvo inválido."}), 400

    updated = database.update_product_target(product_id, target_price, notify_email)
    if not updated:
        return jsonify({"success": False, "error": "Produto não encontrado."}), 404

    return jsonify({
        "success": True,
        "product": updated,
        "message": "Meta de preço atualizada!"
    })


@app.route("/api/products/<int:product_id>", methods=["DELETE"])
def api_delete_product(product_id):
    """
    Exclui um produto monitorado.
    """
    database.delete_product(product_id)
    return jsonify({"success": True, "message": "Produto removido do monitoramento."})


@app.route("/api/products/<int:product_id>/check", methods=["POST"])
def api_check_product(product_id):
    """
    Força a verificação imediata de preço de um único produto via Web Scraping.
    """
    result = check_single_product_and_notify(product_id)
    if not result.get("success"):
        return jsonify(result), 404
    return jsonify(result)


@app.route("/api/products/<int:product_id>/simulate-drop", methods=["POST"])
def api_simulate_drop(product_id):
    """
    Simula uma promoção real no produto (colocando o preço entre 5% e 12% abaixo da meta),
    atualizando o gráfico de histórico e disparando o alerta de e-mail na hora!
    Ideal para testar e demonstrar o funcionamento completo do sistema.
    """
    product = database.get_product_by_id(product_id)
    if not product:
        return jsonify({"success": False, "error": "Produto não encontrado."}), 404

    target = float(product["target_price"])
    current = float(product["current_price"])
    base = min(target, current)

    # Calcula um novo preço promocional cerca de 5% a 10% menor que a meta
    discount_factor = random.uniform(0.90, 0.96)
    simulated_price = round(max(1.0, base * discount_factor), 2)

    result = check_single_product_and_notify(product_id, forced_price=simulated_price)
    return jsonify(result)


@app.route("/api/check-all", methods=["POST"])
def api_check_all():
    """
    Verifica todos os produtos cadastrados de uma só vez.
    """
    products = database.get_all_products()
    alerts_triggered = []

    for prod in products:
        res = check_single_product_and_notify(prod["id"])
        if res.get("alert"):
            alerts_triggered.append(res["alert"])

    database.update_last_auto_check()
    return jsonify({
        "success": True,
        "checked_count": len(products),
        "alerts_count": len(alerts_triggered),
        "last_alert": alerts_triggered[-1] if alerts_triggered else None,
        "message": f"{len(products)} produto(s) verificado(s) com sucesso!"
    })


@app.route("/api/seed-demo", methods=["POST"])
def api_seed_demo():
    """
    Recarrega os produtos de demonstração caso o usuário queira testar com exemplos prontos.
    """
    database.seed_demo_products()
    return jsonify({
        "success": True,
        "message": "Produtos de exemplo adicionados ao painel!"
    })


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    """
    Salva as configurações de envio de e-mail (SMTP) e o intervalo do monitor automático.
    """
    data = request.get_json(silent=True) or {}
    current = database.get_settings()

    # Se o campo de senha vier vazio mas já havia uma senha salva, preserva a senha anterior
    smtp_password = data.get("smtp_password")
    if not smtp_password and current.get("smtp_password"):
        smtp_password = current["smtp_password"]

    updated = database.update_settings(
        smtp_email=data.get("smtp_email", ""),
        smtp_password=smtp_password or "",
        default_recipient=data.get("default_recipient", ""),
        smtp_host=data.get("smtp_host", "smtp.gmail.com"),
        smtp_port=data.get("smtp_port", 587),
        check_interval_minutes=data.get("check_interval_minutes", 30),
        auto_check_enabled=data.get("auto_check_enabled", True)
    )

    return jsonify({
        "success": True,
        "settings": updated,
        "message": "Configurações salvas com sucesso!"
    })


@app.route("/api/test-email", methods=["POST"])
def api_test_email():
    """
    Dispara um e-mail de teste usando o primeiro produto da lista (ou um produto fictício)
    para validar as configurações de SMTP ou visualizar o template HTML na tela.
    """
    products = database.get_all_products()
    settings = database.get_settings()

    if products:
        sample_product = products[0]
    else:
        sample_product = {
            "title": "Produto de Teste - Notebook Gamer 16GB RAM RTX 4060",
            "url": "https://www.mercadolivre.com.br",
            "image_url": scraper.DEFAULT_PRODUCT_IMAGE,
            "store_name": "Mercado Livre",
            "current_price": 4299.90,
            "initial_price": 5199.00,
            "highest_price": 5199.00,
            "target_price": 4500.00,
            "notify_email": settings.get("default_recipient") or settings.get("smtp_email")
        }

    alert_result = mailer.send_price_alert(sample_product, settings)
    return jsonify({
        "success": True,
        "alert": alert_result
    })


# =====================================================================
# MONITOR AUTOMÁTICO EM SEGUNDO PLANO (BACKGROUND THREAD)
# =====================================================================

def background_price_monitor():
    """
    Esta função roda em uma Thread separada (em segundo plano) enquanto o servidor estiver ligado.
    A cada minuto ela verifica se já passou o tempo configurado (ex: 30 min) para checar os preços!
    """
    last_run_timestamp = time.time()

    while True:
        time.sleep(20)
        try:
            settings = database.get_settings()
            if not settings.get("auto_check_enabled", 1):
                continue

            interval_seconds = max(1, int(settings.get("check_interval_minutes", 30))) * 60
            if (time.time() - last_run_timestamp) >= interval_seconds:
                products = database.get_all_products()
                for prod in products:
                    check_single_product_and_notify(prod["id"])
                database.update_last_auto_check()
                last_run_timestamp = time.time()
        except Exception as exc:
            print(f"[Monitor Automático] Aviso: {exc}")


# Inicia a thread em segundo plano (daemon=True garante que ela feche junto com o programa)
monitor_thread = threading.Thread(target=background_price_monitor, daemon=True)
monitor_thread.start()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("[PriceRadar] Servidor iniciado com sucesso!")
    print("Acesse no seu navegador: http://127.0.0.1:5000")
    print("=" * 60 + "\n")
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
