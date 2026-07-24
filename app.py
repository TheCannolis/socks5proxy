"""Single-process entry point for RunxBuild / single-port deployments.
   Merges public shop (/) and admin panel (/admin/) into one Flask instance.
   gunicorn app:app --bind 0.0.0.0:$PORT
"""
import os, sys, json, logging, threading
from functools import wraps
from flask import Flask, render_template_string, request, jsonify, send_file, redirect, session

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
from core import pool
from shop_backend import orders, PLANS
from wallet import (issue_nonce, build_siwe_message, verify_siwe, create_session,
                     get_session, revoke_session, create_payment, register_payment,
                     get_payment, check_payment, list_chains_for_client)

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(name)s %(levelname)s %(message)s')
log = logging.getLogger('app')

app = Flask(__name__)
app.secret_key = cfg.WEB_SECRET_KEY

# ============================================================
# Admin authentication
# ============================================================
def login_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not session.get('logged_in'):
            if request.path.startswith('/admin/api/'):
                return jsonify({'error': 'unauthorized'}), 401
            return redirect('/admin/login')
        return f(*a, **kw)
    return d

# ============================================================
# Admin dashboard routes (prefixed with /admin)
# ============================================================
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = ''
    if request.method == 'POST':
        if request.form.get('username') == cfg.WEB_USERNAME and request.form.get('password') == cfg.WEB_PASSWORD:
            session['logged_in'] = True
            return redirect('/admin/')
        error = 'Bad credentials'
    return render_template_string(ADMIN_LOGIN_HTML, error=error)

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect('/admin/login')

@app.route('/admin/')
@login_required
def admin_index():
    return render_template_string(ADMIN_MAIN_HTML)

@app.route('/admin/overview')
@login_required
def admin_overview():
    return render_template_string(ADMIN_MAIN_HTML)

@app.route('/admin/api/stats')
@login_required
def admin_api_stats():
    s = pool.stats()
    s['orders'] = orders.stats()
    return jsonify(s)

@app.route('/admin/api/proxies')
@login_required
def admin_api_proxies():
    c = request.args.get('country', '').strip().upper()
    limit = int(request.args.get('limit', 200))
    from dataclasses import asdict
    return jsonify([asdict(p) for p in pool.get_alive([c] if c else None, limit)])

@app.route('/admin/api/orders')
@login_required
def admin_api_orders():
    return jsonify([{
        'order_id': o.order_id, 'plan': o.plan_name, 'email': o.email,
        'status': o.status, 'price': o.price_usd, 'created': o.created_at,
        'api_key': (o.api_key[:16] + '...') if o.api_key else ''
    } for o in orders.get_all_orders()])

@app.route('/admin/api/download/<fmt>')
@login_required
def admin_api_download(fmt):
    p = cfg.OUTPUT_DIR / f'socks5_ALL.{fmt}'
    if not p.exists():
        return jsonify({'error': 'not found'}), 404
    return send_file(p, as_attachment=True)

# ============================================================
# Public shop routes (root)
# ============================================================
@app.route('/')
def shop_home():
    html = SHOP_PAGE_HTML.replace('__PID__', cfg.WALLETCONNECT_PROJECT_ID or 'demo-pid')
    html = html.replace('__CHAINS__', json.dumps(list_chains_for_client()))
    html = html.replace('__WALLETS__', json.dumps(cfg.RECEIVING_WALLETS))
    return render_template_string(html)

@app.route('/api/shop/stats')
def shop_stats():
    s = pool.stats()
    return jsonify({'alive': s['alive'], 'countries': len(s['countries']), 'avg_latency': s['avg_latency']})

@app.route('/api/shop/plans')
def shop_plans():
    return jsonify(PLANS)

@app.route('/api/shop/countries')
def shop_countries():
    return jsonify(pool.country_stats())

@app.route('/api/wallet/nonce')
def wallet_nonce():
    return jsonify({'nonce': issue_nonce()})

