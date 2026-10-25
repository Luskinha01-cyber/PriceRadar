"""
scraper.py - Módulo de Web Scraping (Extração de Dados de Produtos)
===================================================================
Este arquivo contém toda a lógica para acessar a página de um produto na internet,
ler o código HTML usando o `BeautifulSoup` e extrair:
1. Nome do Produto (title)
2. Preço Atual (price)
3. Imagem do Produto (image_url)
4. Nome da Loja (store_name)

Dica de Estudo:
- Usamos um cabeçalho `User-Agent` nas requisições HTTP para simular um navegador real
  (Google Chrome no Windows), evitando bloqueios simples de robôs.
- No Mercado Livre, os preços costumam ficar dentro de elementos com a classe
  `andes-money-amount__fraction` (reais) e `andes-money-amount__cents` (centavos),
  ou em metadados estruturados (`application/ld+json` e tags `<meta>`).
"""

import re
import json
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

# Cabeçalhos HTTP que simulam um navegador real para evitar bloqueios
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

DEFAULT_PRODUCT_IMAGE = "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=600&q=80"


def clean_price_text(price_str):
    """
    Converte textos de preço brasileiros (ex: 'R$ 1.899,90' ou '1899.90')
    para um número decimal do Python (`float`, ex: 1899.90).
    """
    if price_str is None:
        return None
    if isinstance(price_str, (int, float)):
        return float(price_str)

    text = str(price_str).strip()
    # Remove símbolos de moeda e espaços
    text = re.sub(r"[^\d,\.]", "", text)
    if not text:
        return None

    # Caso tenha ponto de milhar e vírgula decimal (ex: 1.299,90 -> 1299.90)
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        # Ex: 199,90 -> 199.90
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        # Ex: 1.200.000 -> 1200000
        text = text.replace(".", "")

    try:
        value = float(text)
        return round(value, 2) if value > 0 else None
    except ValueError:
        return None


def detect_store_name(url):
    """
    Identifica o nome amigável da loja a partir do domínio da URL.
    """
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
    # Retorna o domínio limpo caso seja outra loja
    clean_domain = domain.replace("www.", "").split(".")[0].capitalize()
    return clean_domain or "Loja Online"


def extract_from_json_ld(soup):
    """
    Estratégia 1: Muitos sites de e-commerce (incluindo o Mercado Livre) colocam um bloco
    `<script type="application/ld+json">` com os dados oficiais do produto para o Google.
    Ler esse JSON é super confiável!
    """
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            raw_content = script.string or script.get_text()
            if not raw_content:
                continue
            data = json.loads(raw_content)

            # Às vezes o JSON-LD é uma lista de objetos
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Verifica se é um objeto do tipo Product
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
    Estratégia 2: Seletores CSS específicos da página de produto do Mercado Livre.
    """
    result = {"title": None, "price": None, "image_url": None}

    # 1. Título do produto no Mercado Livre
    title_el = (
        soup.select_one("h1.ui-pdp-title")
        or soup.select_one(".ui-pdp-header__title-container h1")
        or soup.find("h1")
    )
    if title_el:
        result["title"] = title_el.get_text(strip=True)

    # 2. Preço principal do produto no Mercado Livre
    # Prioriza o container de preço principal (evitando pegar o valor da parcela ou preço riscado anterior)
    price_containers = [
        soup.select_one(".ui-pdp-price__second-line .andes-money-amount"),
        soup.select_one(".ui-pdp-price__main-container .andes-money-amount:not(.andes-money-amount--previous)"),
        soup.select_one('[ itemprop="offers" ] .andes-money-amount'),
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

    # Fallback para meta tag de preço do Mercado Livre
    if not result["price"]:
        meta_price = (
            soup.find("meta", itemprop="price")
            or soup.find("meta", property="product:price:amount")
            or soup.find("meta", property="og:price:amount")
        )
        if meta_price and meta_price.get("content"):
            result["price"] = clean_price_text(meta_price["content"])

    # 3. Imagem do produto no Mercado Livre
    img_el = (
        soup.select_one("figure.ui-pdp-gallery__figure img")
        or soup.select_one("img.ui-pdp-image")
    )
    if img_el:
        result["image_url"] = img_el.get("data-zoom") or img_el.get("src")

    return result


def extract_from_open_graph(soup):
    """
    Estratégia 3: Metadados OpenGraph (`og:title`, `og:image`, etc.) que quase todos
    os sites usam para gerar pré-visualização de links no WhatsApp/redes sociais.
    """
    result = {"title": None, "price": None, "image_url": None}

    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if og_title and og_title.get("content"):
        result["title"] = og_title["content"].strip()
    elif soup.title and soup.title.string:
        result["title"] = soup.title.string.strip()

    og_image = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    if og_image and og_image.get("content"):
        result["image_url"] = og_image["content"].strip()

    # Tenta encontrar preço no título do OpenGraph (no ML às vezes vem "Produto - R$ 199,90")
    if result["title"]:
        match = re.search(r"R\$\s*([\d\.,]+)", result["title"])
        if match:
            result["price"] = clean_price_text(match.group(1))
            # Limpa o sufixo "- R$ ..." do título se existir
            result["title"] = re.sub(r"\s*-\s*R\$\s*[\d\.,]+.*$", "", result["title"]).strip()

    return result


def scrape_product(url):
    """
    Função principal de Web Scraping!
    Recebe a URL de um produto, faz a requisição HTTP e combina as 3 estratégias
    (JSON-LD, Seletores do Mercado Livre e OpenGraph) para retornar os dados completos.
    """
    if not url or not url.startswith(("http://", "https://")):
        return {
            "success": False,
            "error": "URL inválida. Certifique-se de que o link começa com https://"
        }

    store_name = detect_store_name(url)

    try:
        response = requests.get(url, headers=HEADERS, timeout=12)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return {
            "success": False,
            "store_name": store_name,
            "error": f"Não foi possível acessar a página ({exc.__class__.__name__}). Você também pode preencher o preço manualmente!"
        }

    soup = BeautifulSoup(response.text, "html.parser")

    # Executa as 3 estratégias em sequência para obter a maior precisão possível
    ld_data = extract_from_json_ld(soup)
    ml_data = extract_from_mercado_livre_dom(soup)
    og_data = extract_from_open_graph(soup)

    title = ld_data.get("title") or ml_data.get("title") or og_data.get("title")
    price = ld_data.get("price") or ml_data.get("price") or og_data.get("price")
    image_url = ld_data.get("image_url") or ml_data.get("image_url") or og_data.get("image_url") or DEFAULT_PRODUCT_IMAGE

    # Última tentativa: busca padrão de "R$ 000,00" em elementos de preço genéricos da página
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

    if not title or title.lower() in ("mercado livre", "mercadolivre"):
        # Se a página não retornou título claro, extrai um nome legível a partir do próprio link (slug da URL)
        path_parts = [p for p in urlparse(url).path.split("/") if p and not p.startswith("MLB") and p != "p"]
        if path_parts:
            slug = max(path_parts, key=len)
            title = re.sub(r"[-_]+", " ", slug).replace("JM", "").strip().title()
        else:
            title = f"Produto Monitorado ({store_name})"

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
