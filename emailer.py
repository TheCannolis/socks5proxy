"""Email delivery for SOCKS5 Proxy Shop orders."""
import smtplib, logging, threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import config as cfg

log = logging.getLogger('emailer')


def _smtp_configured() -> bool:
    return bool(cfg.SMTP_HOST and cfg.SMTP_USER and cfg.SMTP_PASS)


def _send(to: str, subject: str, html: str, text: str = ''):
    if not _smtp_configured():
        log.warning(f'SMTP not configured, skipping email to {to}')
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = cfg.SMTP_FROM or cfg.SMTP_USER
        msg['To'] = to
        msg['Subject'] = subject
        if text:
            msg.attach(MIMEText(text, 'plain'))
        msg.attach(MIMEText(html, 'html'))

        if cfg.SMTP_TLS:
            server = smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=15)
        server.login(cfg.SMTP_USER, cfg.SMTP_PASS)
        server.sendmail(msg['From'], [to], msg.as_string())
        server.quit()
        log.info(f'Email sent to {to}: {subject}')
        return True
    except Exception as e:
        log.error(f'Email failed to {to}: {e}')
        return False


def send_async(to: str, subject: str, html: str, text: str = ''):
    """Fire-and-forget email send in background thread."""
    t = threading.Thread(target=_send, args=(to, subject, html, text), daemon=True)
    t.start()


def _base_template(content: str) -> str:
    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0e17;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0e17;padding:40px 20px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#111827;border:1px solid rgba(255,255,255,0.06);border-radius:14px;overflow:hidden;">

<!-- Header -->
<tr><td style="padding:28px 32px 20px;border-bottom:1px solid rgba(255,255,255,0.06);">
<table width="100%"><tr>
<td style="font-size:19px;font-weight:800;color:#f1f5f9;">
<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#3b82f6;box-shadow:0 0 12px #3b82f6;margin-right:10px;vertical-align:middle;"></span>
SOCKS5<span style="color:#64748b;font-weight:500;">.SHOP</span>
</td>
</tr></table>
</td></tr>

<!-- Content -->
<tr><td style="padding:32px;">
{content}
</td></tr>

<!-- Footer -->
<tr><td style="padding:20px 32px;border-top:1px solid rgba(255,255,255,0.06);text-align:center;">
<p style="margin:0;font-size:11px;color:#64748b;">
&copy; 2026 SOCKS5PROXY.SHOP &mdash; No logs. Full anonymity. Always encrypted.
</p>
<p style="margin:6px 0 0;font-size:11px;color:#64748b;">
<a href="https://socks5proxy.shop" style="color:#3b82f6;text-decoration:none;">socks5proxy.shop</a>
</p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>'''


def send_free_order(email: str, order_id: str, proxies: list[str], expires_at: str):
    proxy_rows = ''.join(
        f'<tr><td style="padding:8px 12px;color:#22c55e;font-family:monospace;font-size:14px;border-bottom:1px solid rgba(255,255,255,0.06);">{p}</td></tr>'
        for p in proxies
    )
    content = f'''
<h2 style="margin:0 0 6px;font-size:22px;color:#f1f5f9;font-weight:700;">Your Free Proxy is Ready</h2>
<p style="margin:0 0 24px;font-size:14px;color:#94a3b8;">Your SOCKS5 proxy has been activated. Here are your credentials.</p>

<table width="100%" style="margin-bottom:20px;">
<tr>
<td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Order ID</td>
<td style="padding:6px 0;font-size:14px;color:#3b82f6;font-weight:600;text-align:right;">{order_id}</td>
</tr>
<tr>
<td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Plan</td>
<td style="padding:6px 0;font-size:14px;color:#22c55e;font-weight:600;text-align:right;">Free (24h)</td>
</tr>
<tr>
<td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Expires</td>
<td style="padding:6px 0;font-size:14px;color:#f59e0b;font-weight:600;text-align:right;">{expires_at[:16].replace("T"," ")}</td>
</tr>
</table>

<div style="background:#1a1f2e;border:1px solid rgba(255,255,255,0.06);border-radius:10px;overflow:hidden;margin-bottom:16px;">
<div style="padding:10px 12px;font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.6px;border-bottom:1px solid rgba(255,255,255,0.06);">Your Proxy</div>
<table width="100%">{proxy_rows}</table>
</div>

<div style="background:rgba(59,130,246,0.07);border:1px solid rgba(59,130,246,0.18);border-radius:8px;padding:14px;margin-bottom:16px;">
<p style="margin:0;font-size:13px;color:#94a3b8;">
<strong style="color:#3b82f6;">How to use:</strong> Configure your browser or application to use <code style="background:#0a0e17;padding:2px 6px;border-radius:4px;font-size:12px;color:#22c55e;">SOCKS5</code> protocol with the proxy address above. No authentication required.
</p>
</div>

