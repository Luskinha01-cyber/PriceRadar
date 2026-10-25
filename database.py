"""
database.py - Gerenciamento do Banco de Dados SQLite
====================================================
Este arquivo é responsável por criar e manipular o banco de dados local (priceradar.db).
Usamos a biblioteca nativa `sqlite3` do Python, que não exige instalar nenhum servidor externo.

Tabelas criadas:
1. products: Guarda os produtos cadastrados, preço atual, menor/maior preço e a meta (preço alvo).
2. price_history: Guarda cada leitura de preço ao longo do tempo para gerar o gráfico de evolução.
3. settings: Guarda configurações gerais (e-mail de envio SMTP, senha de app, intervalo de checagem).
"""

import sqlite3
import os
from datetime import datetime, timedelta

# Caminho do arquivo do banco de dados na mesma pasta do projeto
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "priceradar.db")


def get_connection():
    """
    Cria e retorna uma conexão com o banco de dados SQLite.
    O `row_factory = sqlite3.Row` permite acessar as colunas pelo nome (como um dicionário),
    o que torna o código muito mais fácil de ler!
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Cria as tabelas no banco de dados caso elas ainda não existam,
    e inicializa as configurações padrão.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Tabela de Produtos Monitorados
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            image_url TEXT,
            store_name TEXT DEFAULT 'Mercado Livre',
            current_price REAL NOT NULL,
            initial_price REAL NOT NULL,
            lowest_price REAL NOT NULL,
            highest_price REAL NOT NULL,
            target_price REAL NOT NULL,
            notify_email TEXT,
            last_checked TEXT,
            alert_sent INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    # 2. Tabela de Histórico de Preços (Relacionada ao id do produto)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            price REAL NOT NULL,
            checked_at TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
        )
    """)

    # 3. Tabela de Configurações do Sistema (sempre terá apenas 1 linha com id = 1)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            smtp_email TEXT DEFAULT '',
            smtp_password TEXT DEFAULT '',
            default_recipient TEXT DEFAULT '',
             smtp_host TEXT DEFAULT 'smtp.gmail.com',
            smtp_port INTEGER DEFAULT 587,
            check_interval_minutes INTEGER DEFAULT 30,
            auto_check_enabled INTEGER DEFAULT 1,
            last_auto_check TEXT DEFAULT ''
        )
    """)

    # Garante que a linha padrão de configuração existe
    cursor.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")

    conn.commit()
    conn.close()


# =====================================================================
# FUNÇÕES DE PRODUTOS (CRUD - Create, Read, Update, Delete)
# =====================================================================

def add_product(title, url, image_url, store_name, current_price, target_price, notify_email=""):
    """
    Adiciona um novo produto no banco de dados e registra seu primeiro preço no histórico.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO products (
            title, url, image_url, store_name,
            current_price, initial_price, lowest_price, highest_price,
            target_price, notify_email, last_checked, alert_sent, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
    """, (
        title, url, image_url, store_name,
        current_price, current_price, current_price, current_price,
        target_price, notify_email, now, now
    ))

    product_id = cursor.lastrowid

    # Registra o preço inicial na tabela de histórico
    cursor.execute("""
        INSERT INTO price_history (product_id, price, checked_at)
        VALUES (?, ?, ?)
    """, (product_id, current_price, now))

    conn.commit()
    conn.close()
    return get_product_by_id(product_id)


def get_all_products():
    """
    Retorna todos os produtos cadastrados ordenados pelos mais recentes,
    incluindo também os últimos registros de histórico de cada um.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products ORDER BY id DESC")
    rows = cursor.fetchall()

    products = []
    for row in rows:
        prod = dict(row)
        # Busca o histórico de preços deste produto (ordenado do mais antigo para o mais novo)
        cursor.execute("""
            SELECT price, checked_at
            FROM price_history
            WHERE product_id = ?
            ORDER BY id ASC
        """, (prod["id"],))
        prod["history"] = [dict(h) for h in cursor.fetchall()]
        products.append(prod)

    conn.close()
    return products


def get_product_by_id(product_id):
    """
    Busca um único produto pelo seu ID, incluindo seu histórico de preços.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    prod = dict(row)
    cursor.execute("""
        SELECT price, checked_at
        FROM price_history
        WHERE product_id = ?
        ORDER BY id ASC
    """, (prod["id"],))
    prod["history"] = [dict(h) for h in cursor.fetchall()]

    conn.close()
    return prod


def update_product_price(product_id, new_price, title=None, image_url=None):
    """
    Atualiza o preço atual de um produto, recalcula o menor e o maior preço já vistos,
    e adiciona uma nova entrada na tabela `price_history`.
    """
    prod = get_product_by_id(product_id)
    if not prod:
        return None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lowest = min(prod["lowest_price"], new_price)
    highest = max(prod["highest_price"], new_price)

    updated_title = title if title else prod["title"]
    updated_image = image_url if image_url else prod["image_url"]

    # Se o preço subiu acima da meta novamente, reabilita o envio de alerta futuro
    alert_sent = prod["alert_sent"]
    if new_price > prod["target_price"]:
        alert_sent = 0

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE products
        SET current_price = ?,
            lowest_price = ?,
            highest_price = ?,
            title = ?,
            image_url = ?,
            last_checked = ?,
            alert_sent = ?
        WHERE id = ?
    """, (new_price, lowest, highest, updated_title, updated_image, now, alert_sent, product_id))

    cursor.execute("""
        INSERT INTO price_history (product_id, price, checked_at)
        VALUES (?, ?, ?)
    """, (product_id, new_price, now))

    conn.commit()
    conn.close()
    return get_product_by_id(product_id)


