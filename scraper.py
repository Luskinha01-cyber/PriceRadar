"""
scraper.py - Módulo de Web Scraping (Extração de Dados de Produtos)
===================================================================
Este arquivo contém a lógica para acessar a página de um produto na internet,
ler o HTML com `BeautifulSoup` e extrair:
1. Nome do Produto (title)
2. Preço Atual (price)
3. Imagem do Produto (image_url)
4. Nome da Loja (store_name)

Como o Mercado Livre utiliza proteção CloudFront + desafio JavaScript de 2 segundos,
implementamos uma busca em 2 estágios:
- Estágio 1 (Rápido): Requisição HTTP direta com `requests`.
- Estágio 2 (Headless Browser Real): Caso a página exija execução de JavaScript
  (desafio anti-bot do Mercado Livre), usa o `Playwright` com o Google Chrome local
  em modo invisível para aguardar o preço real carregar no DOM!
"""

import re
import json
import time
import socket
import ipaddress
import threading
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------
# SEGURANÇA — proteção contra SSRF (Server-Side Request Forgery)
# O usuário informa a URL, então o SERVIDOR é quem faz a requisição.
# Sem validação, alguém poderia pedir http://127.0.0.1/... ou o IP de
# metadados da nuvem (169.254.169.254) e ler serviços internos da máquina.
# ---------------------------------------------------------------------
ALLOWED_PORTS = (None, 80, 443)
MAX_URL_LENGTH = 2048
MAX_REDIRECTS = 3
MAX_HTML_BYTES = 3_000_000
MAX_TITLE_LENGTH = 200

# Cache curto de resolução de DNS (evita consultar o DNS a cada recurso da página)
_HOST_CACHE = {}
_HOST_CACHE_TTL = 60

# No máximo 2 navegadores Chrome ao mesmo tempo (evita esgotar a memória do servidor)
_BROWSER_SLOTS = threading.BoundedSemaphore(2)


def _host_is_public(hostname):
    """
    Retorna True apenas se TODOS os IPs do domínio forem públicos (da internet).
    Bloqueia localhost, redes privadas (10.x, 192.168.x), link-local (169.254.x) etc.
    """
    now = time.time()
    cached = _HOST_CACHE.get(hostname)
    if cached and now - cached[1] < _HOST_CACHE_TTL:
        return cached[0]

    try:
        infos = socket.getaddrinfo(hostname, None)
        addresses = {info[4][0].split("%")[0] for info in infos}
        result = bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)
    except (socket.gaierror, ValueError, UnicodeError):
        result = False

    _HOST_CACHE[hostname] = (result, now)
    return result


def validate_public_url(url):
    """
    Valida se a URL é segura para o servidor acessar.
    Retorna (True, "") se for segura ou (False, "motivo") se não for.
    """
    if not url or not isinstance(url, str) or len(url) > MAX_URL_LENGTH:
        return False, "URL vazia ou muito longa."

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False, "A URL precisa começar com http:// ou https://"
    if not parsed.hostname:
        return False, "URL sem endereço de site válido."
    if parsed.username or parsed.password:
        return False, "URLs com usuário e senha não são permitidas."

    try:
        port = parsed.port
    except ValueError:
        return False, "Porta da URL inválida."
    if port not in ALLOWED_PORTS:
        return False, "Apenas as portas padrão 80 e 443 são permitidas."

    if not _host_is_public(parsed.hostname):
        return False, "Esse endereço não é um site público da internet."

    return True, ""


def safe_get_html(url):
    """
    Faz o download da página validando CADA redirecionamento (um site público
    poderia redirecionar para um IP interno) e limitando o tamanho da resposta.
    Retorna o HTML (str) ou None se bloqueado/erro.
    """
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        ok, _reason = validate_public_url(current_url)
        if not ok:
            return None

        response = requests.get(current_url, headers=HEADERS, timeout=8, allow_redirects=False, stream=True)
        try:
            if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    return None
                current_url = urljoin(current_url, location)
                continue

            if response.status_code != 200:
                return None

            chunks, total = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > MAX_HTML_BYTES:
                    break
                chunks.append(chunk)
            encoding = response.encoding or "utf-8"
            return b"".join(chunks).decode(encoding, errors="replace")
        finally:
            response.close()
    return None


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

DEFAULT_PRODUCT_IMAGE = "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=600&q=80"


def clean_price_text(price_str):
    """
    Converte textos de preço brasileiros (ex: 'R$ 7.999,00' ou '7999.00')
    para um número decimal do Python (`float`, ex: 7999.0).
    """
    if price_str is None:
        return None
    if isinstance(price_str, (int, float)):
        return float(price_str)

    text = str(price_str).strip()
    text = re.sub(r"[^\d,\.]", "", text)
    if not text:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")

    try:
        value = float(text)
        return round(value, 2) if value > 0 else None
    except ValueError:
        return None


