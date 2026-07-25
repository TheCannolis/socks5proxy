"""SOCKS5 proxy scraper, validator, and pool manager with full metadata."""
import asyncio, json, logging, re, time
from dataclasses import dataclass, asdict, field
from datetime import datetime
import aiohttp, aiohttp_socks
import config as cfg

log = logging.getLogger('socks5core')

GEO_BATCH_API = 'http://ip-api.com/batch?fields=status,query,country,countryCode,city,zip,isp,as,org'

@dataclass
class Proxy:
    host: str
    port: int
    protocol: str = 'socks5'
    country: str = ''
    country_name: str = ''
    city: str = ''
    zipcode: str = ''
    isp: str = ''
    org: str = ''
    asn: str = ''
    anonymity: str = ''
    latency_ms: float = 0.0
    uptime: float = 0.0
    checks: int = 0
    successes: int = 0
    fails: int = 0
    last_seen: float = 0.0
    first_seen: float = 0.0

    def __hash__(self): return hash((self.host, self.port))
    def __eq__(self, other): return isinstance(other, Proxy) and (self.host, self.port) == (other.host, other.port)


def detect_protocol(source_name: str) -> str:
    s = source_name.lower()
    if 'socks5' in s or 's5' in s: return 'socks5'
    if 'socks4' in s or 's4' in s: return 'socks4'
    if 'https' in s: return 'https'
    if 'http' in s: return 'http'
    return 'socks5'


