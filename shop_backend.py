"""Shop backend: orders, plans — 3-tier (Free / Lite / Pro)."""
import json, uuid, secrets, logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional
import config as cfg

log = logging.getLogger('shop')
ORDERS_FILE = cfg.OUTPUT_DIR / 'orders.json'
FREE_EMAILS_FILE = cfg.OUTPUT_DIR / 'free_used.json'

PLANS = {
    'free': {
        'name': 'Free',
        'proxy_count': 1,
        'duration_days': 1,
        'price_usd': 0,
        'features': ['1 Proxy', '24h Access', 'Auto-refresh', 'Basic Countries'],
        'color': '#00ff41',
        'popular': False,
    },
    'lite': {
        'name': 'Lite',
        'proxy_count': 25,
        'duration_days': 30,
        'price_usd': 19.99,
        'features': ['25 Fresh Proxies', '30 Days', 'API Access', 'Country Select', 'Discord Support'],
        'color': '#00cc33',
        'popular': True,
    },
    'pro': {
        'name': 'Pro',
        'proxy_count': 999,
        'duration_days': 30,
        'price_usd': 49.99,
        'features': ['Unlimited Proxies', '30 Days', 'API Access', 'All Countries', 'Dedicated Pool', 'Priority Support', 'Early Access'],
        'color': '#00ff41',
        'popular': False,
    },
}

@dataclass
class Order:
    order_id: str; plan_id: str; plan_name: str; email: str
    countries: list[str]; proxy_count: int; price_usd: float
    crypto_method: str; status: str; api_key: str; proxies: list[str]
    created_at: str; paid_at: str = ''; expires_at: str = ''; tx_hash: str = ''

class OrderManager:
    def __init__(self):
        self.orders: dict[str, Order] = {}
        self.api_keys: dict[str, str] = {}
        self.free_emails: set = set()
        self._load()
        self._load_free()

    def _load(self):
        if ORDERS_FILE.exists():
            try:
                for o in json.loads(ORDERS_FILE.read_text()):
                    order = Order(**o)
                    self.orders[order.order_id] = order
                    if order.api_key: self.api_keys[order.api_key] = order.order_id
            except Exception: pass

    def _load_free(self):
        if FREE_EMAILS_FILE.exists():
            try: self.free_emails = set(json.loads(FREE_EMAILS_FILE.read_text()))
            except Exception: pass

    def _save_free(self):
        FREE_EMAILS_FILE.write_text(json.dumps(list(self.free_emails)))

    def can_claim_free(self, email: str) -> bool:
        return email.lower().strip() not in self.free_emails

    def mark_free_claimed(self, email: str):
        self.free_emails.add(email.lower().strip())
        self._save_free()

    def save(self):
        ORDERS_FILE.write_text(json.dumps([asdict(o) for o in self.orders.values()], indent=2))

    def create_order(self, plan_id, email, countries, crypto_method='') -> Optional[Order]:
        plan = PLANS.get(plan_id)
        if not plan: return None
        order = Order(
            order_id='ORD-' + uuid.uuid4().hex[:8].upper(),
            plan_id=plan_id, plan_name=plan['name'], email=email,
            countries=countries, proxy_count=plan['proxy_count'],
            price_usd=plan['price_usd'], crypto_method=crypto_method or 'manual',
            status='pending', api_key='sk_' + secrets.token_hex(24),
            proxies=[], created_at=datetime.utcnow().isoformat(),
        )
        self.orders[order.order_id] = order
        self.api_keys[order.api_key] = order.order_id
        self.save()
        return order

    def confirm_payment(self, order_id, tx_hash='') -> Optional[Order]:
        from core import pool
        order = self.orders.get(order_id)
        if not order: return None
        countries = order.countries if order.countries else None
        assigned = pool.get_alive(countries)[:order.proxy_count]
        order.proxies = [f'{p.host}:{p.port}' for p in assigned]
        order.status = 'active'
        order.paid_at = datetime.utcnow().isoformat()
        order.expires_at = (datetime.utcnow() + timedelta(days=PLANS[order.plan_id]['duration_days'])).isoformat()
        order.tx_hash = tx_hash
        self.save()
        return order

    def get_order(self, order_id) -> Optional[Order]:
        return self.orders.get(order_id)

    def get_all_orders(self) -> list[Order]:
        return sorted(self.orders.values(), key=lambda o: o.created_at, reverse=True)

    def stats(self):
        return {'total_orders': len(self.orders),
                'pending': sum(1 for o in self.orders.values() if o.status == 'pending'),
                'active': sum(1 for o in self.orders.values() if o.status == 'active'),
                'revenue_usd': round(sum(o.price_usd for o in self.orders.values() if o.status == 'active'), 2)}

orders = OrderManager()
