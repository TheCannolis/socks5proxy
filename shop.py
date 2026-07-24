"""Public SOCKS5 proxy shop — Matrix theme, 3 tiers, Reown Pro, crypto payments."""
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
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOCKS5 Proxy Shop</title>
<style>
:root{--bg:#020602;--bg2:#060f06;--card:rgba(0,15,0,.7);--border:rgba(0,255,65,.15);--text:#c0d8c0;--muted:#4a7a4a;--green:#00ff41;--green2:#00cc33;--green3:#00991a;--red:#ff3344;--font:'Courier New',Courier,monospace;--sans:system-ui,-apple-system,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);overflow-x:hidden;min-height:100vh}
canvas#matrixBg{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;opacity:.12}
main{position:relative;z-index:1}

/* Header */
header{display:flex;align-items:center;justify-content:space-between;padding:16px 24px;background:var(--bg2);border-bottom:1px solid var(--border);backdrop-filter:blur(10px);position:sticky;top:0;z-index:100}
.logo{font-family:var(--font);font-size:20px;font-weight:700;color:var(--green);letter-spacing:2px}
.logo span{color:var(--muted)}
.stats-row{display:flex;gap:24px;font-size:13px;color:var(--muted)}
.stats-row b{color:var(--green)}
.wallet-wrap{display:flex;align-items:center;gap:10px}
.wallet-wrap .addr{font-family:var(--font);font-size:11px;color:var(--green);background:rgba(0,255,65,.08);padding:6px 12px;border-radius:4px;border:1px solid rgba(0,255,65,.2)}
.btn{font-family:var(--font);border:none;cursor:pointer;font-weight:700;font-size:13px;transition:all .2s}
.btn-g{background:var(--green2);color:#000;padding:10px 20px;border-radius:4px;text-transform:uppercase;letter-spacing:1px}
.btn-g:hover{background:var(--green);box-shadow:0 0 16px rgba(0,255,65,.3)}
.btn-o{background:transparent;border:1px solid var(--border);color:var(--green);padding:8px 14px;border-radius:4px;font-size:11px;text-transform:uppercase}
.btn-o:hover{border-color:var(--green)}

/* Hero */
.hero{padding:60px 24px 40px;text-align:center}
.hero h1{font-family:var(--font);font-size:42px;margin:0;color:var(--green);text-shadow:0 0 40px rgba(0,255,65,.3);letter-spacing:2px}
.hero p{color:var(--muted);font-size:15px;max-width:600px;margin:16px auto;line-height:1.6}
.hero .live-dot{display:inline-flex;align-items:center;gap:8px;background:rgba(0,255,65,.08);border:1px solid rgba(0,255,65,.2);padding:8px 18px;border-radius:20px;font-family:var(--font);font-size:12px;color:var(--green);margin-top:16px}
.hero .live-dot .dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

/* Plans */
.plans-section{padding:0 24px 60px}
.plans-grid{display:flex;justify-content:center;gap:20px;flex-wrap:wrap;max-width:1000px;margin:0 auto}
.plan-card{flex:1;min-width:260px;max-width:320px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:32px 24px;position:relative;backdrop-filter:blur(10px);transition:transform .3s,border-color .3s,box-shadow .3s}
.plan-card:hover{transform:translateY(-4px)}
.plan-card.popular{border-color:var(--green);box-shadow:0 0 30px rgba(0,255,65,.1)}
.plan-card.popular::before{content:'MOST POPULAR';position:absolute;top:-12px;left:50%;transform:translateX(-50%);background:var(--green2);color:#000;font-family:var(--font);font-size:10px;font-weight:700;padding:4px 14px;border-radius:3px;letter-spacing:1px}
.plan-card h3{font-family:var(--font);font-size:22px;margin:0 0 4px;letter-spacing:1px}
.plan-card .desc{color:var(--muted);font-size:12px;margin-bottom:20px}
.plan-card .price{font-family:var(--font);font-size:44px;font-weight:700;margin:12px 0;line-height:1}
.plan-card .price .usd{font-size:16px;color:var(--muted);font-weight:400;vertical-align:top;margin-right:2px}
.plan-card .price .per{display:block;font-size:11px;color:var(--muted);font-weight:400;margin-top:2px}
.plan-card ul{list-style:none;padding:0;margin:20px 0;font-size:12px;color:var(--muted)}
.plan-card ul li{padding:6px 0;border-bottom:1px solid rgba(0,255,65,.06)}
.plan-card ul li::before{content:'\25B8';color:var(--green);margin-right:8px}
.plan-card .btn{width:100%;display:block;text-align:center;padding:14px;border-radius:6px;font-size:14px}

/* Grid background */
.grid-overlay{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;opacity:.03;
  background-image:linear-gradient(rgba(0,255,65,.5) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,65,.5) 1px,transparent 1px);
  background-size:40px 40px}

/* Modal */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:200;display:none;align-items:center;justify-content:center;backdrop-filter:blur(4px)}
.modal-overlay.active{display:flex}
.modal{background:var(--bg2);border:1px solid var(--border);border-radius:16px;padding:32px;max-width:480px;width:90%;position:relative;max-height:85vh;overflow-y:auto}
.modal .close{position:absolute;top:12px;right:16px;background:none;border:none;color:var(--muted);font-size:24px;cursor:pointer}
.modal h3{font-family:var(--font);color:var(--green);margin:0 0 6px;letter-spacing:1px}
.modal .sub{color:var(--muted);font-size:12px;margin-bottom:20px}
.modal label{display:block;color:var(--muted);font-size:11px;margin-bottom:4px;text-transform:uppercase;letter-spacing:1px}
.modal input{width:100%;background:rgba(0,0,0,.6);border:1px solid var(--border);color:var(--green);font-family:var(--font);padding:10px 14px;border-radius:6px;font-size:14px;outline:none;margin-bottom:14px}
.modal input:focus{border-color:var(--green);box-shadow:0 0 8px rgba(0,255,65,.15)}
.modal select{width:100%;background:rgba(0,0,0,.6);border:1px solid var(--border);color:var(--green);font-family:var(--font);padding:10px 14px;border-radius:6px;font-size:14px;outline:none;margin-bottom:14px}
.modal .step{display:none}
.modal .step.active{display:block}

/* Payment methods */
.pay-methods{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}
.pay-method{flex:1;min-width:100px;background:rgba(0,0,0,.5);border:1px solid var(--border);border-radius:8px;padding:14px 10px;text-align:center;cursor:pointer;transition:all .2s;font-family:var(--font);font-size:12px}
.pay-method:hover{border-color:var(--green);background:rgba(0,255,65,.03)}
.pay-method.selected{border-color:var(--green);background:rgba(0,255,65,.08)}

/* Chain/token selectors */
.chain-grid{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.chain-chip{background:rgba(0,0,0,.5);border:1px solid var(--border);border-radius:20px;padding:6px 14px;font-family:var(--font);font-size:11px;cursor:pointer;transition:all .2s}
.chain-chip:hover,.chain-chip.selected{border-color:var(--green);color:var(--green);background:rgba(0,255,65,.06)}

/* Address display */
.pay-addr{background:rgba(0,0,0,.6);border:1px solid var(--border);padding:10px 14px;border-radius:6px;font-family:var(--font);font-size:11px;word-break:break-all;margin:8px 0;color:var(--green)}
.pay-addr.btc{border-color:rgba(247,147,26,.4);color:#f7931a}
.pay-addr.ltc{border-color:rgba(191,187,187,.4);color:#bfbbbb}

/* Proxy reveal */
.proxy-box{background:rgba(0,0,0,.6);border:1px solid rgba(0,255,65,.2);border-radius:8px;padding:16px;margin:12px 0;font-family:var(--font)}
.proxy-box .proxy-line{color:var(--green);font-size:13px;padding:3px 0}
.proxy-box .key{background:rgba(0,255,65,.08);padding:8px 12px;border-radius:4px;margin-top:10px;display:inline-block;font-size:11px;color:var(--green);word-break:break-all}

/* Toast */
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:500;background:var(--bg2);border:1px solid var(--border);color:var(--text);padding:12px 24px;border-radius:8px;font-family:var(--font);font-size:12px;display:none;backdrop-filter:blur(10px)}
.toast.err{border-color:var(--red);color:var(--red)}
.toast.ok{border-color:var(--green);color:var(--green)}

/* Spinner */
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--green);border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}

/* Promo section */
.promo-section{text-align:center;padding:40px 24px 60px}
.promo-section h3{font-family:var(--font);color:var(--green);letter-spacing:1px}
.crypto-badges{display:flex;justify-content:center;gap:16px;flex-wrap:wrap;margin-top:16px}
.crypto-badge{background:rgba(0,0,0,.5);border:1px solid var(--border);border-radius:8px;padding:12px 20px;font-family:var(--font);font-size:11px;color:var(--muted);display:flex;align-items:center;gap:8px}

/* Footer */
footer{text-align:center;padding:24px;border-top:1px solid var(--border);color:var(--muted);font-size:11px;font-family:var(--font)}

@media(max-width:768px){.hero h1{font-size:28px}.plans-grid{flex-direction:column;align-items:center}}
</style>
</head><body>
<canvas id="matrixBg"></canvas>
<div class="grid-overlay"></div>
<main>
<header>
  <div class="logo">SOCKS5<span>.SHOP</span></div>
  <div class="stats-row"><span>Proxies: <b id="sAlive">-</b></span><span>Countries: <b id="sCountries">-</b></span><span>Latency: <b id="sLatency">-</b></span></div>
  <div class="wallet-wrap" id="walletArea"><button class="btn btn-o" onclick="connectWallet()">Connect Wallet</button></div>
</header>

<section class="hero">
  <h1>SOCKS5 PROXY MARKET</h1>
  <p>Fresh, anonymous SOCKS5 proxies scraped in real-time. For scraping, pentesting, and privacy.</p>
  <div class="live-dot"><span class="dot"></span> LIVE — proxies refreshing every hour</div>
</section>

<section class="plans-section">
  <div class="plans-grid" id="planCards"></div>
</section>

<section class="promo-section">
  <h3>ACCEPTED PAYMENTS</h3>
  <p style="color:var(--muted);font-size:13px">WalletConnect · MetaMask · Trust · Coinbase Wallet · BTC · LTC · ETH · SOL · USDT · USDC</p>
  <div class="crypto-badges">
    <div class="crypto-badge">₿ Bitcoin</div>
    <div class="crypto-badge">Ł Litecoin</div>
    <div class="crypto-badge">⟠ Ethereum</div>
    <div class="crypto-badge">◎ Solana</div>
    <div class="crypto-badge">⬡ Polygon</div>
    <div class="crypto-badge">⬡ BSC</div>
    <div class="crypto-badge">⬡ Arbitrum</div>
  </div>
</section>

<footer>
  &copy; 2026 SOCKS5PROXY.SHOP — Encrypted · Anonymous · No Logs
</footer>
</main>

<!-- Modal -->
<div class="modal-overlay" id="orderModal">
<div class="modal">
  <button class="close" onclick="closeModal()">&times;</button>

  <!-- Step 1: Email -->
  <div class="step active" id="step1">
    <h3 id="mPlanTitle">Get Started</h3>
    <p class="sub" id="mPlanSub"></p>
    <label>Email</label>
    <input type="email" id="mEmail" placeholder="you@example.com">
    <label>Countries (optional, comma-separated)</label>
    <input id="mCountries" placeholder="US,DE,JP">
    <button class="btn btn-g" style="width:100%;margin-bottom:8px" onclick="handleCheckout()">Continue</button>
    <div id="freeStatus" style="text-align:center;margin-top:8px"></div>
  </div>

  <!-- Step 2: Payment method -->
  <div class="step" id="step2">
    <h3>Choose Payment</h3>
    <p class="sub">Select how you want to pay</p>
    <div class="pay-methods" id="payMethods"></div>
    <div id="chainSelect" class="chain-grid" style="display:none"></div>
    <div class="chain-grid" id="tokenChips" style="display:none"></div>
    <div id="payQuote" style="margin:12px 0;font-family:var(--font);font-size:13px;display:none"></div>
    <button class="btn btn-g" style="width:100%;margin-top:8px" onclick="initPayment()">Pay Now</button>
    <button class="btn btn-o" style="width:100%;margin-top:8px" onclick="goStep(1)">Back</button>
  </div>

  <!-- Step 3: Send payment -->
  <div class="step" id="step3">
    <h3>Send Payment</h3>
    <div id="payInfo"></div>
    <p id="payStatus" style="color:var(--muted)"><span class="spinner"></span> Waiting for payment...</p>
    <button class="btn btn-o" style="margin-top:8px" onclick="checkPayManually()">I already paid — check now</button>
  </div>

  <!-- Step 4: Success -->
  <div class="step" id="step4">
    <h3>Active</h3>
    <p>Order: <b id="mOrderId" style="color:var(--green)"></b></p>
    <p style="color:var(--muted);font-size:12px">Your proxies are live. Save your API key.</p>
    <div id="mProxies"></div>
    <button class="btn btn-g" style="width:100%" onclick="closeModal()">Done</button>
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

function toast(m,err,ok){const t=document.getElementById('toast');t.textContent=m;t.className='toast'+(err?' err':ok?' ok':'');t.style.display='block';setTimeout(()=>t.style.display='none',4000);}
function shortAddr(a){return a.slice(0,6)+'...'+a.slice(-4);}

async function loadStats(){
  try{const s=await(await fetch('/api/shop/stats')).json();
  document.getElementById('sAlive').textContent=s.alive.toLocaleString();
  document.getElementById('sCountries').textContent=s.countries;
  document.getElementById('sLatency').textContent=s.avg_latency+'ms';}catch(e){}
}

async function loadPlans(){
  const plans=await(await fetch('/api/shop/plans')).json();
  window._plansCache=plans;
  const el=document.getElementById('planCards');el.innerHTML='';
  const order=['free','lite','pro'];
  for(const id of order){
    const p=plans[id];if(!p)continue;
    const freeTag = p.price_usd===0 ? '<span class="per">no credit card</span>' : '';
    el.innerHTML+=
`<div class="plan-card ${p.popular?'popular':''}">
  <h3 style="color:${p.color}">${p.name.toUpperCase()}</h3>
  <div class="desc">${p.price_usd===0?'1 free proxy for testing':'SOCKS5 proxies · ${p.duration_days} days'}</div>
  <div class="price"><span class="usd">$</span>${p.price_usd===0?'0':p.price_usd}<span class="per">${p.price_usd===0?'free forever':'/mo'}</span>${freeTag}</div>
  <ul>${p.features.map(f=>'<li>'+f+'</li>').join('')}</ul>
  <button class="btn ${p.price_usd===0?'btn-o':'btn-g'}" style="color:${p.price_usd===0?p.color:''}" onclick="openOrder('${id}')">${p.price_usd===0?'GET FREE':'BUY '+p.name.toUpperCase()}</button>
</div>`;
  }
}

async function connectWallet(){
  if(!PROJECT_ID||PROJECT_ID==='demo-pid'){toast('WalletConnect not configured — use BTC/LTC',true);return;}
  if(!window.AppKit)try{await new Promise(r=>setTimeout(r,2000));}catch(e){}
  if(!window.AppKit){toast('SDK loading... retry in 3s',true);return;}
  try{
    const evmIds=CHAINS.filter(c=>c.type!=='utxo'&&typeof c.chain_id==='number').map(c=>c.chain_id);
    window._appkit=window.AppKit.createAppKit({
      projectId:PROJECT_ID,
      networks:evmIds.length?evmIds:[1],
      metadata:{name:'SOCKS5 Proxy Shop',description:'Premium SOCKS5 Proxies',url:window.location.origin,icons:[],email:'admin@socks5proxy.shop'},
      features:{email:true,socials:['google','x','discord','github']}
    });
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
    document.getElementById('walletArea').innerHTML='<span class="addr">&#9679; '+shortAddr(walletAddress)+'</span> <button class="btn btn-o" onclick="disconnect()">Disconnect</button>';
    toast('Connected','','ok');
  }catch(e){toast('Sign-in failed: '+e.message,true);}
}

function disconnect(){walletConnected=false;walletAddress='';walletChain='';sessionToken='';
  document.getElementById('walletArea').innerHTML='<button class="btn btn-o" onclick="connectWallet()">Connect Wallet</button>';}

function openOrder(id){
  selectedPlan=id;isUtxoOrder=false;isFreeTier=false;selectedChain=null;selectedToken=null;currentPayment=null;currentOrder=null;
  const p=window._plansCache?.[id];if(!p)return;
  document.getElementById('mPlanTitle').textContent=p.name+' Plan';
  document.getElementById('mPlanSub').textContent=p.price_usd===0?'1 free proxy for 24 hours. No payment required.':p.proxy_count+' proxies · '+p.duration_days+' days · $'+p.price_usd+' USD';
  document.getElementById('freeStatus').innerHTML='';
  goStep(1);
  if(p.price_usd===0){showFreeOption();}
  document.getElementById('orderModal').classList.add('active');
}

function showFreeOption(){
  document.getElementById('freeStatus').innerHTML='<span style="color:var(--green);font-size:12px">No payment needed. Just enter your email and click Claim.</span>';
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
  if(p&&p.price_usd===0){
    await claimFree(email,countries);
    return;
  }
  // Paid plan: show payment options
  goStep(2);
  renderPaymentMethods();
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
  // WalletConnect
  el.innerHTML+='<div class="pay-method selected" id="pm-wc" onclick="selectPayMethod(\'wc\')">WalletConnect<br><span style="font-size:10px;color:var(--muted)">ETH · SOL · USDT</span></div>';
  // BTC
  el.innerHTML+='<div class="pay-method" id="pm-btc" onclick="selectPayMethod(\'btc\')">Bitcoin<br><span style="font-size:10px;color:var(--muted)">BTC</span></div>';
  // LTC
  el.innerHTML+='<div class="pay-method" id="pm-ltc" onclick="selectPayMethod(\'ltc\')">Litecoin<br><span style="font-size:10px;color:var(--muted)">LTC</span></div>';
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
  wcChains.forEach(c=>{el.innerHTML+='<div class="chain-chip" id="ch-'+c.id+'" onclick="selChain(\''+c.id+'\')">'+c.name+'</div>';});
  if(wcChains.length)selChain(wcChains[0].id);
}

function selChain(id){
  selectedChain=id;isUtxoOrder=false;
  document.querySelectorAll('#chainSelect .chain-chip').forEach(el=>el.classList.remove('selected'));
  document.getElementById('ch-'+id).classList.add('selected');
  const c=CHAINS.find(x=>x.id===id);
  const tl=document.getElementById('tokenChips');tl.innerHTML='';
  c.tokens.forEach(t=>{tl.innerHTML+='<div class="chain-chip" id="tk-'+t.symbol+'" onclick="selToken(\''+t.symbol+'\')">'+t.symbol+'</div>';});
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
    if(d.error){q.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';currentPayment=null;return;}
    currentPayment=d.payment;
    const cn=CHAINS.find(c=>c.id===chain)?.name||chain;
    q.innerHTML='<span style="color:var(--green)">'+d.payment.amount_human+' '+token+'</span><br><span style="font-size:11px;color:var(--muted)">on '+cn+' ≈ $'+d.payment.amount_usd+' USD</span>';
  }catch(e){q.innerHTML='<span style="color:var(--red)">Quote failed</span>';}
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
  const label=isUtxoOrder?(selectedChain==='bitcoin'?'₿ Bitcoin':'Ł Litecoin'):(selectedToken+' on '+c?.name);
  const addrClass=selectedChain==='bitcoin'?'btc':selectedChain==='litecoin'?'ltc':'';
  document.getElementById('payInfo').innerHTML=
    '<p><b>Order:</b> <span style="color:var(--green)">'+d.order.order_id+'</span></p>'+
    '<p><b>Amount:</b> '+d.payment.amount_human+' '+selectedToken+' ≈ $'+d.payment.amount_usd+'</p>'+
    '<p><b>Send to:</b></p><div class="pay-addr '+addrClass+'">'+d.payment.receiver+'</div>'+
    (c?'<p style="font-size:11px"><a style="color:var(--green)" target="_blank" href="'+c.explorer+'/address/'+d.payment.receiver+'">View on explorer →</a></p>':'')+
    '<p style="font-size:11px;color:var(--muted)">Send the exact amount. Confirmation may take a few minutes.</p>';
  goStep(3);
  pollPayment();
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
    else{ps.innerHTML='<span style="color:#f0c040">Waiting for confirmation...</span>';setTimeout(()=>pollPayment(false),10000);}
  }catch(e){ps.innerHTML='<span style="color:var(--red)">Check failed, retrying...</span>';setTimeout(()=>pollPayment(false),10000);}
}