@app.route('/api/wallet/siwe', methods=['POST'])
def wallet_siwe():
    d = request.get_json(silent=True) or {}
    msg = build_siwe_message(d.get('address', ''), d.get('chain', ''), d.get('nonce', ''))
    return jsonify({'message': msg})

@app.route('/api/wallet/auth', methods=['POST'])
def wallet_auth():
    d = request.get_json(silent=True) or {}
    info = verify_siwe(d.get('message', ''), d.get('signature', ''))
    if not info:
        return jsonify({'error': 'invalid signature'}), 401
    token = create_session(info['address'], info['chain'])
    return jsonify({'token': token, 'address': info['address'], 'chain': info['chain']})

@app.route('/api/wallet/logout', methods=['POST'])
def wallet_logout():
    auth = request.headers.get('Authorization', '').replace('Bearer ', '')
    revoke_session(auth)
    return jsonify({'ok': True})

@app.route('/api/wallet/quote')
def wallet_quote():
    plan = request.args.get('plan', '')
    chain = request.args.get('chain', '')
    token = request.args.get('token', '')
    pc = PLANS.get(plan)
    if not pc:
        return jsonify({'error': 'invalid plan'}), 400
    from dataclasses import asdict
    p = create_payment('QUOTE', pc['price_usd'], chain, token)
    if not p:
        return jsonify({'error': 'unsupported chain/token'}), 400
    return jsonify({'payment': asdict(p)})

@app.route('/api/shop/order', methods=['POST'])
def create_order():
    d = request.get_json(silent=True) or {}
    plan_id = d.get('plan', '')
    email = d.get('email', '').strip()
    countries = [c.strip().upper() for c in d.get('countries', '').split(',') if c.strip()]
    chain = d.get('chain', '')
    token = d.get('token', '')
    is_utxo = d.get('utxo', False) or chain in ('btc', 'ltc')
    if plan_id not in PLANS or '@' not in email:
        return jsonify({'error': 'invalid input'}), 400
    order = orders.create_order(plan_id, email, countries, chain or 'manual')
    if not order:
        return jsonify({'error': 'order failed'}), 500
    out = {'order': {'order_id': order.order_id, 'email': order.email}}
    if chain and token:
        from dataclasses import asdict
        payment = create_payment(order.order_id, order.price_usd, chain, token)
        if payment:
            register_payment(payment)
            out['payment'] = asdict(payment)
    return jsonify(out)

@app.route('/api/wallet/check')
def wallet_check():
    pid = request.args.get('payment_id', '')
    oid = request.args.get('order_id', '')
    payment = get_payment(pid)
    if not payment:
        return jsonify({'paid': False, 'error': 'unknown payment'})
    if not payment.paid:
        check_payment(payment)
    if payment.paid and oid:
        o = orders.confirm_payment(oid, payment.tx_hash)
        if o:
            return jsonify({'paid': True, 'proxies': o.proxies, 'api_key': o.api_key, 'tx_hash': payment.tx_hash})
    import time
    return jsonify({'paid': False, 'expires_at': payment.expires_at,
                    'time_left': max(0, payment.expires_at - time.time())})


@app.route('/api/customer/order/<order_id>')
def customer_order(order_id):
    o = orders.get_order(order_id)
    if not o:
        return jsonify({'error': 'not found'}), 404
    return jsonify({'order_id': o.order_id, 'status': o.status, 'plan': o.plan_name,
                    'expires_at': o.expires_at, 'api_key': o.api_key, 'proxies': o.proxies})

# ============================================================
# HTML templates (bundled so there's no file I/O at runtime)
# ============================================================

