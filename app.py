"""
app.py - Servidor Principal (Backend Flask + Monitor Automático)
================================================================
Conecta a interface web, o banco SQLite, o scraper e o disparador de e-mails.

MODELO MULTIUSUÁRIO (identificação só pelo e-mail, sem senha):
- A pessoa digita o e-mail dela e o servidor grava um cookie de sessão ASSINADO.
- Cada produto pertence a um e-mail dono (`owner_email`); cada pessoa só vê,
  edita, exclui e recebe alertas dos PRÓPRIOS produtos.
- ATENÇÃO: isso é identificação, não autenticação forte. Quem souber o e-mail de
  outra pessoa conseguiria "entrar" como ela. Para algo mais seguro, o próximo
  passo é o login por link mágico enviado ao e-mail (veja o README).

Como executar:
  python app.py
Depois, abra http://127.0.0.1:5000 no navegador!

Variáveis de ambiente opcionais (nada disso aparece na interface):
  SECRET_KEY, FLASK_DEBUG, HOST, PORT, COOKIE_SECURE,
  CHECK_INTERVAL_MINUTES, AUTO_CHECK_ENABLED, MAX_PRODUCTS_PER_USER,
  SMTP_EMAIL, SMTP_PASSWORD, SMTP_HOST, SMTP_PORT
"""

import os
import re
import time
import random
import secrets
import threading
from collections import defaultdict, deque
from datetime import timedelta
from functools import wraps

from flask import Flask, render_template, request, jsonify, session, send_from_directory

import database
import scraper
import mailer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------
# CONFIGURAÇÕES DO SERVIDOR (lidas do ambiente, com padrões seguros)
# ---------------------------------------------------------------------
CHECK_INTERVAL_MINUTES = max(1, int(os.environ.get("CHECK_INTERVAL_MINUTES", "30")))
AUTO_CHECK_ENABLED = os.environ.get("AUTO_CHECK_ENABLED", "1") == "1"
MAX_PRODUCTS_PER_USER = max(1, int(os.environ.get("MAX_PRODUCTS_PER_USER", "10")))
MAX_PRICE = 10_000_000
MAX_TITLE_LENGTH = 200
CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "PriceRadar"


def load_secret_key():
    """
    Chave que assina o cookie de sessão. Usa a variável SECRET_KEY se existir;
    senão gera uma chave aleatória e a guarda no arquivo `.secret_key` (ignorado pelo Git),
    para que as sessões sobrevivam a reinícios do servidor.
    """
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    key_path = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as key_file:
            stored = key_file.read().strip()
            if stored:
                return stored

    if os.environ.get("VERCEL"):
        import hashlib
        seed = os.environ.get("VERCEL_PROJECT_ID") or os.environ.get("VERCEL_URL") or "priceradar-vercel-default-seed"
        return hashlib.sha256(f"priceradar-secret-{seed}".encode("utf-8")).hexdigest()

    new_key = secrets.token_hex(32)
    try:
        with open(key_path, "w", encoding="utf-8") as key_file:
            key_file.write(new_key)
    except OSError:
        pass
    return new_key


app = Flask(__name__)
app.secret_key = load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=64 * 1024,  # corpo de requisição de no máximo 64 KB
)

database.init_db()


# =====================================================================
# SEGURANÇA: CSRF, CABEÇALHOS, LIMITE DE REQUISIÇÕES E LOGIN
# =====================================================================

@app.before_request
def require_csrf_header():
    """
    Proteção CSRF: toda requisição que altera dados precisa do cabeçalho
    `X-Requested-With: PriceRadar`. Um site malicioso não consegue enviar
    esse cabeçalho personalizado a partir de outro domínio (o navegador bloqueia).
    """
    if request.path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE"):
        if request.headers.get(CSRF_HEADER_NAME) != CSRF_HEADER_VALUE:
            return jsonify({"success": False, "error": "Requisição bloqueada (cabeçalho de segurança ausente)."}), 403


@app.after_request
def add_security_headers(response):
    """
    Cabeçalhos de segurança em todas as respostas.
    """
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' https: data:; "
        "connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


_rate_buckets = defaultdict(deque)
_rate_lock = threading.Lock()


