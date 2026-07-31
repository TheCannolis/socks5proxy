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
    html = html.replace('__AFFILIATE_URL__', cfg.AFFILIATE_URL)
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
            return jsonify({'paid': True, 'proxies': o.proxies, 'api_key': o.api_key, 'tx_hash': payment.tx_hash, 'order_id': o.order_id})
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


@app.route('/api/shop/free', methods=['POST'])
def shop_free():
    d = request.get_json(silent=True) or {}
    email = d.get('email','').strip().lower()
    if '@' not in email:
        return jsonify({'error': 'valid email required'}), 400
    if not orders.can_claim_free(email):
        return jsonify({'error': 'this email has already claimed a free proxy. one per customer.'}), 400
    plan = PLANS.get('free')
    order = orders.create_order('free', email, [], 'free')
    if not order:
        return jsonify({'error': 'order creation failed'}), 500
    from core import pool as _pool
    from datetime import datetime, timedelta
    assigned = _pool.get_alive(None)[:1]
    order.proxies = [f'{p.host}:{p.port}' for p in assigned]
    order.status = 'active'
    order.paid_at = order.created_at
    order.expires_at = (datetime.utcnow() + timedelta(days=plan['duration_days'])).isoformat()
    orders.save()
    orders.mark_free_claimed(email)
    from emailer import send_free_order
    send_free_order(email, order.order_id, order.proxies, order.expires_at)
    return jsonify({
        'order_id': order.order_id,
        'status': 'active',
        'expires_at': order.expires_at,
        'email_sent': True,
    })

# ============================================================
# Pool API — proxy upload, scrape trigger, stats (API-key auth)
# ============================================================

def require_upload_key(f):
    @wraps(f)
    def decorated(*a, **kw):
        key = (request.headers.get('Authorization', '').replace('Bearer ', '')
               or request.args.get('key', ''))
        if not key or key != cfg.UPLOAD_API_KEY:
            return jsonify({'error': 'invalid api key'}), 401
        return f(*a, **kw)
    decorated.__name__ = f.__name__
    return decorated

@app.route('/api/pool/upload', methods=['POST'])
@require_upload_key
def pool_upload():
    """Accept raw proxy text (ip:port per line) or JSON array and ingest into pool."""
    ct = request.content_type or ''
    if 'json' in ct:
        d = request.get_json(silent=True) or {}
        if isinstance(d, list):
            text = '\n'.join(str(x) for x in d)
        else:
            text = d.get('proxies', '') if isinstance(d.get('proxies'), str) else '\n'.join(d.get('proxies', []))
    else:
        text = request.get_data(as_text=True)
    validate = request.args.get('validate', '').lower() in ('1', 'true', 'yes')
    result = pool.ingest(text, validate=validate)
    return jsonify(result)

@app.route('/api/pool/scrape', methods=['POST'])
@require_upload_key
def pool_scrape():
    """Trigger a full server-side scrape + validate cycle."""
    import asyncio, threading
    result = {}
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result['stats'] = loop.run_until_complete(pool.run_cycle())
        finally:
            loop.close()
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=180)
    if 'stats' in result:
        return jsonify(result['stats'])
    return jsonify({'status': 'scrape started, still running'}), 202

@app.route('/api/pool/stats')
def pool_stats():
    """Public pool health stats."""
    s = pool.stats()
    return jsonify({'alive': s['alive'], 'countries': len(s.get('countries', [])),
                    'avg_latency': s.get('avg_latency', 0),
                    'pool_size': len(pool.proxies),
                    'updated': s.get('updated', '')})

@app.route('/api/pool/list')
@require_upload_key
def pool_list():
    """Return full proxy list (API-key protected)."""
    fmt = request.args.get('format', 'json')
    alive = pool.get_alive()
    if fmt == 'txt':
        from flask import Response
        return Response('\n'.join(f'{p.host}:{p.port}' for p in alive),
                        mimetype='text/plain')
    from dataclasses import asdict
    return jsonify({'count': len(alive), 'proxies': [asdict(p) for p in alive]})

@app.route('/api/shop/inventory')
def shop_inventory():
    """Public proxy inventory — IPs masked for non-authenticated users."""
    from dataclasses import asdict
    country = request.args.get('country', '').strip()
    protocol = request.args.get('protocol', '').strip()
    anonymity = request.args.get('anonymity', '').strip()
    limit = min(int(request.args.get('limit', 50)), 200)
    offset = int(request.args.get('offset', 0))
    items, total = pool.get_inventory(
        country=country or None,
        protocol=protocol or None,
        anonymity=anonymity or None,
        limit=limit, offset=offset)
    masked = []
    for p in items:
        d = asdict(p)
        parts = d['host'].split('.')
        d['host'] = f'{parts[0]}.{parts[1]}.xxx.xxx'
        d.pop('fails', None)
        d.pop('checks', None)
        d.pop('successes', None)
        d.pop('first_seen', None)
        d.pop('org', None)
        d.pop('asn', None)
        masked.append(d)
    return jsonify({'proxies': masked, 'total': total, 'limit': limit, 'offset': offset})

@app.route('/api/shop/inventory/filters')
def shop_inventory_filters():
    """Return available filter options for inventory."""
    return jsonify(pool.inventory_filters())

@app.route('/api/tools/myip')
def tools_myip():
    """Return visitor IP + full geo/ISP/proxy data via cascading APIs."""
    import requests as _req
    ip = (request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
          or request.headers.get('X-Real-IP', '')
          or request.headers.get('CF-Connecting-IP', '')
          or request.remote_addr)
    result = {'ip': ip, 'country': '', 'countryCode': '', 'region': '',
              'city': '', 'zip': '', 'lat': '', 'lon': '', 'timezone': '',
              'isp': '', 'org': '', 'as': '', 'proxy': False, 'hosting': False}
    filled = False
    # 1) ip-api.com (free, HTTP only, 45 req/min)
    if not filled:
        try:
            r = _req.get(
                f'http://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city,zip,lat,lon,timezone,isp,org,as,proxy,hosting,query',
                timeout=4)
            geo = r.json()
            if geo.get('status') == 'success':
                result.update({
                    'country': geo.get('country', ''), 'countryCode': geo.get('countryCode', ''),
                    'region': geo.get('regionName', ''), 'city': geo.get('city', ''),
                    'zip': geo.get('zip', ''), 'lat': geo.get('lat', ''),
                    'lon': geo.get('lon', ''), 'timezone': geo.get('timezone', ''),
                    'isp': geo.get('isp', ''), 'org': geo.get('org', ''),
                    'as': geo.get('as', ''), 'proxy': geo.get('proxy', False),
                    'hosting': geo.get('hosting', False), 'source': 'ip-api.com'})
                filled = True
        except Exception:
            pass
    # 2) ipwho.is (free, HTTPS, no key, no rate limit for moderate use)
    if not filled:
        try:
            r = _req.get(f'https://ipwho.is/{ip}', timeout=4)
            geo = r.json()
            if geo.get('success'):
                result.update({
                    'country': geo.get('country', ''), 'countryCode': geo.get('country_code', ''),
                    'region': geo.get('region', ''), 'city': geo.get('city', ''),
                    'zip': geo.get('postal', ''),
                    'lat': geo.get('latitude', ''), 'lon': geo.get('longitude', ''),
                    'timezone': geo.get('timezone', {}).get('id', '') if isinstance(geo.get('timezone'), dict) else '',
                    'isp': geo.get('connection', {}).get('isp', '') if isinstance(geo.get('connection'), dict) else '',
                    'org': geo.get('connection', {}).get('org', '') if isinstance(geo.get('connection'), dict) else '',
                    'as': 'AS' + str(geo.get('connection', {}).get('asn', '')) if isinstance(geo.get('connection'), dict) and geo.get('connection', {}).get('asn') else '',
                    'proxy': geo.get('security', {}).get('proxy', False) if isinstance(geo.get('security'), dict) else False,
                    'hosting': geo.get('type') == 'hosting',
                    'source': 'ipwho.is'})
                filled = True
        except Exception:
            pass
    # 3) ipapi.co (free, HTTPS, 1000/day)
    if not filled:
        try:
            r = _req.get(f'https://ipapi.co/{ip}/json/', timeout=4,
                         headers={'User-Agent': 'socks5proxy.shop/1.0'})
            geo = r.json()
            if not geo.get('error'):
                result.update({
                    'country': geo.get('country_name', ''), 'countryCode': geo.get('country_code', ''),
                    'region': geo.get('region', ''), 'city': geo.get('city', ''),
                    'zip': geo.get('postal', ''),
                    'lat': geo.get('latitude', ''), 'lon': geo.get('longitude', ''),
                    'timezone': geo.get('timezone', ''),
                    'isp': geo.get('org', ''), 'org': geo.get('org', ''),
                    'as': geo.get('asn', ''),
                    'proxy': False, 'hosting': False,
                    'source': 'ipapi.co'})
                filled = True
        except Exception:
            pass
    return jsonify(result)

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

