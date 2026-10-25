"""
mailer.py - Módulo de Envio Automático de Alertas por E-mail
============================================================
Permite enviar alertas de queda de preço de 2 formas:
1. Modo Direto Zero-Config (Padrão): O usuário informa APENAS o e-mail dele
   e o sistema dispara via relay HTTPS (FormSubmit AJAX API) sem exigir senha!
2. Modo SMTP Próprio (Opcional): Caso variáveis de ambiente ou credenciais SMTP
   tenham sido informadas, envia diretamente via `smtplib` TLS.
"""

import os
import re
import html
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import requests

# Validação estrita de e-mail (também impede injeção de cabeçalhos e de caminho na URL do relay)
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")


def esc(value):
    """
    Escapa texto para colocar com segurança dentro de HTML.
    Títulos de produtos vêm de sites externos (ou do usuário) e NUNCA devem
    ser inseridos no HTML do e-mail/prévia sem escape (evita XSS).
    """
    return html.escape(str(value if value is not None else ""), quote=True)


def safe_http_url(value, fallback="#"):
    """
    Só aceita links http/https (bloqueia javascript:, data: etc.).
    """
    text = str(value or "").strip()
    return text if text.startswith(("http://", "https://")) else fallback


def format_brl(value):
    try:
        val = float(value)
        formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {formatted}"
    except (ValueError, TypeError):
        return "R$ 0,00"