def detect_store_name(url):
    domain = urlparse(url).netloc.lower()
    if "mercadolivre" in domain or "mercadolibre" in domain:
        return "Mercado Livre"
    if "amazon" in domain:
        return "Amazon"
    if "kabum" in domain:
        return "KaBuM!"
    if "magazineluiza" in domain or "magalu" in domain:
        return "Magalu"
    if "shopee" in domain:
        return "Shopee"
    if "aliexpress" in domain:
        return "AliExpress"
    clean_domain = domain.replace("www.", "").split(".")[0].capitalize()
    return clean_domain or "Loja Online"


def extract_from_json_ld(soup):
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            raw_content = script.string or script.get_text()
            if not raw_content:
                continue
            data = json.loads(raw_content)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("@type", "")).lower()
                if "product" in item_type or "offers" in item:
                    title = item.get("name")
                    image = item.get("image")
                    if isinstance(image, list) and image:
                        image = image[0]
                    elif isinstance(image, dict):
                        image = image.get("url")

                    offers = item.get("offers", {})
                    if isinstance(offers, list) and offers:
                        offers = offers[0]

                    price = None
                    if isinstance(offers, dict):
                        price = clean_price_text(offers.get("price") or offers.get("lowPrice"))

                    if title or price:
                        return {
                            "title": title,
                            "price": price,
                            "image_url": image
                        }
        except Exception:
            continue
    return {}


def extract_from_mercado_livre_dom(soup):
    """
    Seletores CSS específicos da página de produto do Mercado Livre.
    Captura o preço principal à vista / Pix (ex: R$ 7.999) ignorando preço riscado e parcelas.
    """
    result = {"title": None, "price": None, "image_url": None}

    title_el = (
        soup.select_one("h1.ui-pdp-title")
        or soup.select_one(".ui-pdp-header__title-container h1")
    )
    if title_el:
        result["title"] = title_el.get_text(strip=True)

    price_containers = [
        soup.select_one(".ui-pdp-price__second-line .andes-money-amount"),
        soup.select_one(".ui-pdp-price__main-container .andes-money-amount:not(.andes-money-amount--previous)"),
        soup.select_one('[itemprop="offers"] .andes-money-amount'),
        soup.select_one(".andes-money-amount:not(.andes-money-amount--previous)"),
    ]

    for container in price_containers:
        if not container:
            continue
        fraction_el = container.select_one(".andes-money-amount__fraction")
        cents_el = container.select_one(".andes-money-amount__cents")
        if fraction_el:
            fraction_text = re.sub(r"[^\d]", "", fraction_el.get_text(strip=True))
            cents_text = re.sub(r"[^\d]", "", cents_el.get_text(strip=True)) if cents_el else "00"
            if fraction_text:
                result["price"] = float(f"{fraction_text}.{cents_text[:2].ljust(2, '0')}")
                break

    if not result["price"]:
        meta_price = (
            soup.find("meta", itemprop="price")
            or soup.find("meta", property="product:price:amount")
            or soup.find("meta", property="og:price:amount")
        )
        if meta_price and meta_price.get("content"):
            result["price"] = clean_price_text(meta_price["content"])

    img_el = (
        soup.select_one("figure.ui-pdp-gallery__figure img")
        or soup.select_one("img.ui-pdp-image")
    )
    if img_el:
        result["image_url"] = img_el.get("data-zoom") or img_el.get("src")

    return result


def extract_from_open_graph(soup):
    result = {"title": None, "price": None, "image_url": None}

    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if og_title and og_title.get("content"):
        result["title"] = og_title["content"].strip()
    elif soup.title and soup.title.string:
        t = soup.title.string.strip()
        if t.lower() not in ("mercado libre", "mercado livre") and not t.lower().startswith("loading "):
            result["title"] = t

    og_image = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    if og_image and og_image.get("content"):
        result["image_url"] = og_image["content"].strip()

    if result["title"]:
        match = re.search(r"R\$\s*([\d\.,]+)", result["title"])
        if match:
            result["price"] = clean_price_text(match.group(1))
            result["title"] = re.sub(r"\s*-\s*R\$\s*[\d\.,]+.*$", "", result["title"]).strip()

    return result


def _route_guard(route):
    """
    Dentro do Chrome headless, bloqueia qualquer requisição (inclusive redirecionamentos
    e recursos da página) que aponte para endereços internos/privados.
    """
    request_url = route.request.url
    if request_url.startswith(("data:", "blob:", "about:")):
        route.continue_()
        return
    ok, _reason = validate_public_url(request_url)
    if ok:
        route.continue_()
    else:
        route.abort()