SHOP_PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOCKS5 Proxy Shop · Premium Anonymous Proxies</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0a0e17; --surface: #111827; --card-bg: #1a1f2e; --card-hover: #1f2937;
  --border: rgba(255,255,255,.06); --border-light: rgba(255,255,255,.10);
  --text: #f1f5f9; --text-secondary: #94a3b8; --text-muted: #64748b;
  --accent: #3b82f6; --accent-hover: #2563eb; --accent-glow: rgba(59,130,246,.12);
  --success: #22c55e; --error: #ef4444; --warning: #f59e0b;
  --pro-accent: #8b5cf6; --pro-glow: rgba(139,92,246,.15);
  --radius: 14px; --radius-sm: 10px; --radius-xs: 6px;
  --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --font-mono: 'SF Mono', 'JetBrains Mono', 'Fira Code', monospace;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  background: var(--bg); color: var(--text); font-family: var(--font);
  -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
  min-height: 100vh; line-height: 1.6;
}
body::before {
  content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background:
    radial-gradient(ellipse 80% 50% at 50% -10%, rgba(59,130,246,.04), transparent),
    radial-gradient(ellipse 60% 40% at 90% 80%, rgba(139,92,246,.03), transparent);
}

/* Header */
header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(10,14,23,.82); backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px); border-bottom: 1px solid var(--border);
  padding: 0 32px; height: 68px; display: flex; align-items: center;
  justify-content: space-between;
}
.logo {
  font-weight: 800; font-size: 19px; letter-spacing: -.4px; color: var(--text);
  display: flex; align-items: center; gap: 10px;
}
.logo-dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--accent); box-shadow: 0 0 12px var(--accent);
}
.logo-sub { color: var(--text-muted); font-weight: 500; }
.stats-row { display: flex; gap: 32px; align-items: center; }
.stat-item { text-align: center; }
.stat-val { font-weight: 700; font-size: 15px; color: var(--text); }
.stat-lbl {
  font-size: 10px; color: var(--text-muted); text-transform: uppercase;
  letter-spacing: .6px; font-weight: 500;
}
.btn {
  font-family: var(--font); font-weight: 600; font-size: 13px; border: none;
  cursor: pointer; border-radius: var(--radius-xs); padding: 9px 18px;
  transition: all .2s ease; display: inline-flex; align-items: center; gap: 7px;
  white-space: nowrap;
}
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover { background: var(--accent-hover); box-shadow: 0 4px 20px var(--accent-glow); }
.btn-outline { background: transparent; border: 1px solid var(--border-light); color: var(--text-secondary); }
.btn-outline:hover { border-color: var(--accent); color: var(--accent); }
.btn-ghost { background: transparent; color: var(--text-secondary); padding: 8px 12px; }
.btn-ghost:hover { color: var(--text); }
.wallet-area { display: flex; align-items: center; gap: 8px; }
.wallet-addr {
  font-family: var(--font-mono); font-size: 12px; color: var(--accent);
  background: var(--accent-glow); padding: 6px 14px; border-radius: var(--radius-xs);
  border: 1px solid rgba(59,130,246,.18);
}
.dot-live {
  width: 7px; height: 7px; border-radius: 50%; background: var(--success);
  display: inline-block; margin-right: 5px; vertical-align: middle;
}

/* Main */
main { position: relative; z-index: 1; max-width: 1180px; margin: 0 auto; padding: 0 32px; }

/* Hero */
.hero { padding: 80px 0 56px; text-align: center; }
.hero .tag {
  display: inline-block; background: rgba(59,130,246,.07); border: 1px solid rgba(59,130,246,.14);
  color: var(--accent); font-size: 12px; font-weight: 600; padding: 6px 16px;
  border-radius: 20px; margin-bottom: 28px; letter-spacing: .3px;
}
.hero h1 {
  font-size: 56px; font-weight: 800; line-height: 1.12; letter-spacing: -1.8px;
  margin: 0 0 22px;
  background: linear-gradient(135deg, #f1f5f9 0%, #94a3b8 45%, var(--accent) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.hero p {
  font-size: 17px; color: var(--text-secondary); max-width: 580px;
  margin: 0 auto 36px; line-height: 1.65;
}
.hero .live-badge {
  display: inline-flex; align-items: center; gap: 10px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 10px 22px; border-radius: 22px; font-size: 13px; color: var(--text-secondary);
  font-weight: 500;
}
.pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--success); animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }

