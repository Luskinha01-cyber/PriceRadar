"""
mailer.py - Módulo de Envio de Alertas por E-mail (SMTP)
========================================================
Gera e envia notificações em HTML com estética minimalista Dark Mode
quando a cotação do produto atinge ou fica abaixo do Preço Alvo.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


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
                        <img src="{product.get('image_url', '')}" alt="Produto" style="max-width:100%; max-height:100%; object-fit:contain;" />
                    </div>
                    <div>
                        <div style="font-family:monospace; font-size:11px; color:#71717a; text-transform:uppercase;">
                            {product.get('store_name', 'Mercado Livre')} · {now_str}
                        </div>
                        <h2 style="font-size:15px; font-weight:500; line-height:1.4; color:#f4f4f5; margin:4px 0 0;">
                            {product.get('title', 'Produto Monitorado')}
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
                    <a href="{product.get('url', '#')}" target="_blank" style="display:inline-block; background:#f4f4f5; color:#09090b; text-decoration:none; padding:11px 20px; border-radius:6px; font-weight:600; font-size:13px;">
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


def send_price_alert(product, settings):
    smtp_email = (settings.get("smtp_email") or "").strip()
    smtp_password = (settings.get("smtp_password") or "").strip()
    smtp_host = (settings.get("smtp_host") or "smtp.gmail.com").strip()
    smtp_port = int(settings.get("smtp_port") or 587)

    recipient = (
        (product.get("notify_email") or "").strip()
        or (settings.get("default_recipient") or "").strip()
        or smtp_email
    )

    html_content = build_alert_email_html(product)
    subject = f"[PriceRadar] Alvo atingido: {product.get('title', 'Produto')[:48]} por {format_brl(product.get('current_price'))}"

    if not smtp_email or not smtp_password:
        return {
            "sent": False,
            "simulated": True,
            "recipient": recipient or "simulacao@priceradar.local",
            "subject": subject,
            "html_preview": html_content,
            "message": "Renderizado em Simulação Local (configure o SMTP para envio externo)."
        }

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
    except Exception as exc:
        return {
            "sent": False,
            "simulated": True,
            "recipient": recipient,
            "subject": subject,
            "html_preview": html_content,
            "error": str(exc),
            "message": f"Falha SMTP ({exc}). Exibindo payload em Simulação Local."
        }