function showResult(d){
  currentOrder=d;goStep(4);
  document.getElementById('mOrderId').textContent=d.order_id||currentOrder?.order_id||'';
  const html=d.proxies?d.proxies.map(p=>'<div class="proxy-line">'+p+'</div>').join(''):'<div class="proxy-line" style="color:var(--muted)">Proxy assigned</div>';
  document.getElementById('mProxies').innerHTML=
    '<div class="proxy-box">'+html+'</div>'+
    '<div class="key">API Key: <span style="color:var(--green)">'+(d.api_key||currentOrder?.api_key||'')+'</span></div>';
}

// Matrix rain
(function(){
  const c=document.getElementById('matrixBg'),ctx=c.getContext('2d');
  let w,h,chars='アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789ABCDEF'.split('');
  let drops=[];
  function resize(){w=c.width=window.innerWidth;h=c.height=window.innerHeight;drops=Array(Math.floor(w/24)).fill(0).map(()=>Math.random()*h);}
  resize();window.addEventListener('resize',resize);
  function draw(){
    ctx.fillStyle='rgba(2,6,2,.15)';ctx.fillRect(0,0,w,h);
    ctx.fillStyle='#00ff41';ctx.font='16px monospace';
    for(let i=0;i<drops.length;i++){
      const ch=chars[Math.floor(Math.random()*chars.length)];
      ctx.fillText(ch,i*24,drops[i]);
      if(drops[i]>h&&Math.random()>.975)drops[i]=0;
      drops[i]+=16;
    }
  }
  setInterval(draw,80);
})();

loadStats();loadPlans();
setInterval(loadStats,30000);
</script></body></html>"""

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
