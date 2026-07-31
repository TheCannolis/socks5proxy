"""Production configuration for SOCKS5 Proxy Manager."""
import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

WEB_HOST = os.environ.get('SOCKS5_HOST', '127.0.0.1')
WEB_PORT = int(os.environ.get('SOCKS5_PORT', '8888'))
SHOP_PORT = int(os.environ.get('SOCKS5_SHOP_PORT', '8889'))
WEB_SECRET_KEY = os.environ.get('SOCKS5_SECRET_KEY', 'change-me-in-production-please')
WEB_USERNAME = os.environ.get('SOCKS5_ADMIN_USER', 'admin')
WEB_PASSWORD = os.environ.get('SOCKS5_ADMIN_PASS', 'admin')

SCRAPE_INTERVAL_MINUTES = int(os.environ.get('SOCKS5_INTERVAL', '60'))
CONCURRENCY = int(os.environ.get('SOCKS5_CONCURRENCY', '300'))
TIMEOUT_SECONDS = int(os.environ.get('SOCKS5_TIMEOUT', '8'))
TEST_URL = os.environ.get('SOCKS5_TEST_URL', 'http://httpbin.org/ip')
MAX_POOL_SIZE = int(os.environ.get('SOCKS5_MAX_POOL', '500'))
REMOVE_DEAD_AFTER_FAILS = 3

OUTPUT_DIR = BASE_DIR / 'proxy_pool'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_API_KEY = os.environ.get('SOCKS5_UPLOAD_KEY', 'change-me-upload-key')

# Email (SMTP)
SMTP_HOST = os.environ.get('SMTP_HOST', '')  # e.g. smtp.gmail.com
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')  # e.g. noreply@socks5proxy.shop
SMTP_PASS = os.environ.get('SMTP_PASS', '')  # App password or API key
SMTP_FROM = os.environ.get('SMTP_FROM', '')  # From address (defaults to SMTP_USER)
SMTP_TLS = os.environ.get('SMTP_TLS', 'true').lower() in ('true', '1', 'yes')

# Affiliate
AFFILIATE_URL = os.environ.get('AFFILIATE_URL', 'https://www.multilogin.com/')  # Anti-fingerprint browser affiliate link

SOURCES = {
    # ── SOCKS5 ──
    'proxyscrape_s5': 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all',
    'proxyscrape_gh_s5': 'https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main/proxies/all/socks5/data.txt',
    'monosans_s5': 'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt',
    'thespeedx_s5': 'https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt',
    'hookzof_s5': 'https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt',
    'mmpx12_s5': 'https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt',
    'jetkai_s5': 'https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt',
    'roosterkid_s5': 'https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt',
    'sunny9577_s5': 'https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/socks5_proxies.txt',
    'prxchk_s5': 'https://raw.githubusercontent.com/prxchk/proxy-list/main/socks5.txt',
    'zloi146_s5': 'https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks5.txt',
    'caliphdev_s5': 'https://raw.githubusercontent.com/caliphdev/proxy-list/master/socks5.txt',
    'officialputuid_s5': 'https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/socks5/socks5.txt',
    # ── SOCKS4 ──
    'proxyscrape_s4': 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=10000&country=all',
    'monosans_s4': 'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt',
    'thespeedx_s4': 'https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt',
    'prxchk_s4': 'https://raw.githubusercontent.com/prxchk/proxy-list/main/socks4.txt',
    'zloi146_s4': 'https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks4.txt',
    'sunny9577_s4': 'https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/socks4_proxies.txt',
    'officialputuid_s4': 'https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/socks4/socks4.txt',
    # ── HTTP / HTTPS ──
    'proxyscrape_http': 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all',
    'monosans_http': 'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
    'thespeedx_http': 'https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt',
    'prxchk_http': 'https://raw.githubusercontent.com/prxchk/proxy-list/main/http.txt',
    'prxchk_https': 'https://raw.githubusercontent.com/prxchk/proxy-list/main/https.txt',
    'zloi146_http': 'https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt',
    'zloi146_https': 'https://raw.githubusercontent.com/zloi-user/hideip.me/main/https.txt',
    'sunny9577_http': 'https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/generated/http_proxies.txt',
    'officialputuid_http': 'https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/http/http.txt',
    'officialputuid_https': 'https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/https/https.txt',
}

# Protocol probe order: try most specific first
PROTOCOL_PROBE_ORDER = ['socks5', 'socks4', 'https', 'http']

# Anonymity test endpoint (must return requesting headers as JSON)
ANONYMITY_TEST_URL = os.environ.get('SOCKS5_ANON_URL', 'http://httpbin.org/headers')

# Max proxies to anonymity-check per cycle (0 = unlimited)
ANON_CHECK_LIMIT = int(os.environ.get('SOCKS5_ANON_LIMIT', '0'))

WALLETCONNECT_PROJECT_ID = os.environ.get('WALLETCONNECT_PROJECT_ID', 'f3bc1958902c39cee9aef3130cde9814')
SHOP_BASE_URL = os.environ.get('SOCKS5_SHOP_URL', 'https://socks5proxy.shop')