def rate_limit(name, max_calls, window_seconds, per_user=False):
    """
    Limita quantas vezes uma rota pode ser chamada por IP (ou por usuário logado)
    dentro de uma janela de tempo. Evita abuso, spam de e-mail e exaustão do servidor.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            identity = (session.get("email") if per_user else None) or request.remote_addr
            key = (name, identity)
            now = time.time()
            with _rate_lock:
                bucket = _rate_buckets[key]
                while bucket and now - bucket[0] > window_seconds:
                    bucket.popleft()
                if len(bucket) >= max_calls:
                    return jsonify({
                        "success": False,
                        "error": "Muitas tentativas em pouco tempo. Aguarde um instante e tente de novo."
                    }), 429
                bucket.append(now)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def login_required(func):
    """
    Exige que a pessoa já tenha informado o e-mail (sessão ativa).
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("email"):
            return jsonify({
                "success": False,
                "need_login": True,
                "error": "Informe seu e-mail para continuar."
            }), 401
        return func(*args, **kwargs)
    return wrapper


def current_email():
    return session.get("email", "")


def get_owned_product(product_id):
    """
    Busca o produto apenas se ele pertencer à pessoa logada.
    Produtos de outras pessoas respondem como "não encontrado".
    """
    return database.get_product_for_owner(product_id, current_email())


def parse_price(value):
    """
    Converte e valida um preço digitado (entre 0,01 e MAX_PRICE).
    """
    price = scraper.clean_price_text(value)
    if price is None or price <= 0 or price > MAX_PRICE:
        return None
    return round(price, 2)


# =====================================================================
# LÓGICA DE VERIFICAÇÃO E ALERTA
# =====================================================================

def check_single_product_and_notify(product_id, forced_price=None, force_alert=False):
    """
    Atualiza o preço de um produto (scraping real ou simulação) e dispara o alerta
    para o DONO quando o preço atinge a meta.
    O alerta é enviado uma única vez por queda (só reenvia depois que o preço
    voltar acima da meta), para não lotar a caixa de entrada a cada verificação.
    """
    product = database.get_product_by_id(product_id)
    if not product:
        return {"success": False, "error": "Produto não encontrado."}

    if forced_price is not None:
        new_price = round(float(forced_price), 2)
        updated_product = database.update_product_price(product_id, new_price)
        scrape_note = "Queda de preço simulada com sucesso!"
    else:
        scraped = scraper.scrape_product(product["url"])
        if scraped.get("success") and scraped.get("price"):
            updated_product = database.update_product_price(
                product_id,
                scraped["price"],
                title=scraped.get("title"),
                image_url=scraped.get("image_url")
            )
            scrape_note = "Preço atualizado via Web Scraping em tempo real!"
        else:
            updated_product = database.update_product_price(product_id, product["current_price"])
            scrape_note = (
                "O site limitou a leitura automática neste instante; "
                "mantivemos o último preço registrado."
            )

    alert_result = None
    hit_target = updated_product["current_price"] <= updated_product["target_price"]
    if hit_target and (force_alert or not updated_product["alert_sent"]):
        alert_result = mailer.send_price_alert(updated_product)
        database.mark_alert_sent(product_id)
        updated_product = database.get_product_by_id(product_id)

    return {
        "success": True,
        "product": updated_product,
        "note": scrape_note,
        "alert": alert_result
    }


# =====================================================================
# ROTAS DA INTERFACE E API REST
# =====================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, "static", "img"), "favicon.png", mimetype="image/png")


@app.route("/api/state", methods=["GET"])
def api_get_state():
    """
    Retorna SOMENTE os produtos da pessoa logada, as estatísticas dela e
    configurações públicas do monitor (nenhuma credencial é exposta).
    """
    email = current_email()
    products = database.get_all_products(email) if email else []

    deals_count = sum(1 for p in products if p["current_price"] <= p["target_price"])
    total_savings = sum(max(0.0, p["highest_price"] - p["current_price"]) for p in products)

    return jsonify({
        "user_email": email or None,
        "products": products,
        "settings": {
            "auto_check_enabled": AUTO_CHECK_ENABLED,
            "check_interval_minutes": CHECK_INTERVAL_MINUTES,
            "max_products": MAX_PRODUCTS_PER_USER
        },
        "stats": {
            "total_products": len(products),
            "deals_count": deals_count,
            "total_savings": round(total_savings, 2)
        }
    })