def update_product_target(product_id, target_price, notify_email):
    """
    Permite ao usuário editar o Preço Alvo (meta) e o e-mail de alerta de um produto.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE products
        SET target_price = ?,
            notify_email = ?,
            alert_sent = 0
        WHERE id = ?
    """, (target_price, notify_email, product_id))

    conn.commit()
    conn.close()
    return get_product_by_id(product_id)


def mark_alert_sent(product_id):
    """
    Marca que o alerta de promoção já foi enviado para evitar spam de e-mails repetidos.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE products SET alert_sent = 1 WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()


def delete_product(product_id):
    """
    Remove um produto e todo o seu histórico de preços do banco de dados.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM price_history WHERE product_id = ?", (product_id,))
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()


# =====================================================================
# FUNÇÕES DE CONFIGURAÇÕES E DADOS DE EXEMPLO
# =====================================================================

def get_settings():
    """
    Retorna as configurações atuais do sistema.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM settings WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}


def update_settings(smtp_email, smtp_password, default_recipient, smtp_host, smtp_port, check_interval_minutes, auto_check_enabled):
    """
    Salva as configurações de e-mail SMTP e do monitor automático.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE settings
        SET smtp_email = ?,
            smtp_password = ?,
            default_recipient = ?,
            smtp_host = ?,
            smtp_port = ?,
            check_interval_minutes = ?,
            auto_check_enabled = ?
        WHERE id = 1
    """, (
        smtp_email.strip(),
        smtp_password.strip(),
        default_recipient.strip(),
        smtp_host.strip() or "smtp.gmail.com",
        int(smtp_port or 587),
        max(1, int(check_interval_minutes or 30)),
        1 if auto_check_enabled else 0
    ))
    conn.commit()
    conn.close()
    return get_settings()


def update_last_auto_check():
    """
    Registra o horário da última verificação automática.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET last_auto_check = ? WHERE id = 1", (now,))
    conn.commit()
    conn.close()


def seed_demo_products():
    """
    Insere 3 produtos realistas com histórico de preços nos últimos dias
    para que o estudante possa visualizar gráficos, comparações e testar alertas na hora!
    """
    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now()
    demos = [
        {
            "title": "Fone de Ouvido Sem Fio Sony WH-1000XM5 Cancelamento de Ruído Preto",
            "url": "https://www.mercadolivre.com.br/fone-de-ouvido-over-ear-sem-fio-sony-wh-1000xm5-preto/p/MLB19162041",
            "image_url": "https://images.unsplash.com/photo-1618366712010-f4ae9c647dcb?auto=format&fit=crop&w=600&q=80",
            "store_name": "Mercado Livre",
            "prices": [2499.00, 2390.00, 2299.90, 2150.00, 1989.90],
            "target_price": 2050.00,
            "alert_sent": 1
        },
        {
            "title": "Console PlayStation 5 Slim Edição Digital 1TB Branco Sony",
            "url": "https://www.mercadolivre.com.br/console-playstation-5-slim-edicao-digital-1tb-branco-sony/p/MLB29018432",
            "image_url": "https://images.unsplash.com/photo-1606813907291-d86efa9b94db?auto=format&fit=crop&w=600&q=80",
            "store_name": "Mercado Livre",
            "prices": [3799.00, 3699.00, 3649.00, 3549.90, 3499.00],
            "target_price": 3350.00,
            "alert_sent": 0
        },
        {
            "title": "Teclado Mecânico Gamer Sem Fio Logitech G915 TKL RGB Tactile",
            "url": "https://www.mercadolivre.com.br/teclado-mecanico-gamer-sem-fio-logitech-g915-tkl-rgb/p/MLB17482910",
            "image_url": "https://images.unsplash.com/photo-1595225476474-87563907a212?auto=format&fit=crop&w=600&q=80",
            "store_name": "Mercado Livre",
            "prices": [1399.00, 1349.00, 1299.00, 1279.00, 1199.90],
            "target_price": 1150.00,
            "alert_sent": 0
        }
    ]

    for item in demos:
        prices = item["prices"]
        initial_p = prices[0]
        current_p = prices[-1]
        lowest_p = min(prices)
        highest_p = max(prices)
        created_str = (now - timedelta(days=len(prices) - 1)).strftime("%Y-%m-%d %H:%M:%S")
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO products (
                title, url, image_url, store_name,
                current_price, initial_price, lowest_price, highest_price,
                target_price, notify_email, last_checked, alert_sent, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)
        """, (
            item["title"], item["url"], item["image_url"], item["store_name"],
            current_p, initial_p, lowest_p, highest_p,
            item["target_price"], now_str, item["alert_sent"], created_str
        ))

        prod_id = cursor.lastrowid
        for idx, p in enumerate(prices):
            check_time = (now - timedelta(days=len(prices) - 1 - idx)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO price_history (product_id, price, checked_at)
                VALUES (?, ?, ?)
            """, (prod_id, p, check_time))

    conn.commit()
    conn.close()