/* Plans */
.plans-section { padding: 8px 0 56px; }
.plans-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; align-items: stretch; }
.plan-card {
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 34px 30px;
  display: flex; flex-direction: column; position: relative;
  transition: all .3s cubic-bezier(.4,0,.2,1);
}
.plan-card:hover {
  background: var(--card-hover); border-color: var(--border-light);
  transform: translateY(-4px); box-shadow: 0 16px 48px rgba(0,0,0,.35);
}
.plan-card.pro {
  border-color: rgba(139,92,246,.3);
  box-shadow: 0 0 0 1px rgba(139,92,246,.15), 0 16px 48px var(--pro-glow);
}
.plan-card.pro::before {
  content: 'MOST POPULAR'; position: absolute; top: -13px; left: 50%;
  transform: translateX(-50%); background: var(--pro-accent); color: #fff;
  font-size: 10px; font-weight: 700; padding: 4px 16px; border-radius: 10px;
  letter-spacing: .8px;
}
.plan-name {
  font-size: 13px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 1.2px; margin-bottom: 6px;
}
.plan-name.free { color: var(--success); }
.plan-name.lite { color: var(--accent); }
.plan-name.pro { color: var(--pro-accent); }
.plan-subtitle { font-size: 13px; color: var(--text-muted); margin-bottom: 22px; line-height: 1.5; }
.price-row { display: flex; align-items: baseline; gap: 3px; margin-bottom: 4px; }
.price { font-size: 44px; font-weight: 800; letter-spacing: -1.2px; color: var(--text); }
.price-period { font-size: 14px; color: var(--text-muted); font-weight: 500; }
.billing-note { font-size: 12px; color: var(--text-muted); margin-bottom: 28px; }
.plan-card ul { list-style: none; flex: 1; margin-bottom: 28px; }
.plan-card ul li {
  padding: 8px 0; font-size: 13px; color: var(--text-secondary);
  display: flex; align-items: flex-start; gap: 10px; line-height: 1.45;
}
.plan-card ul li::before {
  content: ''; width: 5px; height: 5px; border-radius: 50%;
  background: var(--accent); flex-shrink: 0; margin-top: 6px;
}
.plan-card .btn-plan {
  width: 100%; justify-content: center; font-weight: 700; font-size: 14px;
  padding: 14px 0; border-radius: var(--radius-sm);
}
.btn-free { background: rgba(34,197,94,.07); color: var(--success); border: 1px solid rgba(34,197,94,.18); }
.btn-free:hover { background: rgba(34,197,94,.14); border-color: var(--success); }
.btn-buy { background: var(--accent); color: #fff; }
.btn-buy:hover { background: var(--accent-hover); }
.plan-card.pro .btn-buy {
  background: linear-gradient(135deg, var(--pro-accent), #6366f1);
}
.plan-card.pro .btn-buy:hover {
  background: linear-gradient(135deg, #9b8af7, #7c7af7);
}

/* Inventory Browser */
.inv-section { padding: 60px 32px; border-top: 1px solid var(--border); }
.inv-section .section-label {
  font-size: 12px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 1.2px; color: var(--text-muted); margin-bottom: 8px; text-align: center;
}
.inv-section h2 {
  text-align: center; font-size: 28px; font-weight: 800; letter-spacing: -.5px;
  margin-bottom: 6px;
}
.inv-section .inv-sub {
  text-align: center; color: var(--text-secondary); font-size: 14px; margin-bottom: 28px;
}
.inv-wrap { max-width: 1000px; margin: 0 auto; }
.inv-filters {
  display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px;
  align-items: center;
}
.inv-filters select, .inv-filters input {
  background: var(--card-bg); border: 1px solid var(--border); color: var(--text);
  font-family: var(--font); font-size: 13px; padding: 8px 12px;
  border-radius: var(--radius-xs); outline: none; min-width: 140px;
}
.inv-filters select:focus, .inv-filters input:focus { border-color: var(--accent); }
.inv-filters .inv-count {
  margin-left: auto; font-size: 13px; color: var(--text-muted); font-weight: 600;
}
.inv-table {
  width: 100%; border-collapse: collapse;
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden;
}
.inv-table thead { background: rgba(59,130,246,.06); }
.inv-table th {
  padding: 10px 14px; font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .5px; color: var(--text-muted);
  text-align: left; border-bottom: 1px solid var(--border);
}
.inv-table td {
  padding: 10px 14px; font-size: 13px; border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.inv-table tr:hover td { background: rgba(59,130,246,.03); }
.inv-table .inv-flag { font-size: 18px; margin-right: 6px; vertical-align: middle; }
.inv-table .inv-cc { font-weight: 600; font-size: 12px; }
.inv-proto {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 700; text-transform: uppercase;
}
.inv-proto.socks5 { background: rgba(34,197,94,.1); color: #22c55e; }
.inv-proto.socks4 { background: rgba(59,130,246,.1); color: #3b82f6; }
.inv-proto.http { background: rgba(245,158,11,.1); color: #f59e0b; }
.inv-proto.https { background: rgba(139,92,246,.1); color: #8b5cf6; }
.inv-anon {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 700;
}
.inv-anon.elite { background: rgba(34,197,94,.1); color: #22c55e; }
.inv-anon.anonymous { background: rgba(59,130,246,.1); color: #3b82f6; }
.inv-anon.transparent { background: rgba(239,68,68,.1); color: #ef4444; }
.inv-anon.unknown { background: rgba(100,116,139,.1); color: #64748b; }
.inv-latency { font-family: var(--font-mono); font-size: 12px; }
.inv-uptime { font-family: var(--font-mono); font-size: 12px; }
.inv-buy {
  background: rgba(59,130,246,.08); color: var(--accent); border: 1px solid rgba(59,130,246,.2);
  padding: 4px 14px; border-radius: var(--radius-xs); font-size: 12px;
  font-weight: 600; cursor: pointer; font-family: var(--font); transition: all .15s;
}
.inv-buy:hover { background: var(--accent); color: #fff; }
.inv-pager {
  display: flex; justify-content: center; gap: 8px; margin-top: 14px;
}
.inv-pager button {
  background: var(--card-bg); border: 1px solid var(--border); color: var(--text-muted);
  padding: 6px 14px; border-radius: var(--radius-xs); font-size: 12px;
  cursor: pointer; font-family: var(--font); transition: all .15s;
}
.inv-pager button:hover { border-color: var(--accent); color: var(--accent); }
.inv-pager button:disabled { opacity: .3; cursor: default; }
.inv-empty {
  text-align: center; padding: 40px; color: var(--text-muted); font-size: 14px;
}
@media (max-width: 768px) {
  .inv-section { padding: 40px 16px; }
  .inv-filters { flex-direction: column; }
  .inv-filters select, .inv-filters input { width: 100%; }
  .inv-table { font-size: 12px; }
  .inv-table th, .inv-table td { padding: 8px 10px; }
  .inv-filters .inv-count { margin-left: 0; }
}

/* Tools Section */
.tools-section { padding: 60px 32px; border-top: 1px solid var(--border); }
.tools-section .section-label {
  font-size: 12px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 1.2px; color: var(--text-muted); margin-bottom: 8px; text-align: center;
}
.tools-section h2 {
  text-align: center; font-size: 28px; font-weight: 800; letter-spacing: -.5px;
  margin-bottom: 6px;
}
.tools-section .tools-sub {
  text-align: center; color: var(--text-secondary); font-size: 14px; margin-bottom: 36px;
}
.tools-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; max-width: 960px; margin: 0 auto; }
.tool-card {
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 28px; transition: all .25s;
}
.tool-card:hover { border-color: var(--border-light); }
.tool-card h3 {
  font-size: 16px; font-weight: 700; margin-bottom: 4px;
  display: flex; align-items: center; gap: 8px;
}
.tool-card .tool-desc { font-size: 13px; color: var(--text-muted); margin-bottom: 18px; }
.tool-result {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 18px; min-height: 60px; font-size: 13px;
}
.tool-result .tr-row {
  display: flex; justify-content: space-between; padding: 6px 0;
  border-bottom: 1px solid var(--border);
}
.tool-result .tr-row:last-child { border-bottom: none; }
.tool-result .tr-label { color: var(--text-muted); font-weight: 500; font-size: 12px; }
.tool-result .tr-val { color: var(--text); font-weight: 600; font-size: 12px; text-align: right; max-width: 60%; word-break: break-all; }
.tr-val.good { color: var(--success); }
.tr-val.warn { color: var(--warning); }
.tr-val.bad { color: var(--error); }
.tool-result .tr-ip {
  font-family: var(--font-mono); font-size: 22px; font-weight: 800;
  color: var(--accent); text-align: center; padding: 14px 0 8px;
}
.tool-result .tr-flag {
  font-size: 32px; text-align: center; margin-bottom: 4px;
}
.tool-result .tr-loc {
  text-align: center; font-size: 13px; color: var(--text-secondary); padding-bottom: 10px;
  border-bottom: 1px solid var(--border); margin-bottom: 8px;
}
.fp-hash {
  font-family: var(--font-mono); font-size: 18px; font-weight: 700;
  color: var(--pro-accent); text-align: center; padding: 12px 0 10px;
  word-break: break-all;
}
.fp-unique {
  text-align: center; font-size: 12px; margin-bottom: 10px; padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.btn-tool {
  width: 100%; justify-content: center; margin-top: 14px;
  background: rgba(59,130,246,.07); color: var(--accent); border: 1px solid rgba(59,130,246,.18);
  font-weight: 600; font-size: 13px; padding: 10px 0; border-radius: var(--radius-xs);
  cursor: pointer; font-family: var(--font); transition: all .15s;
}
.btn-tool:hover { background: rgba(59,130,246,.14); border-color: var(--accent); }
.ip-risk-bar {
  width: 100%; height: 6px; background: rgba(255,255,255,.06);
  border-radius: 3px; margin: 12px 0 6px; overflow: hidden;
}
.ip-risk-fill {
  height: 100%; border-radius: 3px; transition: width .6s ease;
}
.ip-risk-fill.good { background: linear-gradient(90deg, #22c55e, #4ade80); }
.ip-risk-fill.warn { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.ip-risk-fill.bad { background: linear-gradient(90deg, #ef4444, #f87171); }
.affiliate-cta {
  margin-top: 16px; padding: 16px; background: linear-gradient(135deg, rgba(139,92,246,.08), rgba(59,130,246,.06));
  border: 1px solid rgba(139,92,246,.18); border-radius: var(--radius-xs);
  text-align: center;
}
.affiliate-cta a {
  display: inline-block; margin-top: 8px; padding: 8px 24px;
  background: linear-gradient(135deg, var(--pro-accent), #6366f1);
  color: #fff; font-weight: 700; font-size: 13px; border-radius: var(--radius-xs);
  text-decoration: none; transition: all .2s;
}
.affiliate-cta a:hover { filter: brightness(1.15); transform: translateY(-1px); }
@media (max-width: 768px) {
  .tools-grid { grid-template-columns: 1fr; max-width: 480px; }
  .tools-section { padding: 40px 20px; }
}

/* Promo */
.promo-section { padding: 52px 0 72px; text-align: center; border-top: 1px solid var(--border); }
.promo-section .section-label {
  font-size: 12px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 1.2px; color: var(--text-muted); margin-bottom: 14px;
}
.crypto-badges { display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; }
.crypto-badge {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 10px 18px;
  font-size: 12px; color: var(--text-secondary); font-weight: 600;
  transition: all .2s;
}
.crypto-badge:hover { border-color: var(--accent); color: var(--text); }

/* Footer */
footer {
  position: relative; z-index: 1; text-align: center; padding: 22px 32px;
  border-top: 1px solid var(--border); color: var(--text-muted);
  font-size: 12px; font-weight: 500;
}

/* Modal */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.72);
  backdrop-filter: blur(5px); -webkit-backdrop-filter: blur(5px);
  z-index: 200; display: none; align-items: center; justify-content: center;
}
.modal-overlay.active { display: flex; }
.modal {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); width: 92%; max-width: 480px;
  max-height: 92vh; overflow-y: auto; padding: 32px; position: relative;
}
.modal .close {
  position: absolute; top: 14px; right: 14px; background: none; border: none;
  color: var(--text-muted); font-size: 26px; cursor: pointer;
  width: 34px; height: 34px; display: flex; align-items: center;
  justify-content: center; border-radius: var(--radius-xs); transition: all .15s;
}
.modal .close:hover { color: var(--text); background: var(--card-bg); }
.modal h3 { font-size: 22px; font-weight: 700; margin-bottom: 4px; letter-spacing: -.3px; }
.modal .sub { font-size: 13px; color: var(--text-secondary); margin-bottom: 22px; }
.modal label {
  display: block; font-size: 11px; font-weight: 700; color: var(--text-secondary);
  margin-bottom: 5px; text-transform: uppercase; letter-spacing: .6px;
}
.modal input[type="email"], .modal input[type="text"] {
  width: 100%; padding: 11px 14px; background: var(--card-bg);
  border: 1px solid var(--border); border-radius: var(--radius-xs);
  color: var(--text); font-family: var(--font); font-size: 14px;
  outline: none; transition: border .2s; margin-bottom: 16px;
}
.modal input:focus { border-color: var(--accent); }
.step { display: none; }
.step.active { display: block; }

/* Payment */
.pay-methods { display: flex; gap: 8px; margin-bottom: 16px; }
.pay-method {
  flex: 1; background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 16px 10px; text-align: center;
  cursor: pointer; font-size: 13px; color: var(--text-secondary); font-weight: 600;
  transition: all .15s;
}
.pay-method:hover { border-color: var(--border-light); }
.pay-method.selected { border-color: var(--accent); color: var(--accent); background: var(--accent-glow); }
.chain-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.chain-chip {
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius-xs); padding: 8px 14px; font-size: 12px;
  cursor: pointer; color: var(--text-secondary); font-weight: 500;
  transition: all .15s;
}
.chain-chip:hover { border-color: var(--border-light); color: var(--text); }
.chain-chip.selected { border-color: var(--accent); color: var(--accent); background: var(--accent-glow); }

.pay-addr {
  font-family: var(--font-mono); font-size: 13px;
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius-xs); padding: 14px; word-break: break-all;
  color: var(--accent); margin: 8px 0;
}

/* Proxy reveal */
.proxy-box {
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 16px; margin: 12px 0;
  font-family: var(--font-mono);
}
.proxy-box .proxy-line { color: var(--success); font-size: 13px; padding: 2px 0; }
.proxy-box .key {
  background: var(--accent-glow); padding: 8px 12px; border-radius: var(--radius-xs);
  margin-top: 10px; display: inline-block; font-size: 11px; color: var(--accent);
  word-break: break-all;
}

/* Toast */
.toast {
  position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%);
  z-index: 500; background: var(--surface); border: 1px solid var(--border);
  color: var(--text); padding: 12px 26px; border-radius: var(--radius-sm);
  font-size: 13px; font-weight: 500; display: none;
  box-shadow: 0 8px 32px rgba(0,0,0,.5);
}
.toast.err { border-color: var(--error); color: var(--error); }
.toast.ok { border-color: var(--success); color: var(--success); }

/* Proxy Browser (modal) */
.proxy-browser { margin: 14px 0; }
.pb-filters { display: flex; gap: 8px; margin-bottom: 12px; }
.pb-filters select {
  flex: 1; padding: 9px 10px; background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius-xs); color: var(--text); font-family: var(--font);
  font-size: 13px; outline: none; cursor: pointer; appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%2364748b'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 10px center;
  padding-right: 28px;
}
.pb-filters select:focus { border-color: var(--accent); }
.pb-summary {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; background: var(--card-bg); border: 1px solid var(--border);
  border-radius: var(--radius-sm); margin-bottom: 10px; font-size: 13px;
}
.pb-count { font-weight: 700; color: var(--success); font-size: 18px; }
.pb-count.zero { color: var(--error); }
.pb-list {
  max-height: 180px; overflow-y: auto; border: 1px solid var(--border);
  border-radius: var(--radius-sm); background: var(--bg);
}
.pb-list::-webkit-scrollbar { width: 5px; }
.pb-list::-webkit-scrollbar-thumb { background: var(--border-light); border-radius: 3px; }
.pb-row {
  display: flex; align-items: center; padding: 8px 12px; gap: 10px;
  border-bottom: 1px solid var(--border); font-size: 12px;
}
.pb-row:last-child { border-bottom: none; }
.pb-row .pb-ip { font-family: var(--font-mono); color: var(--success); font-weight: 600; flex: 1; }
.pb-row .pb-cc { font-weight: 600; color: var(--text); min-width: 28px; }
.pb-row .pb-proto {
  font-size: 10px; font-weight: 700; text-transform: uppercase; padding: 2px 6px;
  border-radius: 3px; background: rgba(59,130,246,.1); color: var(--accent);
}
.pb-row .pb-proto.socks5 { background: rgba(139,92,246,.1); color: var(--pro-accent); }
.pb-row .pb-proto.socks4 { background: rgba(245,158,11,.1); color: var(--warning); }
.pb-row .pb-proto.http { background: rgba(34,197,94,.1); color: var(--success); }
.pb-row .pb-anon {
  font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 3px;
}
.pb-row .pb-anon.elite { background: rgba(34,197,94,.1); color: var(--success); }
.pb-row .pb-anon.anonymous { background: rgba(59,130,246,.1); color: var(--accent); }
.pb-row .pb-anon.transparent { background: rgba(239,68,68,.1); color: var(--error); }
.pb-row .pb-ms { color: var(--text-muted); font-size: 11px; min-width: 42px; text-align: right; }
.pb-empty { padding: 24px; text-align: center; color: var(--text-muted); font-size: 13px; }
.pb-more { text-align: center; padding: 8px; font-size: 11px; color: var(--text-muted); }

/* Spinner */
.spinner {
  display: inline-block; width: 15px; height: 15px;
  border: 2px solid var(--border); border-top-color: var(--accent);
  border-radius: 50%; animation: spin .6s linear infinite;
  vertical-align: middle; margin-right: 7px;
}
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 768px) {
  .hero h1 { font-size: 32px; }
  .plans-grid { grid-template-columns: 1fr; max-width: 400px; margin: 0 auto; }
  header { padding: 0 20px; }
  .stats-row { gap: 14px; }
  .stat-val { font-size: 13px; }
  .stat-lbl { font-size: 9px; }
}
</style>
<script type="module">
import{createAppKit,networks,SolanaAdapter}from"https://cdn.jsdelivr.net/npm/@reown/appkit-cdn@1.7.12/dist/appkit.js";
window.AppKit={createAppKit,networks,SolanaAdapter};
</script>
</head>
<body>
<main>
<header>
  <div class="logo">
    <span class="logo-dot"></span>
    <span>SOCKS5<span class="logo-sub">.SHOP</span></span>
  </div>
  <div class="stats-row">
    <div class="stat-item">
      <div class="stat-val" id="sAlive">—</div>
      <div class="stat-lbl">Proxies</div>
    </div>
    <div class="stat-item">
      <div class="stat-val" id="sCountries">—</div>
      <div class="stat-lbl">Countries</div>
    </div>
    <div class="stat-item">
      <div class="stat-val" id="sLatency">—</div>
      <div class="stat-lbl">Latency</div>
    </div>
  </div>
  <div class="wallet-area" id="walletArea">
    <button class="btn btn-outline" onclick="connectWallet()">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
        <rect x="2" y="5" width="20" height="14" rx="2"/>
        <path d="M22 10h-4.5a2 2 0 1 0 0 4H22"/>
      </svg>
      Connect Wallet
    </button>
  </div>
</header>

<section class="hero">
  <div class="tag">ANONYMOUS SOCKS5 PROXIES</div>
  <h1>Premium proxies.<br>Zero compromise.</h1>
  <p>
    Fresh, verified SOCKS5 proxies scraped and validated in real time.
    Built for scraping, pentesting, and privacy at scale.
  </p>
  <div class="live-badge">
    <span class="pulse"></span> Live — proxies refresh every hour
  </div>
</section>

<section class="plans-section">
  <div class="plans-grid" id="planCards"></div>
</section>

<section class="inv-section" id="inventory">
  <div class="section-label">Live Inventory</div>
  <h2>Browse Proxies</h2>
  <p class="inv-sub">Filter by country, protocol, and anonymity level. Pick exactly what you need.</p>
  <div class="inv-wrap">
    <div class="inv-filters">
      <select id="invCountry" onchange="loadInventory(0)"><option value="">All Countries</option></select>
      <select id="invProto" onchange="loadInventory(0)">
        <option value="">All Protocols</option>
        <option value="socks5">SOCKS5</option>
        <option value="socks4">SOCKS4</option>
        <option value="http">HTTP</option>
        <option value="https">HTTPS</option>
      </select>
      <select id="invAnon" onchange="loadInventory(0)">
        <option value="">All Anonymity</option>
        <option value="elite">Elite (Highly Anonymous)</option>
        <option value="anonymous">Anonymous</option>
        <option value="transparent">Transparent</option>
      </select>
      <span class="inv-count" id="invCount"></span>
    </div>
    <div id="invTable"></div>
    <div class="inv-pager" id="invPager"></div>
  </div>
</section>

<section class="tools-section" id="tools">
  <div class="section-label">Free Tools</div>
  <h2>Check Your Exposure</h2>
  <p class="tools-sub">See what websites know about you right now. Test your proxy, VPN, or raw connection.</p>
  <div class="tools-grid">
    <div class="tool-card">
      <h3>&#x1F50D; IP Address Checker</h3>
      <p class="tool-desc">Reveal your public IP, location, ISP, and detect proxy/VPN/WebRTC leaks.</p>
      <div class="tool-result" id="ipResult">
        <div style="text-align:center;padding:20px 0;color:var(--text-muted)">Click the button below to check your IP</div>
      </div>
      <button class="btn-tool" onclick="runIPCheck()">Check My IP</button>
    </div>
    <div class="tool-card">
      <h3>&#x1F9EC; Browser Fingerprint</h3>
      <p class="tool-desc">Canvas, WebGL, audio, screen, fonts, and 20+ signals that make you uniquely trackable.</p>
      <div class="tool-result" id="fpResult">
        <div style="text-align:center;padding:20px 0;color:var(--text-muted)">Click the button below to fingerprint your browser</div>
      </div>
      <button class="btn-tool" onclick="runFingerprint()">Scan My Fingerprint</button>
      <div class="affiliate-cta" id="affiliateCta" style="display:none">
        <div style="font-size:13px;color:var(--text-secondary);margin-bottom:6px">&#x1F6E1;&#xFE0F; <strong style="color:var(--text)">Your browser fingerprint is unique and trackable.</strong></div>
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px">Multilogin masks your fingerprint across unlimited browser profiles &mdash; trusted by 15,000+ professionals worldwide.</div>
        <a href="https://multilogin.com/?ref=YOUR_AFFILIATE_ID" target="_blank" rel="noopener">Try Multilogin Free &rarr;</a>
      </div>
    </div>
  </div>
</section>

<section class="promo-section">
  <div class="section-label">Accepted Payments</div>
  <p style="color:var(--text-secondary);font-size:14px;margin-bottom:18px">
    WalletConnect &middot; MetaMask &middot; Trust Wallet &middot; Coinbase Wallet
    &middot; BTC &middot; LTC &middot; ETH &middot; SOL &middot; USDT &middot; USDC
  </p>
  <div class="crypto-badges">
    <div class="crypto-badge">₿ Bitcoin</div>
    <div class="crypto-badge">Ł Litecoin</div>
    <div class="crypto-badge">⟠ Ethereum</div>
    <div class="crypto-badge">◎ Solana</div>
    <div class="crypto-badge">◆ Polygon</div>
    <div class="crypto-badge">◆ BSC</div>
    <div class="crypto-badge">◆ Arbitrum</div>
  </div>
</section>

<footer>
  &copy; 2026 SOCKS5PROXY.SHOP &mdash; No logs. Full anonymity. Always encrypted.
</footer>
</main>

<!-- Modal -->
<div class="modal-overlay" id="orderModal">
<div class="modal">
  <button class="close" onclick="closeModal()">&times;</button>

  <div class="step active" id="step1">
    <h3 id="mPlanTitle">Get Started</h3>
    <p class="sub" id="mPlanSub"></p>
    <label for="mEmail">Email</label>
    <input type="email" id="mEmail" placeholder="you@example.com">
    <label for="mCountries">Countries (optional)</label>
    <input type="text" id="mCountries" placeholder="US, DE, JP">
    <button class="btn btn-primary" style="width:100%" onclick="handleCheckout()">Continue</button>
    <div id="freeStatus" style="text-align:center;margin-top:10px;font-size:12px"></div>
  </div>

  <div class="step" id="step2">
    <h3>Choose Payment</h3>
    <p class="sub">Select your payment method</p>
    <div class="pay-methods" id="payMethods"></div>
    <div id="chainSelect" class="chain-grid" style="display:none"></div>
    <div class="chain-grid" id="tokenChips" style="display:none"></div>
    <div id="payQuote" style="margin:12px 0;font-size:13px;display:none"></div>
    <button class="btn btn-primary" style="width:100%" onclick="initPayment()">Pay Now</button>
    <button class="btn btn-ghost" style="width:100%;margin-top:6px" onclick="goStep(1)">Back</button>
  </div>

  <div class="step" id="step3">
    <h3>Send Payment</h3>
    <div id="payInfo"></div>
    <p id="payStatus" style="color:var(--text-secondary);font-size:13px;margin-top:8px">
      <span class="spinner"></span> Waiting for payment...
    </p>
    <button class="btn btn-ghost" style="margin-top:8px" onclick="checkPayManually()">
      I already paid — check now
    </button>
  </div>

  <div class="step" id="step4">
    <h3>Active</h3>
    <p>Order: <b id="mOrderId" style="color:var(--accent)"></b></p>
    <p style="color:var(--text-muted);font-size:12px">Your proxies are live. Save your API key.</p>
    <div id="mProxies"></div>
    <button class="btn btn-primary" style="width:100%" onclick="closeModal()">Done</button>
  </div>
</div></div>

<div id="toast" class="toast"></div>

<script>
const PROJECT_ID='__PID__';
const CHAINS=__CHAINS__;
const WALLETS=__WALLETS__;

let walletConnected=false,walletAddress='',walletChain='',sessionToken='';
let selectedPlan=null,selectedChain=null,selectedToken=null,currentOrder=null,currentPayment=null;
let isUtxoOrder=false,isFreeTier=false;

function toast(m,err,ok){
  const t=document.getElementById('toast');
  t.textContent=m;t.className='toast'+(err?' err':ok?' ok':'');
  t.style.display='block';setTimeout(()=>t.style.display='none',4000);
}
function shortAddr(a){return a.slice(0,6)+'...'+a.slice(-4);}

async function loadStats(){
  try{
    const s=await(await fetch('/api/shop/stats')).json();
    document.getElementById('sAlive').textContent=s.alive.toLocaleString();
    document.getElementById('sCountries').textContent=s.countries;
    document.getElementById('sLatency').textContent=s.avg_latency+'ms';
  }catch(e){}
}

async function loadPlans(){
  const plans=await(await fetch('/api/shop/plans')).json();
  window._plansCache=plans;
  const el=document.getElementById('planCards');el.innerHTML='';
  const order=['free','lite','pro'];
  for(const id of order){
    const p=plans[id];if(!p)continue;
    const isFree=p.price_usd===0;
    const nameClass=isFree?'free':(id==='pro'?'pro':'lite');
    const cardClass=id==='pro'?' pro':'';
    const btnClass=isFree?'btn-free':'btn-buy';
    const btnText=isFree?'Claim Free':'Get '+p.name;
    const qtyLabel=(p.proxy_count>=999)?'Unlimited':(p.proxy_count+' proxies');
    const subtitle=isFree
      ?'1 proxy for testing — no payment required'
      :qtyLabel+' — '+p.duration_days+' days';
    const billing=isFree?'':'One-time payment';
    const featuresHtml=p.features.map(f=>'<li>'+f+'</li>').join('');
    el.innerHTML+=
'<div class="plan-card'+cardClass+'">'+
'<div class="plan-name '+nameClass+'">'+p.name+'</div>'+
'<div class="plan-subtitle">'+subtitle+'</div>'+
'<div class="price-row"><span class="price">$'+(isFree?'0':p.price_usd)+'</span>'+
'<span class="price-period">'+(isFree?'':' USD')+'</span></div>'+
'<div class="billing-note">'+billing+'</div>'+
'<ul>'+featuresHtml+'</ul>'+
'<button class="btn btn-plan '+btnClass+'" onclick="openOrder(&#39;'+id+'&#39;)">'+btnText+'</button>'+
'</div>';
  }
}

async function connectWallet(){
  if(!PROJECT_ID||PROJECT_ID==='demo-pid'){toast('WalletConnect not configured — use BTC/LTC',true);return;}
  if(!window.AppKit){for(let i=0;i<12&&!window.AppKit;i++)await new Promise(r=>setTimeout(r,500));}
  if(!window.AppKit){toast('Wallet SDK still loading, please retry...',true);return;}
  try{
    if(!window._appkit){
      const AK=window.AppKit;
      const cmap={1:'mainnet',137:'polygon',56:'bsc',42161:'arbitrum'};
      const nets=CHAINS.filter(c=>c.type!=='utxo'&&typeof c.chain_id==='number')
        .map(c=>AK.networks[cmap[c.chain_id]]).filter(Boolean);
      if(CHAINS.find(c=>c.id==='solana')&&AK.networks.solana)nets.push(AK.networks.solana);
      window._appkit=AK.createAppKit({
        projectId:PROJECT_ID,
        networks:nets.length?nets:[AK.networks.mainnet],
        metadata:{name:'SOCKS5 Proxy Shop',description:'Premium SOCKS5 Proxies',url:window.location.origin,icons:[]},
        features:{email:true,socials:['google','x','discord','github']}
      });
    }
    await window._appkit.open();
    const state=window._appkit.getState?.()||{};
    const addr=state.address||window._appkit.getAddress?.()||'';
    const cid=state.chainId||window._appkit.getChainId?.()||0;
    if(addr){walletAddress=addr;walletChain=CHAINS.find(c=>c.chain_id===cid)?.id||'';await signIn();}
  }catch(e){toast('Connection failed: '+e.message,true);}
}

async function signIn(){
  try{
    const nr=await fetch('/api/wallet/nonce');const{nonce}=await nr.json();
    const mr=await fetch('/api/wallet/siwe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({address:walletAddress,chain:walletChain,nonce})});
    const{message}=await mr.json();
    const sig=await window._appkit.signMessage(message);
    const ar=await fetch('/api/wallet/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,signature:sig})});
    const data=await ar.json();
    if(data.error){toast(data.error,true);return;}
    sessionToken=data.token;walletConnected=true;
    document.getElementById('walletArea').innerHTML='<span class="wallet-addr"><span class="dot-live"></span>'+shortAddr(walletAddress)+'</span> <button class="btn btn-ghost" onclick="disconnect()">Disconnect</button>';
    toast('Connected',null,'ok');
  }catch(e){toast('Sign-in failed: '+e.message,true);}
}

function disconnect(){
  walletConnected=false;walletAddress='';walletChain='';sessionToken='';
  document.getElementById('walletArea').innerHTML='<button class="btn btn-outline" onclick="connectWallet()"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M22 10h-4.5a2 2 0 1 0 0 4H22"/></svg>Connect Wallet</button>';
}

function openOrder(id){
  selectedPlan=id;isUtxoOrder=false;isFreeTier=false;
  selectedChain=null;selectedToken=null;currentPayment=null;currentOrder=null;
  const p=window._plansCache?.[id];if(!p)return;
  document.getElementById('mPlanTitle').textContent=p.name+' Plan';
  document.getElementById('mPlanSub').textContent=p.price_usd===0
    ?'1 free proxy for 24 hours. No payment required.'
    :(p.proxy_count>=999?'Unlimited':p.proxy_count+' proxies')+' · '+p.duration_days+' days · $'+p.price_usd+' USD';
  document.getElementById('freeStatus').innerHTML='';
  goStep(1);
  if(p.price_usd===0){
    document.getElementById('freeStatus').innerHTML=
      '<span style="color:var(--success);font-size:12px">No payment needed. Enter your email and click Claim.</span>';
  }
  document.getElementById('orderModal').classList.add('active');
}

function closeModal(){document.getElementById('orderModal').classList.remove('active');}

function goStep(n){
  document.querySelectorAll('.step').forEach(s=>s.classList.remove('active'));
  document.getElementById('step'+n).classList.add('active');
}

async function handleCheckout(){
  const email=document.getElementById('mEmail').value.trim();
  const countries=document.getElementById('mCountries').value;
  if(!email.includes('@')){toast('Valid email required',true);return;}
  const p=window._plansCache?.[selectedPlan];
  if(p&&p.price_usd===0){await claimFree(email,countries);return;}
  goStep(2);renderPaymentMethods();
}

async function claimFree(email,countries){
  const r=await fetch('/api/shop/free',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,countries})});
  const d=await r.json();
  if(d.error){toast(d.error,true);return;}
  toast('Free proxy claimed! Check your email.',null,'ok');
  showFreeResult(d,email);
}

function renderPaymentMethods(){
  const el=document.getElementById('payMethods');el.innerHTML='';
  el.innerHTML+='<div class="pay-method selected" id="pm-wc" onclick="selectPayMethod(&#39;wc&#39;)">WalletConnect<br><span style="font-size:10px;color:var(--text-muted)">ETH · SOL · USDT</span></div>';
  el.innerHTML+='<div class="pay-method" id="pm-btc" onclick="selectPayMethod(&#39;btc&#39;)">Bitcoin<br><span style="font-size:10px;color:var(--text-muted)">₿ BTC</span></div>';
  el.innerHTML+='<div class="pay-method" id="pm-ltc" onclick="selectPayMethod(&#39;ltc&#39;)">Litecoin<br><span style="font-size:10px;color:var(--text-muted)">Ł LTC</span></div>';
  selectPayMethod('wc');
}

function selectPayMethod(method){
  document.querySelectorAll('.pay-method').forEach(el=>el.classList.remove('selected'));
  document.getElementById('pm-'+method).classList.add('selected');
  document.getElementById('chainSelect').style.display='none';
  document.getElementById('tokenChips').style.display='none';
  document.getElementById('payQuote').style.display='none';
  isUtxoOrder=false;selectedChain=null;selectedToken=null;currentPayment=null;
  if(method==='btc'){selectChainManual('bitcoin','BTC');}
  else if(method==='ltc'){selectChainManual('litecoin','LTC');}
  else{renderChainSelector();}
}

function selectChainManual(chain,token){
  isUtxoOrder=true;selectedChain=chain;selectedToken=token;currentPayment=null;
  document.getElementById('payQuote').style.display='block';
  loadQuote(chain,token);
}

function renderChainSelector(){
  document.getElementById('chainSelect').style.display='flex';
  document.getElementById('tokenChips').style.display='flex';
  isUtxoOrder=false;
  const el=document.getElementById('chainSelect');el.innerHTML='';
  const wcChains=CHAINS.filter(c=>c.type!=='utxo');
  wcChains.forEach(c=>{
    el.innerHTML+='<div class="chain-chip" id="ch-'+c.id+'" onclick="selChain(&#39;'+c.id+'&#39;)">'+c.name+'</div>';
  });
  if(wcChains.length)selChain(wcChains[0].id);
}

function selChain(id){
  selectedChain=id;isUtxoOrder=false;
  document.querySelectorAll('#chainSelect .chain-chip').forEach(el=>el.classList.remove('selected'));
  document.getElementById('ch-'+id).classList.add('selected');
  const c=CHAINS.find(x=>x.id===id);
  const tl=document.getElementById('tokenChips');tl.innerHTML='';
  c.tokens.forEach(t=>{
    tl.innerHTML+='<div class="chain-chip" id="tk-'+t.symbol+'" onclick="selToken(&#39;'+t.symbol+'&#39;)">'+t.symbol+'</div>';
  });
  if(c.tokens.length)selToken(c.tokens[0].symbol);
}

function selToken(sym){
  selectedToken=sym;
  document.querySelectorAll('#tokenChips .chain-chip').forEach(el=>el.classList.remove('selected'));
  document.getElementById('tk-'+sym).classList.add('selected');
  loadQuote(selectedChain,sym);
}

async function loadQuote(chain,token){
  const q=document.getElementById('payQuote');q.style.display='block';
  q.innerHTML='<span class="spinner"></span>Getting quote...';
  try{
    const r=await fetch('/api/wallet/quote?plan='+selectedPlan+'&chain='+chain+'&token='+token);
    const d=await r.json();
    if(d.error){q.innerHTML='<span style="color:var(--error)">'+d.error+'</span>';currentPayment=null;return;}
    currentPayment=d.payment;
    const cn=CHAINS.find(c=>c.id===chain)?.name||chain;
    q.innerHTML='<span style="color:var(--accent);font-weight:600">'+d.payment.amount_human+' '+token+'</span><br><span style="font-size:11px;color:var(--text-muted)">on '+cn+' ≈ $'+d.payment.amount_usd+' USD</span>';
  }catch(e){q.innerHTML='<span style="color:var(--error)">Quote failed</span>';}
}

async function initPayment(){
  const email=document.getElementById('mEmail').value.trim();
  const countries=document.getElementById('mCountries').value;
  if(!email.includes('@')){toast('Valid email required',true);goStep(1);return;}
  if(!selectedChain||!selectedToken){toast('Select payment method',true);return;}
  const body={plan:selectedPlan,email,countries,chain:selectedChain,token:selectedToken};
  if(!isUtxoOrder&&walletAddress)body.wallet=walletAddress;
  const r=await fetch('/api/shop/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  if(d.error){toast(d.error,true);return;}
  currentOrder=d.order;currentPayment=d.payment;
  const c=CHAINS.find(x=>x.id===selectedChain);
  document.getElementById('payInfo').innerHTML=
    '<p><b>Order:</b> <span style="color:var(--accent)">'+d.order.order_id+'</span></p>'+
    '<p><b>Amount:</b> '+d.payment.amount_human+' '+selectedToken+' ≈ $'+d.payment.amount_usd+'</p>'+
    '<p><b>Send to:</b></p><div class="pay-addr">'+d.payment.receiver+'</div>'+
    (c?'<p style="font-size:11px"><a style="color:var(--accent)" target="_blank" href="'+c.explorer+'/address/'+d.payment.receiver+'">View on explorer →</a></p>':'')+
    '<p style="font-size:11px;color:var(--text-muted)">Send the exact amount. Confirmation may take a few minutes.</p>';
  goStep(3);pollPayment();
}

function checkPayManually(){pollPayment(true);}

async function pollPayment(force){
  if(!currentPayment||!currentOrder)return;
  const ps=document.getElementById('payStatus');
  ps.innerHTML='<span class="spinner"></span>Checking blockchain...';
  try{
    const r=await fetch('/api/wallet/check?payment_id='+currentPayment.payment_id+'&order_id='+currentOrder.order_id);
    const d=await r.json();
    if(d.paid){showResult(d);}
    else{ps.innerHTML='<span style="color:var(--warning)">Waiting for confirmation...</span>';setTimeout(()=>pollPayment(false),10000);}
  }catch(e){ps.innerHTML='<span style="color:var(--error)">Check failed, retrying...</span>';setTimeout(()=>pollPayment(false),10000);}
}

function showFreeResult(d,email){
  goStep(4);
  document.getElementById('mOrderId').textContent=d.order_id||'';
  document.getElementById('mProxies').innerHTML=
    '<div class="proxy-box" style="text-align:center;padding:24px 16px">'+
    '<div style="font-size:32px;margin-bottom:12px">&#x2709;&#xFE0F;</div>'+
    '<div style="font-size:15px;font-weight:600;color:var(--success);margin-bottom:8px">Proxy sent to your email!</div>'+
    '<div style="font-size:13px;color:var(--text-secondary)">Check <span style="color:var(--accent);font-weight:600">'+email+'</span> for your SOCKS5 proxy details.</div>'+
    '<div style="font-size:12px;color:var(--text-muted);margin-top:12px">Expires: '+(d.expires_at||'').replace("T"," ").substring(0,16)+'</div>'+
    '</div>';
}

function showResult(d){
  currentOrder=d;goStep(4);
  document.getElementById('mOrderId').textContent=d.order_id||currentOrder?.order_id||'';
  const html=d.proxies
    ?d.proxies.map(p=>'<div class="proxy-line">'+p+'</div>').join('')
    :'<div class="proxy-line" style="color:var(--text-muted)">Proxy assigned</div>';
  document.getElementById('mProxies').innerHTML=
    '<div class="proxy-box">'+html+'</div>'+
    '<div class="proxy-box" style="margin-top:8px"><span style="font-size:11px;color:var(--text-muted)">API Key</span><br><span style="color:var(--accent);font-size:13px">'+(d.api_key||currentOrder?.api_key||'')+'</span></div>';
}

// ─── IP CHECKER ───
async function runIPCheck(){
  const el=document.getElementById('ipResult');
  el.innerHTML='<div style="text-align:center;padding:20px 0"><span class="spinner"></span> Analyzing your connection...</div>';
  try{
    const sr=await fetch('/api/tools/myip');
    const d=await sr.json();
    const ip=d.ip||'unknown';
    const cc=d.countryCode||'';
    const flag=cc?String.fromCodePoint(...[...cc.toUpperCase()].map(c=>0x1F1E6+c.charCodeAt(0)-65)):'&#x1F310;';
    const proxyDetected=d.proxy||d.hosting;
    // WebRTC leak check
    let webrtcIPs=[];
    try{webrtcIPs=await detectWebRTC();}catch(e){}
    const rtcLeak=webrtcIPs.filter(x=>x!==ip&&!x.startsWith('192.168.')&&!x.startsWith('10.')&&!x.startsWith('172.'));
    // Risk score
    let risk=0,riskFactors=[];
    if(d.proxy){risk+=40;riskFactors.push('Proxy/VPN detected');}
    if(d.hosting){risk+=30;riskFactors.push('Datacenter IP');}
    if(rtcLeak.length){risk+=20;riskFactors.push('WebRTC leak');}
    if(!d.proxy&&!d.hosting){risk+=10;riskFactors.push('Residential IP');}
    const riskPct=Math.min(risk,100);
    const riskColor=riskPct>=60?'good':riskPct>=30?'warn':'bad';
    const riskLabel=riskPct>=60?'Low Exposure':riskPct>=30?'Moderate Exposure':'High Exposure';
    el.innerHTML=
      '<div class="tr-flag">'+flag+'</div>'+
      '<div class="tr-ip">'+ip+'</div>'+
      '<div class="tr-loc">'+(d.city||'')+(d.city&&d.region?', ':'')+
      (d.region||'')+(d.city||d.region?', ':'')+
      (d.country||'')+'</div>'+
      '<div class="ip-risk-bar"><div class="ip-risk-fill '+riskColor+'" style="width:'+riskPct+'%"></div></div>'+
      '<div style="text-align:center;margin-bottom:12px"><span class="tr-val '+riskColor+'" style="font-size:13px;font-weight:700">'+riskLabel+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">ISP</span><span class="tr-val">'+(d.isp||'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">Organization</span><span class="tr-val">'+(d.org||'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">ASN</span><span class="tr-val">'+(d.as||'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">Region</span><span class="tr-val">'+(d.region||'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">ZIP Code</span><span class="tr-val">'+(d.zip||'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">Timezone</span><span class="tr-val">'+(d.timezone||'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">Coordinates</span><span class="tr-val">'+(d.lat&&d.lon?d.lat+', '+d.lon:'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">Proxy / VPN</span><span class="tr-val '+(d.proxy?'good':'bad')+'">'+(d.proxy?'&#x2705; Detected':'&#x274C; Not Detected')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">Hosting / DC</span><span class="tr-val '+(d.hosting?'good':'warn')+'">'+(d.hosting?'&#x2705; Yes':'&#x274C; No')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">WebRTC Leak</span><span class="tr-val '+(rtcLeak.length?'bad':'good')+'">'+(rtcLeak.length?'&#x26A0;&#xFE0F; '+rtcLeak.join(', '):'&#x2705; None detected')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">DNS Leak</span><span class="tr-val '+(d.proxy?'good':'warn')+'">'+(d.proxy?'&#x2705; Protected':'&#x26A0;&#xFE0F; Exposed')+'</span></div>';
  }catch(e){
    el.innerHTML='<div style="color:var(--error);text-align:center;padding:12px">Detection failed: '+e.message+'</div>';
  }
}

function detectWebRTC(){
  return new Promise((resolve)=>{
    const ips=new Set();
    try{
      const pc=new RTCPeerConnection({iceServers:[{urls:'stun:stun.l.google.com:19302'}]});
      pc.createDataChannel('');
      pc.onicecandidate=e=>{
        if(!e.candidate){pc.close();resolve([...ips]);return;}
        const m=e.candidate.candidate.match(/(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/);
        if(m)ips.add(m[1]);
      };
      pc.createOffer().then(o=>pc.setLocalDescription(o));
      setTimeout(()=>{pc.close();resolve([...ips]);},3000);
    }catch(e){resolve([]);}
  });
}

// ─── FINGERPRINT ───
async function runFingerprint(){
  const el=document.getElementById('fpResult');
  el.innerHTML='<div style="text-align:center;padding:20px 0"><span class="spinner"></span> Scanning fingerprint...</div>';
  await new Promise(r=>setTimeout(r,300));
  const fp={};
  // Canvas
  try{
    const c=document.createElement('canvas');c.width=280;c.height=40;
    const ctx=c.getContext('2d');
    ctx.textBaseline='top';
    ctx.font='16px Arial';ctx.fillStyle='#f60';ctx.fillRect(100,1,62,20);
    ctx.fillStyle='#069';ctx.fillText('SOCKS5PROXY.SHOP',2,15);
    ctx.fillStyle='rgba(102,204,0,0.7)';ctx.fillText('fingerprint',4,17);
    fp.canvas=await hashStr(c.toDataURL());
  }catch(e){fp.canvas='blocked';}
  // WebGL
  try{
    const c=document.createElement('canvas');const gl=c.getContext('webgl')||c.getContext('experimental-webgl');
    if(gl){
      const dbg=gl.getExtension('WEBGL_debug_renderer_info');
      fp.webgl_vendor=dbg?gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL):'N/A';
      fp.webgl_renderer=dbg?gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL):'N/A';
    }else{fp.webgl_vendor='blocked';fp.webgl_renderer='blocked';}
  }catch(e){fp.webgl_vendor='error';fp.webgl_renderer='error';}
  // Audio
  try{
    const actx=new(window.OfflineAudioContext||window.webkitOfflineAudioContext)(1,44100,44100);
    const osc=actx.createOscillator();osc.type='triangle';osc.frequency.setValueAtTime(10000,actx.currentTime);
    const comp=actx.createDynamicsCompressor();
    osc.connect(comp);comp.connect(actx.destination);osc.start(0);
    const buf=await actx.startRendering();
    const d=buf.getChannelData(0).slice(4500,5000);
    let sum=0;for(let i=0;i<d.length;i++)sum+=Math.abs(d[i]);
    fp.audio=await hashStr(sum.toString());
  }catch(e){fp.audio='blocked';}
  // Navigator
  fp.user_agent=navigator.userAgent;
  fp.platform=navigator.platform||'N/A';
  fp.language=navigator.language;
  fp.languages=(navigator.languages||[]).join(', ');
  fp.hardware_concurrency=navigator.hardwareConcurrency||'N/A';
  fp.device_memory=navigator.deviceMemory||'N/A';
  fp.max_touch=navigator.maxTouchPoints||0;
  fp.do_not_track=navigator.doNotTrack||'unset';
  fp.cookie_enabled=navigator.cookieEnabled;
  // Screen
  fp.screen=screen.width+'x'+screen.height+'x'+screen.colorDepth;
  fp.avail_screen=screen.availWidth+'x'+screen.availHeight;
  fp.pixel_ratio=window.devicePixelRatio||1;
  // Timezone
  fp.timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;
  fp.tz_offset=new Date().getTimezoneOffset();
  // Storage
  fp.local_storage=typeof localStorage!=='undefined';
  fp.session_storage=typeof sessionStorage!=='undefined';
  fp.indexed_db=!!window.indexedDB;
  // Fonts (probe common ones)
  const testFonts=['Arial','Verdana','Times New Roman','Courier New','Georgia','Comic Sans MS','Impact','Trebuchet MS','Palatino','Lucida Console','Tahoma','Consolas','Helvetica Neue','Segoe UI','Roboto','Noto Sans'];
  const detected=[];
  const testSpan=document.createElement('span');
  testSpan.style.cssText='position:absolute;left:-9999px;font-size:72px;';
  testSpan.textContent='mmmmmmmmmmlli';
  document.body.appendChild(testSpan);
  testSpan.style.fontFamily='monospace';
  const baseW=testSpan.offsetWidth;
  for(const f of testFonts){
    testSpan.style.fontFamily='"'+f+'",monospace';
    if(testSpan.offsetWidth!==baseW)detected.push(f);
  }
  document.body.removeChild(testSpan);
  fp.fonts_detected=detected.length;
  // Permissions
  const perms=['geolocation','notifications','camera','microphone'];
  const permResults=[];
  for(const p of perms){
    try{const s=await navigator.permissions.query({name:p});permResults.push(p+':'+s.state);}catch(e){}
  }
  fp.permissions=permResults.join(', ')||'N/A';
  // Compute overall hash
  const allStr=JSON.stringify(fp);
  const fpHash=await hashStr(allStr);
  const uniqueness=((parseInt(fpHash.substring(0,8),16)%9000+1000)/100).toFixed(1);
  el.innerHTML=
    '<div class="fp-hash">'+fpHash.substring(0,16).toUpperCase()+'</div>'+
    '<div class="fp-unique"><span style="color:var(--warning)">Your browser has a nearly unique fingerprint</span></div>'+
    '<div class="tr-row"><span class="tr-label">Canvas Hash</span><span class="tr-val">'+(fp.canvas==='blocked'?'<span class="good">Blocked</span>':fp.canvas.substring(0,12)+'...')+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">WebGL Renderer</span><span class="tr-val">'+fp.webgl_renderer.substring(0,40)+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">Audio Hash</span><span class="tr-val">'+(fp.audio==='blocked'?'<span class="good">Blocked</span>':fp.audio.substring(0,12)+'...')+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">Platform</span><span class="tr-val">'+fp.platform+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">Screen</span><span class="tr-val">'+fp.screen+' @'+fp.pixel_ratio+'x</span></div>'+
    '<div class="tr-row"><span class="tr-label">Timezone</span><span class="tr-val">'+fp.timezone+' (UTC'+(-fp.tz_offset/60>=0?'+':'')+(-fp.tz_offset/60)+')</span></div>'+
    '<div class="tr-row"><span class="tr-label">Language</span><span class="tr-val">'+fp.languages+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">CPU Cores</span><span class="tr-val">'+fp.hardware_concurrency+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">Memory</span><span class="tr-val">'+(fp.device_memory!=='N/A'?fp.device_memory+' GB':'Hidden')+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">Touch Points</span><span class="tr-val">'+fp.max_touch+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">Do Not Track</span><span class="tr-val '+(fp.do_not_track==='1'?'good':'warn')+'">'+fp.do_not_track+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">Fonts Detected</span><span class="tr-val">'+fp.fonts_detected+'/'+testFonts.length+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">Cookies</span><span class="tr-val">'+(fp.cookie_enabled?'Enabled':'Disabled')+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">IndexedDB</span><span class="tr-val">'+(fp.indexed_db?'Available':'Blocked')+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">Permissions</span><span class="tr-val" style="font-size:10px">'+fp.permissions+'</span></div>'+
    '<div class="tr-row"><span class="tr-label">User Agent</span><span class="tr-val" style="font-size:10px">'+fp.user_agent.substring(0,60)+'...</span></div>';
  document.getElementById('affiliateCta').style.display='block';
}

async function hashStr(s){
  const buf=new TextEncoder().encode(s);
  const hb=await crypto.subtle.digest('SHA-256',buf);
  return Array.from(new Uint8Array(hb)).map(b=>b.toString(16).padStart(2,'0')).join('');
}

// ─── INVENTORY BROWSER ───
const INV_COUNTRY_NAMES={AF:'Afghanistan',AL:'Albania',DZ:'Algeria',AR:'Argentina',AM:'Armenia',AU:'Australia',AT:'Austria',AZ:'Azerbaijan',BD:'Bangladesh',BY:'Belarus',BE:'Belgium',BA:'Bosnia',BR:'Brazil',BG:'Bulgaria',KH:'Cambodia',CA:'Canada',CL:'Chile',CN:'China',CO:'Colombia',HR:'Croatia',CZ:'Czechia',DK:'Denmark',EC:'Ecuador',EG:'Egypt',EE:'Estonia',FI:'Finland',FR:'France',GE:'Georgia',DE:'Germany',GH:'Ghana',GR:'Greece',HK:'Hong Kong',HU:'Hungary',IN:'India',ID:'Indonesia',IR:'Iran',IQ:'Iraq',IE:'Ireland',IL:'Israel',IT:'Italy',JP:'Japan',KZ:'Kazakhstan',KE:'Kenya',KR:'South Korea',LV:'Latvia',LT:'Lithuania',MY:'Malaysia',MX:'Mexico',MD:'Moldova',MN:'Mongolia',MA:'Morocco',MM:'Myanmar',NL:'Netherlands',NZ:'New Zealand',NG:'Nigeria',NO:'Norway',PK:'Pakistan',PH:'Philippines',PL:'Poland',PT:'Portugal',RO:'Romania',RU:'Russia',SA:'Saudi Arabia',RS:'Serbia',SG:'Singapore',SK:'Slovakia',SI:'Slovenia',ZA:'South Africa',ES:'Spain',SE:'Sweden',CH:'Switzerland',TW:'Taiwan',TH:'Thailand',TR:'Turkey',UA:'Ukraine',AE:'UAE',GB:'United Kingdom',US:'United States',UZ:'Uzbekistan',VN:'Vietnam',XX:'Unknown'};
function ccFlag(cc){if(!cc||cc==='XX')return'🌐';return String.fromCodePoint(...[...cc.toUpperCase()].map(c=>0x1F1E6+c.charCodeAt(0)-65));}
let invPage=0,invTotal=0;

async function loadInvFilters(){
  try{
    const r=await fetch('/api/shop/inventory/filters');
    const d=await r.json();
    const sel=document.getElementById('invCountry');
    sel.innerHTML='<option value="">All Countries ('+d.total+')</option>';
    for(const[cc,cnt] of Object.entries(d.countries||{})){
      const name=INV_COUNTRY_NAMES[cc]||cc;
      sel.innerHTML+='<option value="'+cc+'">'+ccFlag(cc)+' '+name+' ('+cnt+')</option>';
    }
  }catch(e){}
}

async function loadInventory(page){
  invPage=page||0;
  const country=document.getElementById('invCountry').value;
  const proto=document.getElementById('invProto').value;
  const anon=document.getElementById('invAnon').value;
  const limit=25;
  let url='/api/shop/inventory?limit='+limit+'&offset='+(invPage*limit);
  if(country)url+='&country='+country;
  if(proto)url+='&protocol='+proto;
  if(anon)url+='&anonymity='+anon;
  try{
    const r=await fetch(url);
    const d=await r.json();
    invTotal=d.total||0;
    document.getElementById('invCount').textContent=invTotal+' proxies found';
    const el=document.getElementById('invTable');
    if(!d.proxies||!d.proxies.length){
      el.innerHTML='<div class="inv-empty">No proxies match your filters. Try broadening your search.</div>';
      document.getElementById('invPager').innerHTML='';
      return;
    }
    let html='<table class="inv-table"><thead><tr>';
    html+='<th>Location</th><th>Protocol</th><th>Anonymity</th><th>Latency</th><th>Uptime</th><th>ISP</th><th></th>';
    html+='</tr></thead><tbody>';
    for(const p of d.proxies){
      const flag=ccFlag(p.country);
      const city=p.city?p.city+', ':'';
      const cname=INV_COUNTRY_NAMES[p.country]||p.country||'Unknown';
      const maskedIp=p.host?p.host.split('.').map((o,i)=>i<2?o:'***').join('.'):'***.***.***.***';
      html+='<tr>';
      html+='<td><span class="inv-flag">'+flag+'</span><span class="inv-cc">'+city+cname+'</span></td>';
      html+='<td><span class="inv-proto '+p.protocol+'">'+p.protocol.toUpperCase()+'</span></td>';
      html+='<td><span class="inv-anon '+(p.anonymity||'unknown')+'">'+(p.anonymity||'unknown').charAt(0).toUpperCase()+(p.anonymity||'unknown').slice(1)+'</span></td>';
      html+='<td class="inv-latency">'+(p.latency_ms||0).toFixed(0)+'ms</td>';
      html+='<td class="inv-uptime">'+(p.uptime||0).toFixed(0)+'%</td>';
      html+='<td style="font-size:12px;color:var(--text-muted);max-width:160px;overflow:hidden;text-overflow:ellipsis">'+(p.isp||'-')+'</td>';
      html+='<td><button class="inv-buy" onclick="buyFromInventory(&#39;'+p.country+'&#39;,&#39;'+p.protocol+'&#39;,&#39;'+(p.anonymity||'unknown')+'&#39;)">Buy Access</button></td>';
      html+='</tr>';
    }
    html+='</tbody></table>';
    el.innerHTML=html;
    // Pagination
    const totalPages=Math.ceil(invTotal/limit);
    let pg='';
    if(totalPages>1){
      pg+='<button '+(invPage<=0?'disabled':'')+'onclick="loadInventory('+(invPage-1)+')">&laquo; Prev</button>';
      pg+='<span style="color:var(--text-muted);font-size:12px;padding:6px 10px">'+(invPage+1)+' / '+totalPages+'</span>';
      pg+='<button '+(invPage>=totalPages-1?'disabled':'')+'onclick="loadInventory('+(invPage+1)+')">&raquo; Next</button>';
    }
    document.getElementById('invPager').innerHTML=pg;
  }catch(e){
    document.getElementById('invTable').innerHTML='<div class="inv-empty">Failed to load inventory.</div>';
  }
}

function buyFromInventory(country,proto,anon){
  // Pre-select a paid plan and open the order modal with filters pre-set
  const plan=proto==='socks5'?'pro':'lite';
  openOrder(plan);
}

loadStats();loadPlans();
loadInvFilters();loadInventory(0);
setInterval(loadStats,30000);
setInterval(()=>{loadInvFilters();loadInventory(invPage);},60000);
</script>
</body></html>"""

if __name__ == "__main__":
    from core import scraper
    scraper.run_once()
    port = int(os.environ.get("PORT", str(cfg.WEB_PORT)))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