@app.route("/api/session", methods=["POST"])
@rate_limit("session", 10, 600)
def api_start_session():
    """
    "Login" por e-mail: valida o formato e grava o e-mail na sessão assinada.
    """
    data = request.get_json(silent=True) or {}
    email = database.normalize_email(data.get("email"))

    if len(email) > 254 or not mailer.EMAIL_RE.match(email):
        return jsonify({"success": False, "error": "Digite um e-mail válido (ex: voce@gmail.com)."}), 400

    session.clear()
    session["email"] = email
    session.permanent = True
    return jsonify({"success": True, "email": email, "message": "E-mail identificado! Seus alertas chegarão aqui."})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/scrape-preview", methods=["POST"])
@login_required
@rate_limit("scrape-preview", 8, 60, per_user=True)
def api_scrape_preview():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    return jsonify(scraper.scrape_product(url))


@app.route("/api/products", methods=["POST"])
@login_required
@rate_limit("add-product", 10, 60, per_user=True)
def api_add_product():
    """
    Cadastra um produto para a pessoa logada (o alerta vai para o e-mail dela).
    """
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    manual_title = (data.get("title") or "").strip()[:MAX_TITLE_LENGTH]
    manual_image = (data.get("image_url") or "").strip()
    manual_price = parse_price(data.get("current_price")) if data.get("current_price") not in (None, "") else None
    target_price = parse_price(data.get("target_price"))

    url_ok, url_error = scraper.validate_public_url(url)
    if not url_ok:
        return jsonify({"success": False, "error": f"URL não permitida: {url_error}"}), 400
    if not target_price:
        return jsonify({"success": False, "error": "Informe um Preço Alvo válido."}), 400
    if database.count_products_by_owner(current_email()) >= MAX_PRODUCTS_PER_USER:
        return jsonify({
            "success": False,
            "error": f"Limite de {MAX_PRODUCTS_PER_USER} produtos por e-mail atingido. Remova algum para adicionar outro."
        }), 400

    scraped = {}
    if not manual_price or not manual_title:
        scraped = scraper.scrape_product(url)

    title = manual_title or scraped.get("title") or "Produto Monitorado"
    current_price = manual_price or scraped.get("price")
    image_url = manual_image if manual_image.startswith(("http://", "https://")) else ""
    image_url = image_url or scraped.get("image_url") or scraper.DEFAULT_PRODUCT_IMAGE
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
                "Digite o Preço Atual no campo exibido para concluir o cadastro!"
            )
        }), 422

    product = database.add_product(
        title=title,
        url=url,
        image_url=image_url,
        store_name=store_name,
        current_price=current_price,
        target_price=target_price,
        notify_email=current_email(),
        owner_email=current_email()
    )

    alert_result = None
    if product["current_price"] <= product["target_price"]:
        alert_result = mailer.send_price_alert(product)
        database.mark_alert_sent(product["id"])
        product = database.get_product_by_id(product["id"])

    return jsonify({
        "success": True,
        "product": product,
        "alert": alert_result,
        "message": "Produto adicionado ao monitoramento com sucesso!"
    })


@app.route("/api/products/<int:product_id>", methods=["PUT"])
@login_required
def api_update_product(product_id):
    if not get_owned_product(product_id):
        return jsonify({"success": False, "error": "Produto não encontrado."}), 404

    data = request.get_json(silent=True) or {}
    target_price = parse_price(data.get("target_price"))
    if not target_price:
        return jsonify({"success": False, "error": "Preço Alvo inválido."}), 400

    updated = database.update_product_target(product_id, target_price, current_email())
    return jsonify({"success": True, "product": updated, "message": "Meta de preço atualizada!"})


@app.route("/api/products/<int:product_id>", methods=["DELETE"])
@login_required
def api_delete_product(product_id):
    if not get_owned_product(product_id):
        return jsonify({"success": False, "error": "Produto não encontrado."}), 404

    database.delete_product(product_id)
    return jsonify({"success": True, "message": "Produto removido do monitoramento."})