def fetch_html_with_playwright(url):
    """
    Usa o navegador Chrome em modo Headless via Playwright para resolver o desafio
    JavaScript do Mercado Livre e obter o DOM completo renderizado com o preço real.
    Limitado a 2 navegadores simultâneos e com todas as requisições validadas (anti-SSRF).
    """
    ok, _reason = validate_public_url(url)
    if not ok:
        return None

    if not _BROWSER_SLOTS.acquire(timeout=20):
        return None

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    channel="chrome",
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )
            except Exception:
                browser = p.chromium.launch(
                    channel="msedge",
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )

            try:
                temp_page = browser.new_page()
                real_ua = temp_page.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
                temp_page.close()

                ctx = browser.new_context(user_agent=real_ua, locale="pt-BR")
                page = ctx.new_page()
                page.route("**/*", _route_guard)
                page.goto(url, wait_until="domcontentloaded", timeout=15000)

                try:
                    page.wait_for_selector("h1.ui-pdp-title, .andes-money-amount__fraction", timeout=9000)
                except Exception:
                    page.wait_for_timeout(2500)

                return page.content()
            finally:
                browser.close()
    except Exception:
        return None
    finally:
        _BROWSER_SLOTS.release()


def parse_product_soup(soup):
    """
    Combina os extratores priorizando o DOM específico do Mercado Livre (que traz o preço Pix/à vista exato).
    """
    ml_data = extract_from_mercado_livre_dom(soup)
    ld_data = extract_from_json_ld(soup)
    og_data = extract_from_open_graph(soup)

    title = ml_data.get("title") or ld_data.get("title") or og_data.get("title")
    price = ml_data.get("price") or ld_data.get("price") or og_data.get("price")
    image_url = ml_data.get("image_url") or ld_data.get("image_url") or og_data.get("image_url")

    if not price:
        price_candidates = soup.find_all(
            lambda tag: tag.name in ("span", "div", "strong", "p")
            and tag.get("class")
            and any("price" in c.lower() or "preco" in c.lower() or "valor" in c.lower() for c in tag.get("class", []))
        )
        for candidate in price_candidates:
            match = re.search(r"R\$\s*([\d\.]+(?:,\d{2})?)", candidate.get_text(" ", strip=True))
            if match:
                parsed = clean_price_text(match.group(1))
                if parsed:
                    price = parsed
                    break

    return title, price, image_url


def scrape_product(url):
    """
    Função principal de Web Scraping:
    1. Tenta leitura rápida via `requests`.
    2. Se o site retornar desafio JS (como o CloudFront do Mercado Livre),
       aciona automaticamente o navegador headless via Playwright para ler o preço real!
    """
    url = (url or "").strip()
    url_ok, url_error = validate_public_url(url)
    if not url_ok:
        return {
            "success": False,
            "error": f"URL não permitida: {url_error}"
        }

    store_name = detect_store_name(url)
    title, price, image_url = None, None, None

    # 1. Tentativa rápida via HTTP (com validação anti-SSRF a cada redirecionamento)
    try:
        html_text = safe_get_html(url)
        if html_text:
            soup = BeautifulSoup(html_text, "html.parser")
            title, price, image_url = parse_product_soup(soup)
    except requests.exceptions.RequestException:
        pass

    # 2. Se o preço não veio (bloqueio anti-bot / desafio JS do Mercado Livre), usa Playwright
    if not price:
        rendered_html = fetch_html_with_playwright(url)
        if rendered_html:
            soup = BeautifulSoup(rendered_html, "html.parser")
            title, price, image_url = parse_product_soup(soup)

    if not title or title.lower() in ("mercado livre", "mercado libre", "mercadolivre"):
        path_parts = [p for p in urlparse(url).path.split("/") if p and not p.startswith("MLB") and p != "p"]
        if path_parts:
            slug = max(path_parts, key=len)
            title = re.sub(r"[-_]+", " ", slug).replace("JM", "").strip().title()
        else:
            title = f"Produto Monitorado ({store_name})"

    image_url = image_url or DEFAULT_PRODUCT_IMAGE
    if not str(image_url).startswith(("http://", "https://")):
        image_url = DEFAULT_PRODUCT_IMAGE
    title = (title or "")[:MAX_TITLE_LENGTH]

    if not price:
        return {
            "success": False,
            "partial": True,
            "title": title,
            "image_url": image_url,
            "store_name": store_name,
            "error": (
                "Encontramos a página, mas o site protegeu o preço contra leitura automática. "
                "Informe o Preço Atual no campo abaixo para iniciar o monitoramento!"
            )
        }

    return {
        "success": True,
        "title": title,
        "price": round(float(price), 2),
        "image_url": image_url,
        "store_name": store_name
    }