RECEIVING_WALLETS = {
    'ethereum': os.environ.get('WALLET_ETH', '0x53E418e2A8F31F431Fe7ea8B691c6e7Dcdd07f9A'),
    'polygon':  os.environ.get('WALLET_POLYGON', '0x53E418e2A8F31F431Fe7ea8B691c6e7Dcdd07f9A'),
    'bsc':      os.environ.get('WALLET_BSC', '0x53E418e2A8F31F431Fe7ea8B691c6e7Dcdd07f9A'),
    'arbitrum': os.environ.get('WALLET_ARBITRUM', '0x53E418e2A8F31F431Fe7ea8B691c6e7Dcdd07f9A'),
    'solana':   os.environ.get('WALLET_SOLANA', 'HUwk24jpeM6tiqxB65V5oSTbh12MNqcSCT1gBnYt6GBJ'),
    'bitcoin':  os.environ.get('WALLET_BTC', 'bc1qq64q45l68tzmd42td2v7vmyzl3hfwpgmzenpzp'),
    'litecoin': os.environ.get('WALLET_LTC', 'LVmAhnGpP3YNffMVqUb3c3EPF5z4MDY9qb'),
}

SUPPORTED_CHAINS = {
    'ethereum': {
        'chain_id': 1, 'name': 'Ethereum', 'symbol': 'ETH', 'type': 'evm',
        'rpc': 'https://eth.llamarpc.com', 'explorer': 'https://etherscan.io',
        'tokens': {
            'ETH':  {'address': None, 'decimals': 18, 'coingecko': 'ethereum'},
            'USDT': {'address': '0xdAC17F958D2ee523a2206206994597C13D831ec7', 'decimals': 6, 'coingecko': 'tether'},
            'USDC': {'address': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', 'decimals': 6, 'coingecko': 'usd-coin'},
        },
    },
    'polygon': {
        'chain_id': 137, 'name': 'Polygon', 'symbol': 'MATIC', 'type': 'evm',
        'rpc': 'https://polygon-rpc.com', 'explorer': 'https://polygonscan.com',
        'tokens': {
            'MATIC': {'address': None, 'decimals': 18, 'coingecko': 'matic-network'},
            'USDT':  {'address': '0xc2132D05D31c914a87C6611C10748AEb04B58e8F', 'decimals': 6, 'coingecko': 'tether'},
            'USDC':  {'address': '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174', 'decimals': 6, 'coingecko': 'usd-coin'},
        },
    },
    'bsc': {
        'chain_id': 56, 'name': 'BNB Smart Chain', 'symbol': 'BNB', 'type': 'evm',
        'rpc': 'https://bsc-dataseed.binance.org', 'explorer': 'https://bscscan.com',
        'tokens': {
            'BNB':  {'address': None, 'decimals': 18, 'coingecko': 'binancecoin'},
            'USDT': {'address': '0x55d398326f99059fF775485246999027B3197955', 'decimals': 18, 'coingecko': 'tether'},
            'USDC': {'address': '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', 'decimals': 18, 'coingecko': 'usd-coin'},
        },
    },
    'arbitrum': {
        'chain_id': 42161, 'name': 'Arbitrum One', 'symbol': 'ETH', 'type': 'evm',
        'rpc': 'https://arb1.arbitrum.io/rpc', 'explorer': 'https://arbiscan.io',
        'tokens': {
            'ETH':  {'address': None, 'decimals': 18, 'coingecko': 'ethereum'},
            'USDT': {'address': '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9', 'decimals': 6, 'coingecko': 'tether'},
            'USDC': {'address': '0xaf88d065E77c8cC2239327C5EDb3A432268e5831', 'decimals': 6, 'coingecko': 'usd-coin'},
        },
    },
    'solana': {
        'chain_id': 'mainnet-beta', 'name': 'Solana', 'symbol': 'SOL', 'type': 'solana',
        'rpc': 'https://api.mainnet-beta.solana.com', 'explorer': 'https://solscan.io',
        'tokens': {
            'SOL':  {'address': None, 'decimals': 9, 'coingecko': 'solana'},
            'USDC': {'address': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', 'decimals': 6, 'coingecko': 'usd-coin'},
        },
    },
    'bitcoin': {
        'chain_id': 'btc', 'name': 'Bitcoin', 'symbol': 'BTC', 'type': 'utxo',
        'rpc': 'https://blockstream.info/api', 'explorer': 'https://blockstream.info',
        'tokens': {
            'BTC': {'address': None, 'decimals': 8, 'coingecko': 'bitcoin'},
        },
    },
    'litecoin': {
        'chain_id': 'ltc', 'name': 'Litecoin', 'symbol': 'LTC', 'type': 'utxo',
        'rpc': 'https://litecoinspace.org/api', 'explorer': 'https://litecoinspace.org',
        'tokens': {
            'LTC': {'address': None, 'decimals': 8, 'coingecko': 'litecoin'},
        },
    },

}

CONFIRMATIONS_REQUIRED = {'ethereum': 12, 'polygon': 64, 'bsc': 15, 'arbitrum': 12, 'solana': 32, 'bitcoin': 2, 'litecoin': 3}