@app.route("/api/products/<int:product_id>/check", methods=["POST"])
@login_required
@rate_limit("check", 6, 60, per_user=True)
def api_check_product(product_id):
    if not get_owned_product(product_id):
        return jsonify({"success": False, "error": "Produto não encontrado."}), 404
    return jsonify(check_single_product_and_notify(product_id))


@app.route("/api/products/<int:product_id>/simulate-drop", methods=["POST"])
@login_required
@rate_limit("simulate", 5, 600, per_user=True)
def api_simulate_drop(product_id):
    """
    Simula uma promoção (preço 4% a 10% abaixo da meta) e dispara o alerta,
    ideal para testar o fluxo completo.
    """
    product = get_owned_product(product_id)
    if not product:
        return jsonify({"success": False, "error": "Produto não encontrado."}), 404

    base = min(float(product["target_price"]), float(product["current_price"]))
    simulated_price = round(max(1.0, base * random.uniform(0.90, 0.96)), 2)
    return jsonify(check_single_product_and_notify(product_id, forced_price=simulated_price, force_alert=True))


@app.route("/api/check-all", methods=["POST"])
@login_required
@rate_limit("check-all", 2, 60, per_user=True)
def api_check_all():
    """
    Verifica todos os produtos DA PESSOA logada.
    """
    products = database.get_all_products(current_email())
    alerts_triggered = []

    for prod in products:
        result = check_single_product_and_notify(prod["id"])
        if result.get("alert"):
            alerts_triggered.append(result["alert"])

    return jsonify({
        "success": True,
        "checked_count": len(products),
        "alerts_count": len(alerts_triggered),
        "last_alert": alerts_triggered[-1] if alerts_triggered else None,
        "message": f"{len(products)} produto(s) verificado(s) com sucesso!"
    })


@app.route("/api/seed-demo", methods=["POST"])
@login_required
@rate_limit("seed-demo", 3, 600, per_user=True)
def api_seed_demo():
    """
    Adiciona 3 produtos de exemplo na conta da pessoa logada.
    """
    if database.count_products_by_owner(current_email()) + 3 > MAX_PRODUCTS_PER_USER:
        return jsonify({"success": False, "error": "Você não tem espaço suficiente para os exemplos (remova algum produto)."}), 400

    database.seed_demo_products(current_email())
    return jsonify({"success": True, "message": "Produtos de exemplo adicionados ao seu painel!"})


@app.route("/api/test-email", methods=["POST"])
@login_required
@rate_limit("test-email", 3, 600, per_user=True)
def api_test_email():
    """
    Envia um e-mail de teste para o e-mail da PRÓPRIA pessoa logada
    (nunca para um endereço arbitrário).
    """
    email = current_email()
    products = database.get_all_products(email)

    if products:
        sample_product = dict(products[0])
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
        }
    sample_product["owner_email"] = email

    return jsonify({"success": True, "alert": mailer.send_price_alert(sample_product)})


# =====================================================================
# MONITOR AUTOMÁTICO EM SEGUNDO PLANO (BACKGROUND THREAD)
# =====================================================================

def background_price_monitor():
    """
    Roda em uma Thread separada: a cada intervalo configurado, verifica os preços
    de todos os produtos que têm um dono e avisa cada dono por e-mail.
    """
    last_run_timestamp = time.time()

    while True:
        time.sleep(20)
        try:
            if not AUTO_CHECK_ENABLED:
                continue

            if (time.time() - last_run_timestamp) >= CHECK_INTERVAL_MINUTES * 60:
                for prod in database.get_all_products():
                    if prod.get("owner_email"):
                        check_single_product_and_notify(prod["id"])
                last_run_timestamp = time.time()
        except Exception as exc:
            print(f"[Monitor Automático] Aviso: {exc.__class__.__name__}")


if not os.environ.get("VERCEL"):
    monitor_thread = threading.Thread(target=background_price_monitor, daemon=True)
    monitor_thread.start()


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"  # NUNCA ligue em produção

    print("\n" + "=" * 60)
    print("[PriceRadar] Servidor iniciado com sucesso!")
    print(f"Acesse no seu navegador: http://{host}:{port}")
    print("=" * 60 + "\n")
    app.run(host=host, port=port, debug=debug_mode, use_reloader=False)
