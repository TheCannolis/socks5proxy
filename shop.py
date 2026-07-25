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
  el.innerHTML='<div style="text-align:center;padding:20px 0"><span class="spinner"></span> Detecting your IP...</div>';
  try{
    // Server-side IP detection
    const sr=await fetch('/api/tools/myip');
    const sd=await sr.json();
    const ip=sd.ip||'unknown';
    // Geo lookup via ip-api
    let geo={country:'',countryCode:'',city:'',zip:'',isp:'',org:'',as:'',proxy:false,hosting:false};
    try{
      const gr=await fetch('http://ip-api.com/json/'+ip+'?fields=status,country,countryCode,city,zip,isp,org,as,proxy,hosting,query');
      geo=await gr.json();
    }catch(e){}
    // WebRTC leak check
    let webrtcIPs=[];
    try{webrtcIPs=await detectWebRTC();}catch(e){}
    const rtcLeak=webrtcIPs.filter(x=>x!==ip&&!x.startsWith('192.168.')&&!x.startsWith('10.')&&!x.startsWith('172.'));
    // Country flag emoji
    const flag=geo.countryCode?String.fromCodePoint(...[...geo.countryCode.toUpperCase()].map(c=>0x1F1E6+c.charCodeAt(0)-65)):'';
    const proxyDetected=geo.proxy||geo.hosting;
    el.innerHTML=
      '<div class="tr-flag">'+flag+'</div>'+
      '<div class="tr-ip">'+ip+'</div>'+
      '<div class="tr-loc">'+(geo.city||'')+(geo.city&&geo.country?', ':'')+
      (geo.country||'')+(geo.zip?' '+geo.zip:'')+'</div>'+
      '<div class="tr-row"><span class="tr-label">ISP</span><span class="tr-val">'+(geo.isp||'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">Organization</span><span class="tr-val">'+(geo.org||'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">ASN</span><span class="tr-val">'+(geo.as||'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">ZIP Code</span><span class="tr-val">'+(geo.zip||'N/A')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">Proxy / VPN</span><span class="tr-val '+(proxyDetected?'good':'bad')+'">'+(proxyDetected?'Detected':'Not Detected')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">Hosting / DC</span><span class="tr-val '+(geo.hosting?'good':'warn')+'">'+(geo.hosting?'Yes':'No')+'</span></div>'+
      '<div class="tr-row"><span class="tr-label">WebRTC Leak</span><span class="tr-val '+(rtcLeak.length?'bad':'good')+'">'+(rtcLeak.length?rtcLeak.join(', '):'None')+'</span></div>';
  }catch(e){
    el.innerHTML='<div style="color:var(--error);text-align:center;padding:12px">Failed: '+e.message+'</div>';
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
}

async function hashStr(s){
  const buf=new TextEncoder().encode(s);
  const hb=await crypto.subtle.digest('SHA-256',buf);
  return Array.from(new Uint8Array(hb)).map(b=>b.toString(16).padStart(2,'0')).join('');
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
    from emailer import send_free_order
    send_free_order(email, order.order_id, order.proxies, order.expires_at)
    return jsonify({
        'order_id': order.order_id,
        'status': 'active',
        'expires_at': order.expires_at,
        'email_sent': True,
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