def build_alert_email_html(product):
    current_price = float(product.get("current_price", 0))
    initial_price = float(product.get("initial_price", current_price))
    target_price = float(product.get("target_price", current_price))

    reference_price = max(initial_price, float(product.get("highest_price", initial_price)))
    savings = max(0.0, reference_price - current_price)
    discount_pct = round((savings / reference_price) * 100) if reference_price > 0 else 0
    now_str = datetime.now().strftime("%d/%m/%Y · %H:%M")
    title = esc(product.get('title', 'Produto Monitorado'))
    store = esc(product.get('store_name', 'Mercado Livre'))
    image = esc(safe_http_url(product.get('image_url'), ""))
    link = esc(safe_http_url(product.get('url')))

    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
    </head>
    <body style="margin:0; padding:28px; background-color:#09090b; font-family:-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif; color:#f4f4f5;">
        <div style="max-width:520px; margin:0 auto; background-color:#0e0e11; border-radius:10px; overflow:hidden; border:1px solid rgba(255,255,255,0.1);">
            <div style="padding:20px 24px; border-bottom:1px solid rgba(255,255,255,0.07); display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <div style="font-family:monospace; font-size:11px; color:#10b981; letter-spacing:1px; text-transform:uppercase;">
                        PRICERADAR · GATILHO ATINGIDO
                    </div>
                    <h1 style="margin:6px 0 0; font-size:18px; font-weight:600; color:#f4f4f5;">
                        Cotação abaixo do seu preço alvo
                    </h1>
                </div>
            </div>

            <div style="padding:24px;">
                <div style="display:flex; gap:16px; align-items:center; margin-bottom:20px;">
                    <div style="background:#ffffff; padding:8px; border-radius:6px; width:72px; height:72px; text-align:center;">
                        <img src="{image}" alt="Produto" style="max-width:100%; max-height:100%; object-fit:contain;" />
                    </div>
                    <div>
                        <div style="font-family:monospace; font-size:11px; color:#71717a; text-transform:uppercase;">
                            {store} · {now_str}
                        </div>
                        <h2 style="font-size:15px; font-weight:500; line-height:1.4; color:#f4f4f5; margin:4px 0 0;">
                            {title}
                        </h2>
                    </div>
                </div>

                <div style="background:#09090b; border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:16px; margin-bottom:20px;">
                    <table style="width:100%; border-collapse:collapse; font-family:monospace;">
                        <tr>
                            <td style="padding:6px 0; color:#71717a; font-size:12px;">MÁXIMO REGISTRADO</td>
                            <td style="padding:6px 0; text-align:right; color:#71717a; font-size:13px; text-decoration:line-through;">
                                {format_brl(reference_price)}
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:6px 0; color:#a1a1aa; font-size:12px;">SEU ALVO DEFINIDO</td>
                            <td style="padding:6px 0; text-align:right; color:#f4f4f5; font-size:13px;">
                                {format_brl(target_price)}
                            </td>
                        </tr>
                        <tr style="border-top:1px solid rgba(255,255,255,0.07);">
                            <td style="padding:12px 0 4px; color:#10b981; font-size:13px; font-weight:600;">COTAÇÃO ATUAL</td>
                            <td style="padding:12px 0 4px; text-align:right; color:#10b981; font-size:20px; font-weight:700;">
                                {format_brl(current_price)}
                            </td>
                        </tr>
                    </table>
                </div>

                {f'<div style="background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.25); color:#10b981; padding:10px 14px; border-radius:6px; font-family:monospace; font-size:12px; margin-bottom:20px;">VARIAÇÃO: -{format_brl(savings)} (-{discount_pct}%) vs. topo histórico</div>' if savings > 0 else ''}

                <div>
                    <a href="{link}" target="_blank" rel="noopener noreferrer" style="display:inline-block; background:#f4f4f5; color:#09090b; text-decoration:none; padding:11px 20px; border-radius:6px; font-weight:600; font-size:13px;">
                        Abrir anúncio na loja &rarr;
                    </a>
                </div>
            </div>

            <div style="padding:14px 24px; font-family:monospace; font-size:11px; color:#71717a; border-top:1px solid rgba(255,255,255,0.07);">
                PriceRadar · Monitoramento Automatizado em Python
            </div>
        </div>
    </body>
    </html>
    """


def send_via_zero_config_relay(recipient, product, subject, html_content):
    """
    Envia o e-mail automaticamente apenas com o endereço do destinatário,
    sem precisar de Senha de App ou servidor SMTP configurado pelo usuário!
    Usa o relay gratuito FormSubmit.co (no 1º envio, o usuário recebe um e-mail
    de ativação de 1 clique; depois disso, todos os alertas chegam direto).
    """
    current_price = float(product.get("current_price", 0))
    initial_price = float(product.get("initial_price", current_price))
    target_price = float(product.get("target_price", current_price))
    reference_price = max(initial_price, float(product.get("highest_price", initial_price)))
    savings = max(0.0, reference_price - current_price)

    endpoint = f"https://formsubmit.co/ajax/{recipient}"
    payload = {
        "_subject": subject,
        "_template": "box",
        "_captcha": "false",
        "Produto": product.get("title", "Produto Monitorado"),
        "Loja": product.get("store_name", "Mercado Livre"),
        "Cotacao_Atual": format_brl(current_price),
        "Seu_Preco_Alvo": format_brl(target_price),
        "Preco_Maximo": format_brl(reference_price),
        "Economia": format_brl(savings),
        "Link_Direto_da_Oferta": product.get("url", "https://www.mercadolivre.com.br")
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": "http://127.0.0.1:5000/",
        "Origin": "http://127.0.0.1:5000",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
    }

    try:
        res = requests.post(endpoint, json=payload, headers=headers, timeout=12)
        data = res.json() if res.content else {}
        is_ok = str(data.get("success", "")).lower() == "true" or res.status_code == 200
        api_msg = str(data.get("message", ""))

        if is_ok:
            return {
                "sent": True,
                "simulated": False,
                "recipient": recipient,
                "subject": subject,
                "html_preview": html_content,
                "message": f"Alerta automático enviado para {recipient}!"
            }

        # Caso seja a primeira vez que esse e-mail é usado, o serviço pede 1 clique de confirmação no e-mail
        if "activate" in api_msg.lower() or "confirm" in api_msg.lower():
            return {
                "sent": True,
                "simulated": False,
                "recipient": recipient,
                "subject": subject,
                "html_preview": html_content,
                "message": (
                    f"Enviamos um e-mail de ativação única para {recipient}! "
                    "Abra sua caixa de entrada (ou Spam) e clique em 'Activate Form' para receber todos os próximos alertas automaticamente."
                )
            }
    except Exception:
        pass

    return None


def send_price_alert(product, settings=None):
    """
    Envia o alerta para o DONO do produto (`owner_email`).
    Credenciais SMTP próprias (opcional) vêm somente de variáveis de ambiente
    do servidor (SMTP_EMAIL, SMTP_PASSWORD, SMTP_HOST, SMTP_PORT) — nunca da interface.
    """
    smtp_email = os.environ.get("SMTP_EMAIL", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    recipient = (product.get("owner_email") or product.get("notify_email") or "").strip()
    if not EMAIL_RE.match(recipient):
        recipient = ""

    html_content = build_alert_email_html(product)
    subject = f"[PriceRadar] Alvo atingido: {product.get('title', 'Produto')[:48]} por {format_brl(product.get('current_price'))}"
    subject = subject.replace("\r", " ").replace("\n", " ")

    # 1. Se houver SMTP próprio configurado (opcional), usa conexão direta TLS
    if smtp_email and smtp_password and recipient:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"PriceRadar <{smtp_email}>"
        msg["To"] = recipient
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(smtp_email, smtp_password)
                server.sendmail(smtp_email, [recipient], msg.as_string())

            return {
                "sent": True,
                "simulated": False,
                "recipient": recipient,
                "subject": subject,
                "html_preview": html_content,
                "message": f"Notificação enviada via SMTP para {recipient}."
            }
        except Exception:
            pass

    # 2. Se o usuário informou apenas o e-mail dele (Modo 1-Passo Sem Senha!),
    # dispara automaticamente pelo relay HTTPS:
    if recipient and "@" in recipient:
        relay_result = send_via_zero_config_relay(recipient, product, subject, html_content)
        if relay_result:
            return relay_result

    # 3. Fallback local caso nenhum e-mail tenha sido digitado ainda
    return {
        "sent": False,
        "simulated": True,
        "recipient": recipient or "simulacao@priceradar.local",
        "subject": subject,
        "html_preview": html_content,
        "message": (
            "Informe seu e-mail no topo da página para receber os alertas automaticamente!"
        )
    }