class ProxyPool:
    def __init__(self):
        self.proxies: dict[tuple[str, int], Proxy] = {}

    def _proxy_url(self, p: Proxy) -> str:
        proto = p.protocol if p.protocol in ('socks5', 'socks4', 'http', 'https') else 'socks5'
        return f'{proto}://{p.host}:{p.port}'

    def _extract(self, text: str, source: str = '') -> list[Proxy]:
        proto = detect_protocol(source) if source else 'socks5'
        found = []
        for m in re.finditer(r'(?P<ip>\d{1,3}(?:\.\d{1,3}){3})[:\s]+(?P<port>\d{2,5})', text):
            host, port = m.group('ip'), int(m.group('port'))
            if 1 <= port <= 65535:
                found.append(Proxy(host=host, port=port, protocol=proto))
        return found

    async def _check_anonymity(self, session: aiohttp.ClientSession, p: Proxy) -> str:
        """Detect anonymity level by checking what headers the proxy leaks."""
        try:
            test_url = 'http://httpbin.org/headers'
            if p.protocol in ('socks5', 'socks4'):
                conn = aiohttp_socks.ProxyConnector.from_url(self._proxy_url(p), rdns=True)
            else:
                conn = aiohttp.TCPConnector()
            async with aiohttp.ClientSession(connector=conn,
                    timeout=aiohttp.ClientTimeout(total=cfg.TIMEOUT_SECONDS)) as s:
                kw = {}
                if p.protocol in ('http', 'https'):
                    kw['proxy'] = self._proxy_url(p)
                async with s.get(test_url, **kw) as r:
                    data = await r.json()
                    headers = {k.lower(): v for k, v in data.get('headers', {}).items()}
                    has_via = 'via' in headers or 'x-via' in headers
                    has_forward = ('x-forwarded-for' in headers or
                                   'x-real-ip' in headers or
                                   'forwarded' in headers)
                    if not has_via and not has_forward:
                        return 'elite'
                    elif has_forward and not has_via:
                        return 'anonymous'
                    else:
                        return 'transparent'
        except Exception:
            return 'unknown'

    async def _geo_enrich(self, proxies: list[Proxy]):
        """Batch geo-lookup using ip-api.com (free, 100 per batch, 45 req/min)."""
        need_geo = [p for p in proxies if not p.country]
        if not need_geo:
            return
        log.info(f'Geo-enriching {len(need_geo)} proxies...')
        async with aiohttp.ClientSession() as s:
            batches = [need_geo[i:i+100] for i in range(0, len(need_geo), 100)]
            for batch in batches:
                ips = [{'query': p.host} for p in batch]
                try:
                    async with s.post(GEO_BATCH_API, json=ips,
                            timeout=aiohttp.ClientTimeout(total=20)) as r:
                        if r.status == 200:
                            data = await r.json()
                            ip_map = {d['query']: d for d in data if d.get('status') == 'success'}
                            for p in batch:
                                if p.host in ip_map:
                                    d = ip_map[p.host]
                                    p.country = d.get('countryCode', '')
                                    p.country_name = d.get('country', '')
                                    p.city = d.get('city', '')
                                    p.zipcode = d.get('zip', '')
                                    p.isp = d.get('isp', '')
                                    p.org = d.get('org', '')
                                    p.asn = d.get('as', '')
                        elif r.status == 429:
                            log.warning('Geo API rate limited, pausing...')
                            await asyncio.sleep(60)
                except Exception as e:
                    log.warning(f'Geo batch failed: {e}')
                await asyncio.sleep(1.5)

    async def run_cycle(self, countries=None, progress_cb=None):
        raw = []
        async with aiohttp.ClientSession() as s:
            for name, url in cfg.SOURCES.items():
                try:
                    async with s.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
                        raw.extend(self._extract(await r.text(), name))
                except Exception as e:
                    log.warning(f'{name}: {e}')
        unique_map = {}
        for p in raw:
            key = (p.host, p.port)
            if key not in unique_map:
                unique_map[key] = p
        unique = list(unique_map.values())

        sem = asyncio.Semaphore(cfg.CONCURRENCY)
        async def check(p):
            async with sem:
                start = time.time()
                try:
                    conn = aiohttp_socks.ProxyConnector.from_url(self._proxy_url(p), rdns=True)
                    async with aiohttp.ClientSession(connector=conn,
                            timeout=aiohttp.ClientTimeout(total=cfg.TIMEOUT_SECONDS)) as s:
                        async with s.get(cfg.TEST_URL) as r:
                            await r.text()
                            p.latency_ms = round((time.time() - start) * 1000, 1)
                            now = time.time()
                            p.last_seen = now
                            if not p.first_seen:
                                p.first_seen = now
                            # Update existing proxy or create new
                            key = (p.host, p.port)
                            if key in self.proxies:
                                existing = self.proxies[key]
                                existing.latency_ms = p.latency_ms
                                existing.last_seen = now
                                existing.checks += 1
                                existing.successes += 1
                                existing.uptime = round(existing.successes / max(existing.checks, 1) * 100, 1)
                                existing.protocol = p.protocol
                                return existing
                            else:
                                p.checks = 1
                                p.successes = 1
                                p.uptime = 100.0
                                return p
                except Exception:
                    key = (p.host, p.port)
                    if key in self.proxies:
                        self.proxies[key].checks += 1
                        self.proxies[key].fails += 1
                        self.proxies[key].uptime = round(
                            self.proxies[key].successes / max(self.proxies[key].checks, 1) * 100, 1)
                    return None

        results = await asyncio.gather(*[check(p) for p in unique])
        alive = [p for p in results if p is not None]

        for p in alive:
            self.proxies[(p.host, p.port)] = p

        # Geo-enrich new proxies
        await self._geo_enrich(alive)

        # Anonymity check (sample up to 50 to avoid timeout)
        need_anon = [p for p in alive if not p.anonymity or p.anonymity == 'unknown'][:50]
        if need_anon:
            log.info(f'Anonymity check on {len(need_anon)} proxies...')
            anon_sem = asyncio.Semaphore(20)
            async def anon_check(p):
                async with anon_sem:
                    p.anonymity = await self._check_anonymity(None, p)
            await asyncio.gather(*[anon_check(p) for p in need_anon])

        self.save_state()
        self.export()
        return self.stats()

    def get_alive(self, countries=None, limit=0):
        now = time.time()
        items = [p for p in self.proxies.values() if now - p.last_seen < 3600 * 6]
        if countries:
            items = [p for p in items if p.country in countries]
        items.sort(key=lambda x: x.latency_ms)
        return items[:limit] if limit else items

    def get_inventory(self, country=None, protocol=None, anonymity=None, limit=100, offset=0):
        """Get filtered proxy inventory for frontend display."""
        items = self.get_alive()
        if country:
            items = [p for p in items if p.country == country.upper()]
        if protocol:
            items = [p for p in items if p.protocol == protocol.lower()]
        if anonymity:
            items = [p for p in items if p.anonymity == anonymity.lower()]
        total = len(items)
        items = items[offset:offset + limit]
        return items, total

    def inventory_stats(self):
        """Aggregate stats for frontend filters."""
        alive = self.get_alive()
        countries = {}
        protocols = {}
        anonymity = {}
        for p in alive:
            cc = p.country or 'XX'
            countries[cc] = countries.get(cc, 0) + 1
            proto = p.protocol or 'socks5'
            protocols[proto] = protocols.get(proto, 0) + 1
            anon = p.anonymity or 'unknown'
            anonymity[anon] = anonymity.get(anon, 0) + 1
        return {
            'total': len(alive),
            'countries': dict(sorted(countries.items(), key=lambda x: -x[1])),
            'protocols': dict(sorted(protocols.items(), key=lambda x: -x[1])),
            'anonymity': dict(sorted(anonymity.items(), key=lambda x: -x[1])),
        }

    def country_stats(self):
        stats = {}
        for p in self.get_alive():
            stats[p.country] = stats.get(p.country, 0) + 1
        return dict(sorted(stats.items(), key=lambda x: -x[1]))

    def stats(self):
        alive = self.get_alive()
        countries = {p.country for p in alive if p.country}
        lats = [p.latency_ms for p in alive if p.latency_ms > 0]
        proto_counts = {}
        anon_counts = {}
        for p in alive:
            proto_counts[p.protocol] = proto_counts.get(p.protocol, 0) + 1
            anon_counts[p.anonymity or 'unknown'] = anon_counts.get(p.anonymity or 'unknown', 0) + 1
        return {
            'alive': len(alive),
            'countries': sorted(countries),
            'country_counts': self.country_stats(),
            'protocol_counts': proto_counts,
            'anonymity_counts': anon_counts,
            'avg_latency': round(sum(lats) / len(lats), 1) if lats else 0,
            'avg_uptime': round(sum(p.uptime for p in alive) / len(alive), 1) if alive else 0,
            'updated': datetime.utcnow().isoformat()
        }

    def save_state(self):
        (cfg.OUTPUT_DIR / 'pool_state.json').write_text(
            json.dumps([asdict(p) for p in self.proxies.values()], indent=2))

    def load_state(self):
        p = cfg.OUTPUT_DIR / 'pool_state.json'
        if p.exists():
            try:
                for item in json.loads(p.read_text()):
                    # Handle old format without new fields
                    for f in ('protocol', 'zipcode', 'org', 'asn', 'anonymity',
                              'uptime', 'checks', 'successes', 'first_seen'):
                        if f not in item:
                            if f in ('uptime', 'checks', 'successes', 'first_seen'):
                                item[f] = 0.0 if f in ('uptime', 'first_seen') else 0
                            else:
                                item[f] = '' if f != 'protocol' else 'socks5'
                    px = Proxy(**item)
                    self.proxies[(px.host, px.port)] = px
            except Exception as e:
                log.warning(f'Failed to load state: {e}')

    def ingest(self, proxy_text: str, source: str = '', validate: bool = False) -> dict:
        """Ingest raw ip:port text into the pool. Returns stats."""
        raw = self._extract(proxy_text, source)
        new_count = 0
        now = time.time()
        for p in raw:
            key = (p.host, p.port)
            if key not in self.proxies:
                p.last_seen = now
                p.first_seen = now
                self.proxies[key] = p
                new_count += 1
            else:
                self.proxies[key].last_seen = now
                if p.protocol and p.protocol != 'socks5':
                    self.proxies[key].protocol = p.protocol
        self.save_state()
        self.export()
        if validate:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import threading
                    result = {}
                    def _run():
                        nl = asyncio.new_event_loop()
                        asyncio.set_event_loop(nl)
                        result['stats'] = nl.run_until_complete(self.run_cycle())
                        nl.close()
                    t = threading.Thread(target=_run)
                    t.start(); t.join(timeout=120)
                else:
                    loop.run_until_complete(self.run_cycle())
            except RuntimeError:
                asyncio.run(self.run_cycle())
        return {'ingested': len(raw), 'new': new_count, 'pool_size': len(self.proxies),
                'alive': len(self.get_alive())}

    def export(self):
        alive = self.get_alive()
        (cfg.OUTPUT_DIR / 'socks5_ALL.txt').write_text(
            '\n'.join(f'{p.host}:{p.port}' for p in alive))
        (cfg.OUTPUT_DIR / 'socks5_ALL.json').write_text(
            json.dumps([asdict(p) for p in alive], indent=2))

pool = ProxyPool()
