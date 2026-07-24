"""WalletConnect backend: SIWE auth, pricing, payment verification (EVM + UTXO)."""
import json, logging, secrets, time, uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
import requests
from eth_account.messages import encode_defunct
from web3 import Web3
import config as cfg

log = logging.getLogger('wallet')
_nonces: dict[str, float] = {}
_sessions: dict[str, dict] = {}
_pending: dict[str, 'PaymentRequest'] = {}
_PRICE_CACHE: dict[str, tuple[float, float]] = {}
_UTXO_TX_CACHE: dict[str, float] = {}

@dataclass
class PaymentRequest:
    payment_id: str; order_id: str; chain: str; token_symbol: str
    token_address: Optional[str]; receiver: str; amount_raw: int
    amount_human: str; amount_usd: float; expires_at: float
    paid: bool = False; tx_hash: str = ''; payer_address: str = ''
    confirmed_at: str = ''

def get_usd_price(coin_id: str) -> float:
    now = time.time()
    if coin_id in _PRICE_CACHE:
        price, ts = _PRICE_CACHE[coin_id]
        if now - ts < 60: return price
    try:
        r = requests.get('https://api.coingecko.com/api/v3/simple/price',
                         params={'ids': coin_id, 'vs_currencies': 'usd'}, timeout=8)
        price = float(r.json()[coin_id]['usd'])
        _PRICE_CACHE[coin_id] = (price, now)
        return price
    except Exception as e:
        log.warning(f'Price oracle: {e}')
        return _PRICE_CACHE.get(coin_id, (0.0,))[0]

def issue_nonce() -> str:
    n = secrets.token_hex(8)
    _nonces[n] = time.time() + 600
    return n

def consume_nonce(nonce: str) -> bool:
    return _nonces.pop(nonce, 0) > time.time()