<p style="margin:0;font-size:12px;color:#64748b;text-align:center;">
Need more proxies? <a href="https://socks5proxy.shop" style="color:#3b82f6;text-decoration:none;font-weight:600;">Upgrade to Lite or Pro</a>
</p>'''

    text = f'''SOCKS5PROXY.SHOP - Free Proxy

Order: {order_id}
Plan: Free (24h)
Expires: {expires_at}

Proxy: {", ".join(proxies)}

Configure SOCKS5 with the proxy address above. No authentication required.
Upgrade: https://socks5proxy.shop'''

    send_async(email, f'Your Free Proxy is Ready - {order_id}', _base_template(content), text)


def send_paid_order(email: str, order_id: str, plan_name: str, proxies: list[str],
                    api_key: str, expires_at: str, price_usd: float, tx_hash: str = ''):
    proxy_rows = ''.join(
        f'<tr><td style="padding:6px 12px;color:#22c55e;font-family:monospace;font-size:13px;border-bottom:1px solid rgba(255,255,255,0.06);">{p}</td></tr>'
        for p in proxies[:50]
    )
    more_note = f'<tr><td style="padding:8px 12px;color:#64748b;font-size:12px;">...and {len(proxies)-50} more. Use your API key to retrieve the full list.</td></tr>' if len(proxies) > 50 else ''

    tx_row = ''
    if tx_hash:
        tx_row = f'''<tr>
<td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">TX Hash</td>
<td style="padding:6px 0;font-size:12px;color:#94a3b8;text-align:right;font-family:monospace;word-break:break-all;">{tx_hash[:20]}...</td>
</tr>'''

    content = f'''
<h2 style="margin:0 0 6px;font-size:22px;color:#f1f5f9;font-weight:700;">Payment Confirmed</h2>
<p style="margin:0 0 24px;font-size:14px;color:#94a3b8;">Your {plan_name} plan is now active. {len(proxies)} proxies assigned.</p>

<table width="100%" style="margin-bottom:20px;">
<tr>
<td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Order ID</td>
<td style="padding:6px 0;font-size:14px;color:#3b82f6;font-weight:600;text-align:right;">{order_id}</td>
</tr>
<tr>
<td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Plan</td>
<td style="padding:6px 0;font-size:14px;color:#8b5cf6;font-weight:600;text-align:right;">{plan_name}</td>
</tr>
<tr>
<td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Amount Paid</td>
<td style="padding:6px 0;font-size:14px;color:#22c55e;font-weight:600;text-align:right;">${price_usd} USD</td>
</tr>
<tr>
<td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Proxies</td>
<td style="padding:6px 0;font-size:14px;color:#f1f5f9;font-weight:600;text-align:right;">{len(proxies)}</td>
</tr>
<tr>
<td style="padding:6px 0;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Expires</td>
<td style="padding:6px 0;font-size:14px;color:#f59e0b;font-weight:600;text-align:right;">{expires_at[:16].replace("T"," ")}</td>
</tr>
{tx_row}
</table>

<div style="background:#1a1f2e;border:1px solid rgba(255,255,255,0.06);border-radius:10px;overflow:hidden;margin-bottom:16px;">
<div style="padding:10px 12px;font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.6px;border-bottom:1px solid rgba(255,255,255,0.06);">Your Proxies</div>
<table width="100%">{proxy_rows}{more_note}</table>
</div>

<div style="background:#1a1f2e;border:1px solid rgba(255,255,255,0.06);border-radius:10px;padding:14px;margin-bottom:20px;">
<div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;">API Key</div>
<div style="font-family:monospace;font-size:13px;color:#3b82f6;word-break:break-all;">{api_key}</div>
</div>

<div style="background:rgba(59,130,246,0.07);border:1px solid rgba(59,130,246,0.18);border-radius:8px;padding:14px;">
<p style="margin:0;font-size:13px;color:#94a3b8;">
<strong style="color:#3b82f6;">Retrieve full list:</strong>
<code style="background:#0a0e17;padding:2px 6px;border-radius:4px;font-size:11px;color:#22c55e;">GET /api/customer/order/{order_id}</code><br>
<span style="font-size:12px;">All proxies use <code style="background:#0a0e17;padding:2px 6px;border-radius:4px;font-size:11px;color:#22c55e;">SOCKS5</code> protocol. No authentication required.</span>
</p>
</div>'''

    proxy_list_text = "\n".join(proxies[:50])
    if len(proxies) > 50:
        proxy_list_text += f"\n...and {len(proxies)-50} more (use API key to get full list)"

    text = f'''SOCKS5PROXY.SHOP - Payment Confirmed

Order: {order_id}
Plan: {plan_name}
Paid: ${price_usd} USD
Proxies: {len(proxies)}
Expires: {expires_at}
{f"TX: {tx_hash}" if tx_hash else ""}

Proxies:
{proxy_list_text}

API Key: {api_key}

Retrieve full list: GET /api/customer/order/{order_id}
All proxies use SOCKS5. No auth required.'''

    send_async(email, f'Payment Confirmed - {plan_name} Plan - {order_id}', _base_template(content), text)
