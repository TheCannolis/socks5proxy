"""Admin dashboard for SOCKS5 Proxy Manager."""
import json, logging, threading, time
from functools import wraps
from dataclasses import asdict
from flask import Flask, render_template_string, request, jsonify, send_file, redirect, session
import config as cfg
from core import pool

log = logging.getLogger('socks5web')
app = Flask(__name__)
app.secret_key = cfg.WEB_SECRET_KEY

def login_required(f):
    @wraps(f)
    def d(*a,**kw):
        if not session.get('logged_in'):
            if request.path.startswith('/api/'): return jsonify({'error':'unauthorized'}), 401
            return redirect('/login')
        return f(*a,**kw)
    return d

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username')==cfg.WEB_USERNAME and request.form.get('password')==cfg.WEB_PASSWORD:
            session['logged_in']=True; return redirect('/')
        return render_template_string(ADMIN_HTML, error='Bad credentials')
    return render_template_string(ADMIN_HTML, error='')

@app.route('/logout')
def logout():
    session.clear(); return redirect('/login')

@app.route('/')
@login_required
def index(): return render_template_string(ADMIN_HTML)

@app.route('/api/stats')
@login_required
def api_stats():
    from shop_backend import orders as om
    s = pool.stats()
    s['orders'] = om.stats()
    return jsonify(s)

@app.route('/api/proxies')
@login_required
def api_proxies():
    c = request.args.get('country','').strip().upper()
    limit = int(request.args.get('limit', 200))
    return jsonify([asdict(p) for p in pool.get_alive([c] if c else None, limit)])

@app.route('/api/download/<fmt>')
@login_required
def api_download(fmt):
    p = cfg.OUTPUT_DIR / f'socks5_ALL.{fmt}'
    if not p.exists(): return jsonify({'error':'not found'}), 404
    return send_file(p, as_attachment=True)

@app.route('/api/orders')
@login_required
def api_orders():
    from shop_backend import orders as om
    return jsonify([{'order_id': o.order_id, 'plan': o.plan_name, 'email': o.email,
                     'status': o.status, 'price': o.price_usd, 'created': o.created_at,
                     'api_key': o.api_key[:16]+'...' if o.api_key else ''} for o in om.get_all_orders()])

def start_web(host=None, port=None):
    app.run(host=host or cfg.WEB_HOST, port=port or cfg.WEB_PORT, debug=False, threaded=True, use_reloader=False)

ADMIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOCKS5 Manager — socks5proxy.shop</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#58a6ff;--green:#238636;--red:#da3633;--yellow:#d29922;--font:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:var(--font);font-size:14px}
a{color:var(--accent)}.wrap{display:flex;min-height:100vh}
.sidebar{width:220px;background:var(--card);border-right:1px solid var(--border);padding:20px 0;flex-shrink:0}
.sidebar h2{padding:0 20px;margin:0 0 20px;font-size:16px}
.nav-item{padding:12px 20px;cursor:pointer;color:var(--muted)}
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
.login-box{max-width:320px;margin:10vh auto;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:28px}
</style></head><body>
{% if error %}<script>alert('{{ error }}')</script>{% endif %}
<div class="wrap">
<div class="sidebar">
<h2>🧦 socks5proxy.shop</h2>
<div class="nav-item active" onclick="showPage('overview',this)">Overview</div>
<div class="nav-item" onclick="showPage('proxies',this)">Proxies</div>
<div class="nav-item" onclick="showPage('orders',this)">Orders</div>
<div class="nav-item" onclick="showPage('export',this)">Export</div>
<div style="margin-top:auto"><a href="/logout" class="nav-item">Sign Out</a></div>
</div>
<div class="main">
<div class="page active" id="page-overview">
  <h2>Overview</h2>
  <div class="stats" id="ovStats"></div>
</div>
<div class="page" id="page-proxies">
  <h2>Proxy List</h2>
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
    <p style="color:var(--muted)">Download alive proxies.</p>
    <div style="display:flex;gap:12px;margin-top:16px">
      <button class="btn btn-green" onclick="window.location='/api/download/txt'">TXT</button>
      <button class="btn btn-green" onclick="window.location='/api/download/json'">JSON</button>
    </div>
  </div>
</div>
</div></div>
<script>
function showPage(id,el){document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));document.getElementById('page-'+id).classList.add('active');document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));if(el)el.classList.add('active');if(id==='proxies')loadProxies();if(id==='orders')loadOrders();}
function flag(c){if(!c||c.length!==2)return'';return String.fromCodePoint(...[...c.toUpperCase()].map(x=>0x1F1E6+x.charCodeAt(0)-65));}
async function fetchStats(){const s=await(await fetch('/api/stats')).json();const el=document.getElementById('ovStats');el.innerHTML=`<div class="stat"><div class="sv">${(s.alive||0).toLocaleString()}</div><div class="ss">alive proxies</div></div><div class="stat"><div class="sv">${(s.countries||[]).length}</div><div class="ss">countries</div></div><div class="stat"><div class="sv">${s.avg_latency||0}ms</div><div class="ss">avg latency</div></div><div class="stat"><div class="sv">$${(s.orders?.revenue_usd||0).toFixed(2)}</div><div class="ss">revenue</div></div><div class="stat"><div class="sv">${s.orders?.total_orders||0}</div><div class="ss">total orders</div></div><div class="stat"><div class="sv">${s.orders?.active||0}</div><div class="ss">active subs</div></div>`;}
async function loadProxies(){const q=document.getElementById('pSearch').value.toLowerCase();const c=document.getElementById('pCountry').value.toUpperCase();const ps=await(await fetch('/api/proxies?limit=500&country='+encodeURIComponent(c))).json();const tb=document.getElementById('pBody');tb.innerHTML='';ps.filter(p=>!q||p.host.includes(q)||(p.country+' '+p.city+' '+p.isp).toLowerCase().includes(q)).slice(0,200).forEach(p=>{tb.innerHTML+=`<tr><td>${p.host}:${p.port}</td><td>${flag(p.country)} ${p.country}</td><td>${p.latency_ms}ms</td><td>${p.isp||'-'}</td></tr>`;});}
async function loadOrders(){const os=await(await fetch('/api/orders')).json();const tb=document.getElementById('oBody');tb.innerHTML='';os.forEach(o=>{tb.innerHTML+=`<tr><td>${o.order_id}</td><td>${o.plan}</td><td>${o.email}</td><td style="color:${o.status==='active'?'var(--green)':o.status==='pending'?'var(--yellow)':'var(--muted)'}">${o.status}</td><td>$${o.price}</td><td>${(o.created||'').split('T')[0]}</td></tr>`;});}
fetchStats();setInterval(fetchStats,15000);
</script></body></html>"""
