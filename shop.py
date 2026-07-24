"""Public SOCKS5 proxy shop — professional design, 3 tiers, Reown Pro, crypto payments."""
import json, logging, time
from dataclasses import asdict
from flask import Flask, render_template_string, request, jsonify
import config as cfg
from core import pool
from shop_backend import orders, PLANS
from wallet import (issue_nonce, build_siwe_message, verify_siwe, create_session,
                     get_session, revoke_session, create_payment, register_payment,
                     get_payment, check_payment, list_chains_for_client)

log = logging.getLogger('shop')
app = Flask(__name__)
app.secret_key = cfg.WEB_SECRET_KEY + '-shop'

SHOP_HTML = r"""<!doctype html>
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
  toast('Free proxy claimed!',null,'ok');
  showResult(d);
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

loadStats();loadPlans();
setInterval(loadStats,30000);
</script>
</body></html>"""

@app.route('/')
def home():
    html = SHOP_HTML.replace('__PID__', cfg.WALLETCONNECT_PROJECT_ID or 'demo-pid')
    html = html.replace('__CHAINS__', json.dumps(list_chains_for_client()))
    html = html.replace('__WALLETS__', json.dumps(cfg.RECEIVING_WALLETS))
    return render_template_string(html)

@app.route('/api/shop/stats')
def shop_stats():
    s = pool.stats()
    return jsonify({'alive': s['alive'], 'countries': len(s['countries']), 'avg_latency': s['avg_latency']})

@app.route('/api/shop/plans')
def shop_plans(): return jsonify(PLANS)

@app.route('/api/shop/countries')
def shop_countries(): return jsonify(pool.country_stats())

@app.route('/api/shop/free', methods=['POST'])
def shop_free():
    d = request.get_json(silent=True) or {}
    email = d.get('email', '').strip().lower()
    if '@' not in email:
        return jsonify({'error': 'valid email required'}), 400
    if not orders.can_claim_free(email):
        return jsonify({'error': 'this email has already claimed a free proxy. one per customer.'}), 400
    plan = PLANS.get('free')
    order = orders.create_order('free', email, [], 'free')
    if not order:
        return jsonify({'error': 'order creation failed'}), 500
    from core import pool
    assigned = pool.get_alive(None)[:1]
    order.proxies = [f'{p.host}:{p.port}' for p in assigned]
    order.status = 'active'
    order.paid_at = order.created_at
    from datetime import datetime, timedelta
    order.expires_at = (datetime.utcnow() + timedelta(days=plan['duration_days'])).isoformat()
    orders.save()
    orders.mark_free_claimed(email)
    return jsonify({
        'order_id': order.order_id,
        'proxies': order.proxies,
        'api_key': order.api_key,
        'status': 'active',
        'expires_at': order.expires_at,
    })

@app.route('/api/wallet/nonce')
def wallet_nonce(): return jsonify({'nonce': issue_nonce()})

@app.route('/api/wallet/siwe', methods=['POST'])
def wallet_siwe():
    d = request.get_json(silent=True) or {}
    msg = build_siwe_message(d.get('address',''), d.get('chain',''), d.get('nonce',''))
    return jsonify({'message': msg})

@app.route('/api/wallet/auth', methods=['POST'])
def wallet_auth():
    d = request.get_json(silent=True) or {}
    info = verify_siwe(d.get('message',''), d.get('signature',''))
    if not info: return jsonify({'error': 'invalid signature'}), 401
    token = create_session(info['address'], info['chain'])
    return jsonify({'token': token, 'address': info['address'], 'chain': info['chain']})

@app.route('/api/wallet/logout', methods=['POST'])
def wallet_logout():
    auth = request.headers.get('Authorization','').replace('Bearer ','')
    revoke_session(auth)
    return jsonify({'ok': True})

@app.route('/api/wallet/quote')
def wallet_quote():
    plan = request.args.get('plan','')
    chain = request.args.get('chain','')
    token = request.args.get('token','')
    pc = PLANS.get(plan)
    if not pc: return jsonify({'error': 'invalid plan'}), 400
    p = create_payment('QUOTE', pc['price_usd'], chain, token)
    if not p: return jsonify({'error': 'unsupported chain/token'}), 400
    return jsonify({'payment': asdict(p)})

@app.route('/api/shop/order', methods=['POST'])
def create_order():
    d = request.get_json(silent=True) or {}
    plan_id = d.get('plan','')
    email = d.get('email','').strip()
    countries = [c.strip().upper() for c in d.get('countries','').split(',') if c.strip()]
    chain = d.get('chain','')
    token = d.get('token','')
    if plan_id not in PLANS or '@' not in email:
        return jsonify({'error': 'invalid input'}), 400
    order = orders.create_order(plan_id, email, countries, chain or 'wc-manual')
    if not order: return jsonify({'error': 'order failed'}), 500
    out = {'order': {'order_id': order.order_id, 'email': order.email}}
    if chain and token:
        payment = create_payment(order.order_id, order.price_usd, chain, token)
        if payment:
            register_payment(payment)
            out['payment'] = asdict(payment)
    return jsonify(out)

@app.route('/api/wallet/check')
def wallet_check():
    pid = request.args.get('payment_id','')
    oid = request.args.get('order_id','')
    payment = get_payment(pid)
    if not payment: return jsonify({'paid': False, 'error': 'unknown payment'})
    if not payment.paid: check_payment(payment)
    if payment.paid and oid:
        o = orders.confirm_payment(oid, payment.tx_hash)
        if o: return jsonify({'paid': True, 'proxies': o.proxies, 'api_key': o.api_key, 'tx_hash': payment.tx_hash, 'order_id': o.order_id})
    return jsonify({'paid': False, 'expires_at': payment.expires_at, 'time_left': max(0, payment.expires_at - time.time())})

@app.route('/api/customer/order/<order_id>')
def customer_order(order_id):
    o = orders.get_order(order_id)
    if not o: return jsonify({'error': 'not found'}), 404
    return jsonify({'order_id': o.order_id, 'status': o.status, 'plan': o.plan_name, 'expires_at': o.expires_at, 'api_key': o.api_key, 'proxies': o.proxies})

def start_shop(host=None, port=None):
    app.run(host=host or cfg.WEB_HOST, port=port or cfg.SHOP_PORT, debug=False, threaded=True, use_reloader=False)
