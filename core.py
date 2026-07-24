"""SOCKS5 proxy scraper, validator, and pool manager."""
import asyncio, json, logging, re, time
from dataclasses import dataclass, asdict
from datetime import datetime
import aiohttp, aiohttp_socks
import config as cfg

log = logging.getLogger('socks5core')

@dataclass
class Proxy:
    host: str; port: int; country: str = ''; country_name: str = ''
    city: str = ''; isp: str = ''; latency_ms: float = 0.0
    fails: int = 0; last_seen: float = 0.0
    def __hash__(self): return hash((self.host, self.port))
    def __eq__(self, other): return isinstance(other, Proxy) and (self.host, self.port) == (other.host, other.port)

class ProxyPool:
    def __init__(self):
        self.proxies: dict[tuple[str, int], Proxy] = {}

    def _proxy_url(self, p: Proxy) -> str:
        return f'socks5://{p.host}:{p.port}'

    def _extract(self, text: str) -> list[Proxy]:
        found = []
        for m in re.finditer(r'(?P<ip>\d{1,3}(?:\.\d{1,3}){3})[:\s]+(?P<port>\d{2,5})', text):
            host, port = m.group('ip'), int(m.group('port'))
            if 1 <= port <= 65535: found.append(Proxy(host=host, port=port))
        return found

    async def run_cycle(self, countries=None, progress_cb=None):
        raw = []
        async with aiohttp.ClientSession() as s:
            for name, url in cfg.SOURCES.items():
                try:
                    async with s.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
                        raw.extend(self._extract(await r.text()))
                except Exception as e:
                    log.warning(f'{name}: {e}')
        unique = list({(p.host, p.port): p for p in raw}.values())
        sem = asyncio.Semaphore(cfg.CONCURRENCY)
        async def check(p):
            async with sem:
                start = time.time()
                try:
                    conn = aiohttp_socks.ProxyConnector.from_url(self._proxy_url(p), rdns=True)
                    async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=cfg.TIMEOUT_SECONDS)) as s:
                        async with s.get(cfg.TEST_URL) as r:
                            await r.text()
                            p.latency_ms = round((time.time() - start) * 1000, 1)
                            p.last_seen = time.time()
                            return p
                except Exception:
                    return None
        async with aiohttp.ClientSession() as s:
            results = await asyncio.gather(*[check(p) for p in unique])
        alive = [p for p in results if p is not None]
        for p in alive: self.proxies[(p.host, p.port)] = p
        self.save_state(); self.export()
        return self.stats()

    def get_alive(self, countries=None, limit=0):
        now = time.time()
        items = [p for p in self.proxies.values() if now - p.last_seen < 3600 * 6]
        if countries: items = [p for p in items if p.country in countries]
        items.sort(key=lambda x: x.latency_ms)
        return items[:limit] if limit else items

    def country_stats(self):
        stats = {}
        for p in self.get_alive(): stats[p.country] = stats.get(p.country, 0) + 1
        return dict(sorted(stats.items(), key=lambda x: -x[1]))

    def stats(self):
        alive = self.get_alive()
        countries = {p.country for p in alive if p.country}
        lats = [p.latency_ms for p in alive if p.latency_ms > 0]
        return {'alive': len(alive), 'countries': sorted(countries),
                'country_counts': self.country_stats(),
                'avg_latency': round(sum(lats)/len(lats), 1) if lats else 0,
                'updated': datetime.utcnow().isoformat()}

    def save_state(self):
        (cfg.OUTPUT_DIR / 'pool_state.json').write_text(json.dumps([asdict(p) for p in self.proxies.values()], indent=2))

    def load_state(self):
        p = cfg.OUTPUT_DIR / 'pool_state.json'
        if p.exists():
            try:
                for item in json.loads(p.read_text()):
                    px = Proxy(**item); self.proxies[(px.host, px.port)] = px
            except Exception: pass

    def export(self):
        alive = self.get_alive()
        (cfg.OUTPUT_DIR / 'socks5_ALL.txt').write_text('\n'.join(f'{p.host}:{p.port}' for p in alive))
        (cfg.OUTPUT_DIR / 'socks5_ALL.json').write_text(json.dumps([asdict(p) for p in alive], indent=2))

pool = ProxyPool()