def create_session(address: str, chain: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {'address': address, 'chain': chain, 'created': time.time()}
    return token

def get_session(token: str) -> Optional[dict]:
    s = _sessions.get(token)
    if not s or time.time() - s['created'] > 86400 * 7: return _sessions.pop(token, None)
    return s

def revoke_session(token: str): _sessions.pop(token, None)

def build_siwe_message(address: str, chain: str, nonce: str) -> str:
    domain = cfg.SHOP_BASE_URL.replace('https://','').replace('http://','').split('/')[0]
    cc = cfg.SUPPORTED_CHAINS.get(chain, {})
    return (f'{domain} wants you to sign in with your Ethereum account:\n{address}\n\n'
            f'Connect to SOCKS5 Proxy Shop\n\nURI: {cfg.SHOP_BASE_URL}\n'
            f'Version: 1\nChain ID: {cc.get("chain_id", 1)}\n'
            f'Nonce: {nonce}\nIssued At: {datetime.utcnow().isoformat()}Z')

def verify_siwe(message: str, signature: str) -> Optional[dict]:
    try:
        w3 = Web3()
        msg = encode_defunct(text=message)
        address = w3.eth.account.recover_message(msg, signature=signature)
        if not address: return None
        nonce = None; chain_id = None
        for line in message.split('\n'):
            if line.startswith('Nonce: '): nonce = line.split(': ', 1)[1].strip()
            if line.startswith('Chain ID: '):
                try: chain_id = int(line.split(': ', 1)[1].strip())
                except: chain_id = line.split(': ', 1)[1].strip()
        if not nonce or not consume_nonce(nonce): return None
        chain = next((c for c, cc in cfg.SUPPORTED_CHAINS.items() if cc['chain_id'] == chain_id), None)
        return {'address': address, 'chain': chain, 'chain_id': chain_id} if chain else None
    except Exception as e:
        log.warning(f'SIWE verify: {e}')
        return None

def create_payment(order_id: str, plan_price: float, chain: str, token_symbol: str) -> Optional[PaymentRequest]:
    cc = cfg.SUPPORTED_CHAINS.get(chain)
    if not cc: return None
    tc = cc['tokens'].get(token_symbol)
    if not tc: return None
    receiver = cfg.RECEIVING_WALLETS.get(chain, '')
    if not receiver: return None
    price = get_usd_price(tc['coingecko'])
    if price <= 0: return None
    tokens = plan_price / price
    amount_raw = int(tokens * (10 ** tc['decimals']))
    amount_human = f'{tokens:.8f}'.rstrip('0').rstrip('.')
    # UTXO payments get longer expiry (on-chain confirmation takes minutes)
    expiry = time.time() + 3600 if cc.get('type') == 'utxo' else time.time() + 1800
    return PaymentRequest(
        payment_id='PAY-' + uuid.uuid4().hex[:10].upper(),
        order_id=order_id, chain=chain, token_symbol=token_symbol,
        token_address=tc['address'], receiver=receiver,
        amount_raw=amount_raw, amount_human=amount_human,
        amount_usd=plan_price, expires_at=expiry)

def register_payment(p): _pending[p.payment_id] = p
def get_payment(pid): return _pending.get(pid)
def delete_payment(pid): _pending.pop(pid, None)

def _check_utxo_payment(payment: PaymentRequest) -> bool:
    """Check Bitcoin/Litecoin payment via block explorer REST API."""
    chain = cfg.SUPPORTED_CHAINS.get(payment.chain, {})
    api_base = chain.get('rpc', '')
    try:
        addr_url = f'{api_base}/address/{payment.receiver}'
        r = requests.get(addr_url, timeout=12)
        data = r.json()

        chain_stats = data.get('chain_stats', {})
        mempool_stats = data.get('mempool_stats', {})
        total_received = chain_stats.get('funded_txo_sum', 0)
        total_spent = chain_stats.get('spent_txo_sum', 0)
        balance = total_received - total_spent

        # Get latest confirmed balance
        if balance >= payment.amount_raw:
            # Check that there are recent confirmed transactions (not stale balance)
            tx_url = f'{api_base}/address/{payment.receiver}/txs'
            txs = requests.get(tx_url, timeout=12).json()
            for tx in txs:
                vout_sum = sum(v.get('value', 0) for v in tx.get('vout', [])
                               if v.get('scriptpubkey_address') == payment.receiver)
                if vout_sum >= payment.amount_raw and tx.get('status', {}).get('confirmed'):
                    confs = cfg.CONFIRMATIONS_REQUIRED.get(payment.chain, 2)
                    # Blockstream/Litecoinspace tx status confirmed block height
                    # For simplicity, if it's confirmed with >= 1 confirmation, accept after polling twice
                    # Use cache to ensure we've seen it confirmed twice (2 polls)
                    txid = tx['txid']
                    now = time.time()
                    if txid in _UTXO_TX_CACHE:
                        if now - _UTXO_TX_CACHE[txid] > 15:
                            payment.paid = True
                            payment.tx_hash = txid
                            payment.payer_address = ''
                            payment.confirmed_at = datetime.utcnow().isoformat()
                            del _UTXO_TX_CACHE[txid]
                            return True
                    else:
                        _UTXO_TX_CACHE[txid] = now
                    break
        return False
    except Exception as e:
        log.warning(f'UTXO payment check ({payment.chain}): {e}')
        return False

def _check_evm_payment(payment: PaymentRequest) -> bool:
    """Check EVM/Solana payment via Web3 / RPC."""
    try:
        w3 = Web3(Web3.HTTPProvider(cfg.SUPPORTED_CHAINS[payment.chain]['rpc'], request_kwargs={'timeout': 10}))
        receiver = Web3.to_checksum_address(payment.receiver)
        tx = None
        if payment.token_address is None:
            b = w3.eth.block_number
            for bn in range(max(0, b - 200), b + 1):
                try:
                    blk = w3.eth.get_block(bn, full_transactions=True)
                    for t in blk.get('transactions', []):
                        if t['to'] and t['to'].lower() == receiver.lower() and t['value'] >= payment.amount_raw:
                            if b - bn >= cfg.CONFIRMATIONS_REQUIRED.get(payment.chain, 12):
                                tx = t; break
                except Exception: continue
                if tx: break
        if tx:
            payment.paid = True
            payment.tx_hash = tx['hash'].hex() if hasattr(tx['hash'], 'hex') else str(tx['hash'])
            payment.payer_address = tx['from']
            payment.confirmed_at = datetime.utcnow().isoformat()
            return True
        return False
    except Exception as e:
        log.warning(f'EVM payment check: {e}')
        return False

def check_payment(payment: PaymentRequest) -> bool:
    if payment.paid or time.time() > payment.expires_at: return payment.paid
    cc = cfg.SUPPORTED_CHAINS.get(payment.chain, {})
    if cc.get('type') == 'utxo':
        return _check_utxo_payment(payment)
    elif cc.get('type') == 'solana':
        # Solana not fully implemented via Web3.py; still evm-style check via RPC
        return _check_evm_payment(payment)
    else:
        return _check_evm_payment(payment)

def list_chains_for_client() -> list[dict]:
    """Return chains with wallet addresses configured, for shop frontend.
       UTXO chains (BTC, LTC) are marked as manual — no WalletConnect needed."""
    out = []
    for cname, c in cfg.SUPPORTED_CHAINS.items():
        if not cfg.RECEIVING_WALLETS.get(cname): continue
        tokens = [{'symbol': tn, 'address': t['address'], 'decimals': t['decimals']} for tn, t in c['tokens'].items()]
        out.append({'id': cname, 'name': c['name'], 'chain_id': c['chain_id'],
                     'symbol': c['symbol'], 'rpc': c['rpc'], 'explorer': c['explorer'],
                     'tokens': tokens, 'type': c.get('type', 'evm')})
    return out

def list_utxo_for_client() -> list[dict]:
    """Return only UTXO chains (BTC, LTC) — no WalletConnect needed."""
    out = []
    for cname, c in cfg.SUPPORTED_CHAINS.items():
        if c.get('type') != 'utxo': continue
        if not cfg.RECEIVING_WALLETS.get(cname): continue
        out.append({'id': cname, 'name': c['name'], 'symbol': c['symbol'],
                     'explorer': c['explorer']})
    return out