ADMIN_LOGIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Login — socks5proxy.shop</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--accent:#58a6ff;--green:#238636;--red:#da3633;--font:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:var(--font);display:flex;align-items:center;justify-content:center;min-height:100vh}
.login-box{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:32px 28px;width:340px}
.login-box h2{margin:0 0 20px;text-align:center;font-size:18px}
label{display:block;font-size:13px;color:#8b949e;margin:12px 0 4px}
input{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:10px;border-radius:6px;font-family:var(--font)}
.btn{width:100%;border:none;border-radius:6px;padding:12px;cursor:pointer;font-family:var(--font);font-weight:700;color:#fff;background:var(--green);margin-top:16px;font-size:14px}
.error{background:rgba(218,54,51,.15);border:1px solid var(--red);color:var(--red);padding:10px;border-radius:6px;margin-bottom:16px;font-size:13px;text-align:center}
</style></head><body>
<div class="login-box">
<h2>🧦 Admin</h2>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="POST">
<label>Username</label><input name="username" autocomplete="off">
<label>Password</label><input name="password" type="password">
<button class="btn" type="submit">Sign In</button>
</form>
</div></body></html>"""

ADMIN_MAIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOCKS5 Manager — socks5proxy.shop</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#58a6ff;--green:#238636;--red:#da3633;--yellow:#d29922;--font:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:var(--font);font-size:14px}
a{color:var(--accent)}.wrap{display:flex;min-height:100vh}
.sidebar{width:220px;background:var(--card);border-right:1px solid var(--border);padding:20px 0;flex-shrink:0}
.sidebar h2{padding:0 20px;margin:0 0 20px;font-size:16px}
.nav-item{padding:12px 20px;cursor:pointer;color:var(--muted);display:block;text-decoration:none}
.nav-item:hover,.nav-item.active{color:var(--text);background:rgba(88,166,255,.1)}
.main{flex:1;padding:24px;overflow:auto}.page{display:none}.page.active{display:block}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:16px}
.btn{border:none;border-radius:6px;padding:8px 16px;cursor:pointer;font-family:var(--font);font-size:13px;color:#fff;background:var(--accent)}
.btn-green{background:var(--green)}.btn-outline{background:transparent;border:1px solid var(--border);color:var(--text)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:20px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px}
.stat .sv{font-size:28px;font-weight:700;color:var(--accent)}.stat .ss{color:var(--muted);font-size:12px}
table{width:100%;border-collapse:collapse;margin-top:12px}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--border);font-size:13px}
th{color:var(--muted);font-weight:600}
input{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:6px;font-family:var(--font)}
</style></head><body>
<div class="wrap">
<div class="sidebar">
<h2>🧦 socks5proxy.shop</h2>
<a class="nav-item active" href="#" onclick="showPage('overview',this);return false">Overview</a>
<a class="nav-item" href="#" onclick="showPage('proxies',this);return false">Proxies</a>
<a class="nav-item" href="#" onclick="showPage('orders',this);return false">Orders</a>
<a class="nav-item" href="#" onclick="showPage('export',this);return false">Export</a>
<a class="nav-item" href="/" target="_blank">Shop →</a>
<div style="position:absolute;bottom:20px"><a href="/admin/logout" class="nav-item">Sign Out</a></div>
</div>
<div class="main">
<div class="page active" id="page-overview">
  <h2>Overview</h2>
  <div class="stats" id="ovStats"></div>
</div>
<div class="page" id="page-proxies">
  <h2>Proxy List — Search / Filter</h2>
  <div class="card" style="display:flex;gap:12px">
    <input id="pSearch" placeholder="Search IP / country" style="flex:1" oninput="loadProxies()">
    <input id="pCountry" placeholder="Country (US,DE)" style="width:140px" oninput="loadProxies()">
  </div>
  <div class="card"><table><thead><tr><th>Proxy</th><th>Country</th><th>Latency</th><th>ISP</th></tr></thead><tbody id="pBody"></tbody></table></div>
</div>
<div class="page" id="page-orders">
  <h2>Orders</h2>
  <div class="card"><table><thead><tr><th>Order ID</th><th>Plan</th><th>Email</th><th>Status</th><th>Price</th><th>Date</th></tr></thead><tbody id="oBody"></tbody></table></div>
</div>
<div class="page" id="page-export">
  <h2>Export</h2>
  <div class="card">
    <p style="color:var(--muted)">Download alive proxy list.</p>
    <div style="display:flex;gap:12px;margin-top:16px">
      <button class="btn btn-green" onclick="window.location='/admin/api/download/txt'">TXT</button>
      <button class="btn btn-green" onclick="window.location='/admin/api/download/json'">JSON</button>
    </div>
  </div>
</div>
</div></div>
<script>
function showPage(id,el){document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));document.getElementById('page-'+id).classList.add('active');document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));if(el)el.classList.add('active');if(id==='proxies')loadProxies();if(id==='orders')loadOrders();}
function flag(c){if(!c||c.length!==2)return'';return String.fromCodePoint(...[...c.toUpperCase()].map(x=>0x1F1E6+x.charCodeAt(0)-65));}
async function fetchStats(){const s=await(await fetch('/admin/api/stats')).json();const el=document.getElementById('ovStats');el.innerHTML=`<div class="stat"><div class="sv">${(s.alive||0).toLocaleString()}</div><div class="ss">alive proxies</div></div><div class="stat"><div class="sv">${(s.countries||[]).length}</div><div class="ss">countries</div></div><div class="stat"><div class="sv">${s.avg_latency||0}ms</div><div class="ss">avg latency</div></div><div class="stat"><div class="sv">$${(s.orders?.revenue_usd||0).toFixed(2)}</div><div class="ss">revenue</div></div><div class="stat"><div class="sv">${s.orders?.total_orders||0}</div><div class="ss">total orders</div></div><div class="stat"><div class="sv">${s.orders?.active||0}</div><div class="ss">active subs</div></div>`;}
async function loadProxies(){const q=document.getElementById('pSearch').value.toLowerCase();const c=document.getElementById('pCountry').value.toUpperCase();const ps=await(await fetch('/admin/api/proxies?limit=500&country='+encodeURIComponent(c))).json();const tb=document.getElementById('pBody');tb.innerHTML='';ps.filter(p=>!q||p.host.includes(q)||(p.country+' '+p.city+' '+p.isp).toLowerCase().includes(q)).slice(0,200).forEach(p=>{tb.innerHTML+=`<tr><td>${p.host}:${p.port}</td><td>${flag(p.country)} ${p.country}</td><td>${p.latency_ms}ms</td><td>${p.isp||'-'}</td></tr>`;});}
async function loadOrders(){const os=await(await fetch('/admin/api/orders')).json();const tb=document.getElementById('oBody');tb.innerHTML='';os.forEach(o=>{tb.innerHTML+=`<tr><td>${o.order_id}</td><td>${o.plan}</td><td>${o.email}</td><td style="color:${o.status==='active'?'var(--green)':o.status==='pending'?'var(--yellow)':'var(--muted)'}">${o.status}</td><td>$${o.price}</td><td>${(o.created||'').split('T')[0]}</td></tr>`;});}
fetchStats();setInterval(fetchStats,15000);
</script></body></html>"""

SHOP_PAGE_HTML = """
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOCKS5 Proxy Shop — socks5proxy.shop</title>
<script src="https://unpkg.com/@reown/appkit@1.6.8/dist/index.js"></script>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#58a6ff;--green:#238636;--orange:#d29922;--purple:#bc8cff;--yellow:#f0c040;--font:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:var(--font)}
.container{max-width:1080px;margin:0 auto;padding:24px}
.wallet-bar{display:flex;justify-content:space-between;align-items:center;padding:12px 20px;background:var(--card);border:1px solid var(--border);border-radius:10px;margin-bottom:24px}
.wallet-bar .addr{font-size:13px;color:var(--muted);font-family:monospace}
.hero{text-align:center;padding:32px 20px}.hero h1{font-size:36px;margin:0}
.hero p{color:var(--muted)}.stats{display:flex;justify-content:center;gap:32px;margin:24px 0;flex-wrap:wrap}
.stat{text-align:center}.stat .v{font-size:32px;font-weight:700;color:var(--accent)}.stat .l{color:var(--muted);font-size:12px}
.plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-top:24px}
.plan{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;text-align:center}
.plan.featured{border-color:var(--accent);box-shadow:0 0 20px rgba(88,166,255,.15)}
.plan h3{margin-top:0}.plan .price{font-size:28px;font-weight:700}
.plan .price span{font-size:14px;color:var(--muted);font-weight:400}
.plan ul{color:var(--muted);padding:0;list-style:none;font-size:13px;margin:12px 0}
.plan ul li{padding:3px 0}
.btn{width:100%;border:none;border-radius:6px;padding:12px;cursor:pointer;font-family:var(--font);font-weight:700;color:#fff;background:var(--green);margin-top:12px}
.btn-outline{background:transparent;border:1px solid var(--border);color:var(--text);font-weight:400;padding:8px 14px;width:auto;margin:0}
.btn-orange{background:var(--orange);color:#000}
.btn-purple{background:var(--purple)}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.75);display:none;align-items:center;justify-content:center;padding:20px;z-index:100;overflow-y:auto}
.modal.active{display:flex}.modal-box{background:var(--card);border:1px solid var(--border);border-radius:12px;max-width:520px;width:100%;padding:24px;margin:auto}
.close{float:right;cursor:pointer;color:var(--muted);font-size:20px}
input,select{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:10px;border-radius:6px;margin-top:6px;font-family:var(--font)}
.step{display:none}.step.active{display:block}
.pay-info{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:16px;margin:16px 0;font-size:13px;word-break:break-all}
.pay-info b{color:var(--accent)}
.chains{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-top:12px}
.chain-card{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;cursor:pointer;text-align:center;font-size:13px}
.chain-card:hover,.chain-card.selected{border-color:var(--accent);background:rgba(88,166,255,.1)}
.chain-card.utxo{border-color:var(--orange)}
.chain-card.utxo:hover,.chain-card.utxo.selected{border-color:var(--orange);background:rgba(210,153,34,.1)}
.tokens{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}
.token-chip{background:var(--bg);border:1px solid var(--border);border-radius:16px;padding:6px 14px;cursor:pointer;font-size:12px}
.token-chip.selected{background:var(--accent);color:#fff;border-color:var(--accent)}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--muted);border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.toast{position:fixed;bottom:20px;right:20px;background:var(--green);color:#fff;padding:10px 16px;border-radius:6px;display:none;z-index:200}
.toast.err{background:#da3633}
.pay-addr{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:12px;font-size:12px;word-break:break-all;margin:8px 0;color:var(--accent);font-family:monospace}
.pay-addr.btc{color:var(--orange)}
.pay-addr.ltc{color:var(--purple)}
.utxo-badges{display:flex;gap:8px;margin-top:12px;justify-content:center}
.utxo-badge{background:var(--bg);border:1px solid var(--orange);border-radius:8px;padding:10px 18px;cursor:pointer;text-align:center;font-size:14px;font-weight:700}
.utxo-badge:hover{border-color:var(--orange);background:rgba(210,153,34,.1)}
.utxo-badge.ltc{color:var(--purple);border-color:var(--purple)}
.utxo-badge.ltc:hover{background:rgba(188,140,255,.1)}
.qr-hint{display:block;text-align:center;margin:8px 0;color:var(--muted);font-size:11px}
</style></head><body>
<div class="container">
<div class="wallet-bar">
  <div style="font-weight:700">🧦 socks5proxy.shop</div>
  <div id="walletArea"><button class="btn btn-outline" id="connectBtn" onclick="connectWallet()">Connect Wallet</button></div>
</div>
<div class="hero"><h1>Premium SOCKS5 Proxies</h1><p>Verified, fresh SOCKS5 proxies — pay with crypto from your wallet.</p>
<div class="stats"><div class="stat"><div class="v" id="sAlive">-</div><div class="l">alive proxies</div></div><div class="stat"><div class="v" id="sCountries">-</div><div class="l">countries</div></div><div class="stat"><div class="v" id="sLatency">-</div><div class="l">avg latency</div></div></div>
</div>
<div class="plans" id="planCards"></div>
<div style="text-align:center;margin-top:24px;color:var(--muted);font-size:12px">© 2026 socks5proxy.shop — Payments via WalletConnect, BTC & LTC</div>
</div>
<div class="modal" id="orderModal"><div class="modal-box">
  <span class="close" onclick="closeModal()">✕</span>
  <div class="step active" id="step1">
    <h3>Order: <span id="mPlanName"></span></h3>
    <p style="color:var(--muted)">$<span id="mPrice">0</span></p>
    <p>Email:<br><input id="mEmail" type="email" placeholder="you@example.com"></p>
    <p>Countries (optional):<br><input id="mCountries" placeholder="US,DE,NL"></p>
    <p style="color:var(--muted);font-size:12px">Choose payment method:</p>
    <div class="utxo-badges">
      <div class="utxo-badge" onclick="startBtcOrder()">₿ BTC</div>
      <div class="utxo-badge ltc" onclick="startLtcOrder()">Ł LTC</div>
    </div>
    <p style="text-align:center;color:var(--muted);font-size:11px;margin:12px 0">or pay with WalletConnect</p>
    <button class="btn" onclick="goStep(2)">Pay with WalletConnect →</button>
  </div>
  <div class="step" id="step2">
    <h3>Select Chain & Token</h3>
    <div class="chains" id="chainList"></div>
    <p style="margin-top:16px;color:var(--muted)">Token:</p>
    <div class="tokens" id="tokenList"></div>
    <div class="pay-info" id="payQuote" style="display:none"></div>
    <button class="btn" onclick="goStep(3)">Continue →</button>
  </div>
  <div class="step" id="step3">
    <h3>Send Payment</h3>
    <div class="pay-info" id="payInfo"></div>
    <p id="payStatus" style="color:var(--muted)"><span class="spinner"></span>Waiting for payment...</p>
    <button class="btn btn-outline" style="margin-top:8px" onclick="checkPayManually()">I already paid — check now</button>
  </div>
  <div class="step" id="step4">
    <h3>✅ Order Confirmed</h3>
    <p>Order ID: <b id="mOrderId"></b></p>
    <p>Your proxies are ready.</p>
    <div class="pay-info" id="mProxies"></div>
    <button class="btn" onclick="closeModal()">Done</button>
  </div>
</div></div>
<div id="toast" class="toast"></div>
<script>
let walletConnected=false,walletAddress='',walletChain='',sessionToken='';
let selectedPlan=null,selectedChain=null,selectedToken=null,currentOrder=null,currentPayment=null;
let isUtxoOrder=false;
const PROJECT_ID='__PID__';
const CHAINS=__CHAINS__;
const WALLETS=__WALLETS__;

function toast(m,err){const t=document.getElementById('toast');t.textContent=m;t.className='toast'+(err?' err':'');t.style.display='block';setTimeout(()=>t.style.display='none',3500);}
function shortAddr(a){return a.slice(0,6)+'...'+a.slice(-4);}
async function loadStats(){const s=await(await fetch('/api/shop/stats')).json();document.getElementById('sAlive').textContent=s.alive.toLocaleString();document.getElementById('sCountries').textContent=s.countries;document.getElementById('sLatency').textContent=s.avg_latency+'ms';}
async function loadPlans(){const plans=await(await fetch('/api/shop/plans')).json();window._plansCache=plans;let el=document.getElementById('planCards');el.innerHTML='';for(const[id,p]of Object.entries(plans)){el.innerHTML+=`<div class="plan ${p.proxy_count===200?'featured':''}"><h3 style="color:${p.color}">${p.name}</h3><div class="price">$${p.price_usd}<span>/mo</span></div><p style="color:var(--muted);font-size:13px">${p.proxy_count>=999?'Unlimited':p.proxy_count} proxies · ${p.duration_days} days</p><ul>${p.features.map(f=>'<li>✓ '+f+'</li>').join('')}</ul><button class="btn" onclick="openOrder('${id}')">Get ${p.name}</button></div>`;}}
async function connectWallet(){if(!PROJECT_ID||PROJECT_ID==='demo-pid'){toast('WalletConnect not configured',true);return;}if(!window.AppKit){toast('SDK loading... reload in 3s',true);return;}try{const evmIds=CHAINS.filter(c=>c.type!=='utxo'&&typeof c.chain_id==='number').map(c=>c.chain_id);const a=await window.AppKit.createAppKit({projectId:PROJECT_ID,networks:evmIds.length?evmIds:[1],metadata:{name:'SOCKS5 Proxy Shop',description:'Buy SOCKS5 proxies',url:window.location.origin,icons:[]}});await a.open();const addr=a.getAddress?.()||'';const cid=a.getChainId?.()||0;if(addr){walletAddress=addr;walletChain=CHAINS.find(c=>c.chain_id===cid)?.id||'';await signIn();}}catch(e){toast('Connection failed: '+e.message,true);}}
async function signIn(){try{const nr=await fetch('/api/wallet/nonce');const{nonce}=await nr.json();const mr=await fetch('/api/wallet/siwe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({address:walletAddress,chain:walletChain,nonce})});const{message}=await mr.json();const adapter=window.appKit||window.appKitModal;const sig=await adapter.signMessage(message);const ar=await fetch('/api/wallet/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,signature:sig})});const data=await ar.json();if(data.error){toast(data.error,true);return;}sessionToken=data.token;walletConnected=true;document.getElementById('walletArea').innerHTML='<span class="addr">🟢 '+shortAddr(walletAddress)+' ('+walletChain+')</span> <button class="btn btn-outline" style="margin-left:8px" onclick="disconnect()">Disconnect</button>';toast('Wallet connected');}catch(e){toast('Sign-in failed: '+e.message,true);}}
function disconnect(){walletConnected=false;walletAddress='';walletChain='';sessionToken='';document.getElementById('walletArea').innerHTML='<button class="btn btn-outline" id="connectBtn" onclick="connectWallet()">Connect Wallet</button>';}
function openOrder(id){selectedPlan=id;isUtxoOrder=false;selectedChain=null;selectedToken=null;currentPayment=null;currentOrder=null;const p=window._plansCache?.[id];document.getElementById('mPlanName').textContent=p?.name||id;document.getElementById('mPrice').textContent=p?.price_usd||'?';goStep(1);document.getElementById('orderModal').classList.add('active');}
function closeModal(){document.getElementById('orderModal').classList.remove('active');}
function goStep(n){document.querySelectorAll('.step').forEach(s=>s.classList.remove('active'));document.getElementById('step'+n).classList.add('active');if(n===2)renderChains();if(n===3)initPayment();if(n===4)finalizeOrder();}

async function startBtcOrder(){startUtxoOrder('bitcoin','BTC','₿ Bitcoin');}
async function startLtcOrder(){startUtxoOrder('litecoin','LTC','Ł Litecoin');}
async function startUtxoOrder(chain,symbol,label){
  const email=document.getElementById('mEmail').value.trim();
  const countries=document.getElementById('mCountries').value;
  if(!email.includes('@')){toast('Valid email required',true);return;}
  isUtxoOrder=true;selectedChain=chain;selectedToken=symbol;
  const r=await fetch('/api/shop/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan:selectedPlan,email,countries,chain:chain,token:symbol})});
  const d=await r.json();
  if(d.error){toast(d.error,true);return;}
  currentOrder=d.order;currentPayment=d.payment;
  document.getElementById('payInfo').innerHTML=`<h4 style="margin-top:0">${label} Payment</h4><b>Order:</b> ${d.order.order_id}<br><b>Amount:</b> ${d.payment.amount_human} ${symbol}<br><b>≈ $${d.payment.amount_usd} USD</b><br><b>Send to:</b><div class="pay-addr ${chain==='bitcoin'?'btc':'ltc'}">${d.payment.receiver}</div><span class="qr-hint">Send EXACT amount shown above. Confirmation may take 5-15 min.</span>`;
  goStep(3);pollPayment();
}

function renderChains(){
  const cl=document.getElementById('chainList');
  cl.innerHTML='';
  const wcChains=CHAINS.filter(c=>c.type!=='utxo');
  wcChains.forEach(c=>{cl.innerHTML+=`<div class="chain-card" id="ch-${c.id}" onclick="selectChain('${c.id}')">${c.name}</div>`;});
  if(wcChains.length)selectChain(wcChains[0].id);
}
function selectChain(id){
  selectedChain=id;isUtxoOrder=false;
  document.querySelectorAll('.chain-card').forEach(el=>el.classList.remove('selected'));
  document.getElementById('ch-'+id).classList.add('selected');
  const c=CHAINS.find(x=>x.id===id);
  const tl=document.getElementById('tokenList');tl.innerHTML='';
  c.tokens.forEach(t=>{tl.innerHTML+=`<div class="token-chip" id="tk-${t.symbol}" onclick="selectToken('${t.symbol}')">${t.symbol}</div>`;});
  if(c.tokens.length)selectToken(c.tokens[0].symbol);
}
async function selectToken(sym){
  selectedToken=sym;
  document.querySelectorAll('.token-chip').forEach(el=>el.classList.remove('selected'));
  document.getElementById('tk-'+sym).classList.add('selected');
  const q=document.getElementById('payQuote');q.style.display='block';
  q.innerHTML='<span class="spinner"></span>Getting quote...';
  if(!selectedChain)return;
  const r=await(await fetch('/api/wallet/quote?plan='+selectedPlan+'&chain='+selectedChain+'&token='+sym)).json();
  if(r.error){q.innerHTML='<span style="color:#f85149">'+r.error+'</span>';currentPayment=null;return;}
  currentPayment=r.payment;
  q.innerHTML=`Pay <b>${r.payment.amount_human} ${sym}</b> on ${CHAINS.find(c=>c.id===selectedChain).name}<br>≈ $${r.payment.amount_usd} USD<br><span style="color:var(--muted)">Quote valid 30 min</span>`;
}
async function initPayment(){
  if(isUtxoOrder){goStep(3);return;}
  const email=document.getElementById('mEmail').value.trim();
  const countries=document.getElementById('mCountries').value;
  if(!email.includes('@')){toast('Valid email required',true);goStep(1);return;}
  const r=await fetch('/api/shop/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan:selectedPlan,email,countries,chain:selectedChain,token:selectedToken,wallet:walletAddress})});
  const d=await r.json();
  if(d.error){toast(d.error,true);return;}
  currentOrder=d.order;currentPayment=d.payment;
  const c=CHAINS.find(x=>x.id===selectedChain);
  document.getElementById('payInfo').innerHTML=`<b>Order:</b> ${d.order.order_id}<br><b>Amount:</b> ${d.payment.amount_human} ${selectedToken}<br><b>Send to:</b><div class="pay-addr">${d.payment.receiver}</div><a style="color:var(--accent);font-size:12px" target="_blank" href="${c.explorer}/address/${d.payment.receiver}">View on ${c.name} explorer →</a>`;
  pollPayment();
}
function checkPayManually(){pollPayment(true);}
async function pollPayment(force){
  if(!currentPayment||!currentOrder)return;
  const ps=document.getElementById('payStatus');
  ps.innerHTML='<span class="spinner"></span>Checking blockchain...';
  const r=await(await fetch('/api/wallet/check?payment_id='+currentPayment.payment_id+'&order_id='+currentOrder.order_id)).json();
  if(r.paid){currentOrder.proxies=r.proxies;currentOrder.api_key=r.api_key;goStep(4);}
  else{ps.innerHTML='<span style="color:var(--yellow)">⏳ Not detected yet. Waiting for confirmation...</span>';setTimeout(()=>pollPayment(false),8000);}
}
function finalizeOrder(){
  document.getElementById('mOrderId').textContent=currentOrder.order_id;
  document.getElementById('mProxies').innerHTML='<b>Your proxies:</b><br><pre style="white-space:pre-wrap;font-size:11px;margin:8px 0">'+currentOrder.proxies.join('\\n')+'</pre><b>API key:</b><br><code>'+currentOrder.api_key+'</code>';
}
loadStats();loadPlans();
</script></body></html>
"""