"""SOCKS5 proxy scraper, validator, and pool manager with full metadata.

Key features:
- Real protocol probing: tries socks5 → socks4 → http per proxy
- Inline anonymity detection on every alive proxy (no sampling)
- Sorted exports by country, protocol, and anonymity level
- Geo-enrichment via ip-api.com batch API
"""
import asyncio, json, logging, re, time
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
import aiohttp, aiohttp_socks
import config as cfg

log = logging.getLogger('socks5core')

GEO_BATCH_API = 'http://ip-api.com/batch?fields=status,query,country,countryCode,city,zip,isp,as,org'
ANON_HEADERS = ('x-forwarded-for', 'via', 'x-real-ip', 'forwarded',
                'x-proxy-id', 'x-bluecoat-via', 'proxy-connection')

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


def _hint_protocol(source_name: str) -> str:
    s = source_name.lower()
    if 'socks5' in s or '_s5' in s: return 'socks5'
    if 'socks4' in s or '_s4' in s: return 'socks4'
    if 'https' in s: return 'https'
    if 'http' in s: return 'http'
    return 'socks5'


class ProxyPool:
    def __init__(self):
        self.proxies: dict[tuple[str, int], Proxy] = {}

    def _proxy_url(self, host: str, port: int, proto: str) -> str:
        return f'{proto}://{host}:{port}'

    def _extract(self, text: str, source: str = '') -> list[Proxy]:
        hint = _hint_protocol(source) if source else 'socks5'
        found = []
        for m in re.finditer(r'(?P<ip>\d{1,3}(?:\.\d{1,3}){3})[:\s]+(?P<port>\d{2,5})', text):
            host, port = m.group('ip'), int(m.group('port'))
            if 1 <= port <= 65535:
                found.append(Proxy(host=host, port=port, protocol=hint))
        return found

    # ── Protocol probing ──────────────────────────────────────────────
    async def _probe_protocol(self, host: str, port: int, hint: str,
                              timeout: float) -> tuple[str, float] | None:
        """Try connecting through proxy, starting with hinted protocol.
        Returns (verified_protocol, latency_ms) or None."""
        # Build ordered list: hint first, then others
        protos = [hint] + [p for p in ('socks5', 'socks4', 'http') if p != hint]

        for proto in protos:
            start = time.time()
            try:
                if proto in ('socks5', 'socks4'):
                    conn = aiohttp_socks.ProxyConnector.from_url(
                        self._proxy_url(host, port, proto), rdns=True)
                    async with aiohttp.ClientSession(
                            connector=conn,
                            timeout=aiohttp.ClientTimeout(total=timeout)) as s:
                        async with s.get(cfg.TEST_URL) as r:
                            await r.text()
                            return proto, round((time.time() - start) * 1000, 1)
                else:
                    proxy_url = f'http://{host}:{port}'
                    async with aiohttp.ClientSession(
                            timeout=aiohttp.ClientTimeout(total=timeout)) as s:
                        async with s.get(cfg.TEST_URL, proxy=proxy_url) as r:
                            await r.text()
                            return proto, round((time.time() - start) * 1000, 1)
            except Exception:
                continue
        return None

    # ── Anonymity detection ───────────────────────────────────────────
    async def _detect_anonymity(self, host: str, port: int, proto: str,
                                timeout: float) -> str:
        """Check anonymity by analyzing what headers the proxy leaks.
        Returns: elite, anonymous, transparent, or unknown."""
        try:
            test_url = getattr(cfg, 'ANONYMITY_TEST_URL', 'http://httpbin.org/headers')
            if proto in ('socks5', 'socks4'):
                conn = aiohttp_socks.ProxyConnector.from_url(
                    self._proxy_url(host, port, proto), rdns=True)
                async with aiohttp.ClientSession(
                        connector=conn,
                        timeout=aiohttp.ClientTimeout(total=timeout)) as s:
                    async with s.get(test_url) as r:
                        data = await r.json()
            else:
                proxy_url = f'http://{host}:{port}'
                async with aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=timeout)) as s:
                    async with s.get(test_url, proxy=proxy_url) as r:
                        data = await r.json()

            headers = {k.lower(): v for k, v in data.get('headers', {}).items()}

            # Check if proxy leaks the real IP in any header
            leaks_ip = any(host in headers.get(h, '') for h in ANON_HEADERS)
            has_proxy_headers = any(h in headers for h in ANON_HEADERS)

            if leaks_ip:
                return 'transparent'
            elif has_proxy_headers:
                return 'anonymous'
            else:
                return 'elite'
        except Exception:
            return 'unknown'

    # ── Geo enrichment ────────────────────────────────────────────────
    async def _geo_enrich(self, proxies: list[Proxy]):
        need = [p for p in proxies if not p.country]
        if not need:
            return
        for i in range(0, len(need), 80):
            batch = need[i:i + 80]
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(GEO_BATCH_API,
                                      json=[p.host for p in batch],
                                      timeout=aiohttp.ClientTimeout(total=15)) as r:
                        if r.status == 200:
                            results = await r.json()
                            for d in results:
                                if d.get('status') == 'success':
                                    ip = d.get('query', '')
                                    for p in batch:
                                        if p.host == ip:
                                            p.country = d.get('countryCode', '')
                                            p.country_name = d.get('country', '')
                                            p.city = d.get('city', '')
                                            p.zipcode = d.get('zip', '')
                                            p.isp = d.get('isp', '')
                                            p.org = d.get('org', '')
                                            p.asn = d.get('as', '')
                        elif r.status == 429:
                            log.warning('Geo API rate limited, pausing 60s...')
                            await asyncio.sleep(60)
            except Exception as e:
                log.warning(f'Geo batch failed: {e}')
            await asyncio.sleep(1.5)

    # ── Main scrape + validate cycle ──────────────────────────────────
    async def run_cycle(self, countries=None, progress_cb=None):
        # 1. Scrape all sources
        raw = []
        async with aiohttp.ClientSession() as s:
            for name, url in cfg.SOURCES.items():
                try:
                    async with s.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
                        raw.extend(self._extract(await r.text(), name))
                except Exception as e:
                    log.warning(f'{name}: {e}')
        log.info(f'Scraped {len(raw)} proxies from {len(cfg.SOURCES)} sources')

        # 2. Deduplicate, keeping best protocol hint
        unique_map: dict[tuple[str, int], Proxy] = {}
        proto_priority = {'socks5': 0, 'socks4': 1, 'https': 2, 'http': 3}
        for p in raw:
            key = (p.host, p.port)
            if key not in unique_map:
                unique_map[key] = p
            else:
                existing = unique_map[key]
                if proto_priority.get(p.protocol, 9) < proto_priority.get(existing.protocol, 9):
                    unique_map[key] = p
        unique = list(unique_map.values())
        log.info(f'{len(unique)} unique proxies to check')

        # 3. Protocol probe + connectivity check
        sem = asyncio.Semaphore(cfg.CONCURRENCY)
        timeout = cfg.TIMEOUT_SECONDS

        async def check(p: Proxy) -> Proxy | None:
            async with sem:
                result = await self._probe_protocol(p.host, p.port, p.protocol, timeout)
                if not result:
                    key = (p.host, p.port)
                    if key in self.proxies:
                        self.proxies[key].checks += 1
                        self.proxies[key].fails += 1
                        ex = self.proxies[key]
                        ex.uptime = round(ex.successes / max(ex.checks, 1) * 100, 1)
                    return None

                verified_proto, latency = result
                now = time.time()
                key = (p.host, p.port)

                if key in self.proxies:
                    ex = self.proxies[key]
                    ex.protocol = verified_proto
                    ex.latency_ms = latency
                    ex.last_seen = now
                    ex.checks += 1
                    ex.successes += 1
                    ex.uptime = round(ex.successes / max(ex.checks, 1) * 100, 1)
                    return ex
                else:
                    p.protocol = verified_proto
                    p.latency_ms = latency
                    p.last_seen = now
                    p.first_seen = now
                    p.checks = 1
                    p.successes = 1
                    p.uptime = 100.0
                    return p

        results = await asyncio.gather(*[check(p) for p in unique])
        alive = [p for p in results if p is not None]
        log.info(f'{len(alive)} proxies alive after protocol probing')

        for p in alive:
            self.proxies[(p.host, p.port)] = p

        # 4. Geo-enrich new proxies
        await self._geo_enrich(alive)

        # 5. Inline anonymity detection on ALL proxies that need it
        anon_limit = getattr(cfg, 'ANON_CHECK_LIMIT', 0)
        need_anon = [p for p in alive if not p.anonymity or p.anonymity == 'unknown']
        if anon_limit > 0:
            need_anon = need_anon[:anon_limit]
        if need_anon:
            log.info(f'Anonymity check on {len(need_anon)} proxies...')
            anon_sem = asyncio.Semaphore(50)
            async def anon_check(p: Proxy):
                async with anon_sem:
                    p.anonymity = await self._detect_anonymity(
                        p.host, p.port, p.protocol, timeout + 2)
            await asyncio.gather(*[anon_check(p) for p in need_anon])
            log.info('Anonymity detection complete')

        # 6. Purge dead proxies (failed too many times)
        dead_keys = [k for k, p in self.proxies.items()
                     if p.fails >= cfg.REMOVE_DEAD_AFTER_FAILS and p.successes == 0]
        for k in dead_keys:
            del self.proxies[k]
        if dead_keys:
            log.info(f'Purged {len(dead_keys)} dead proxies')

        self.save_state()
        self.export()
        return self.stats()

    # ── Query methods ─────────────────────────────────────────────────
    def get_alive(self, countries=None, limit=0):
        now = time.time()
        items = [p for p in self.proxies.values() if now - p.last_seen < 3600 * 6]
        if countries:
            items = [p for p in items if p.country in countries]
        items.sort(key=lambda x: x.latency_ms)
        return items[:limit] if limit else items

    def get_inventory(self, country=None, protocol=None, anonymity=None,
                      sort_by='latency', limit=100, offset=0):
        """Get filtered + sorted proxy inventory for frontend."""
        items = self.get_alive()
        if country:
            items = [p for p in items if p.country == country.upper()]
        if protocol:
            items = [p for p in items if p.protocol == protocol.lower()]
        if anonymity:
            items = [p for p in items if p.anonymity == anonymity.lower()]
        # Sort
        sort_keys = {
            'latency': lambda x: x.latency_ms,
            'uptime': lambda x: -x.uptime,
            'country': lambda x: x.country,
        }
        items.sort(key=sort_keys.get(sort_by, sort_keys['latency']))
        total = len(items)
        items = items[offset:offset + limit]
        return items, total

    def inventory_filters(self):
        """Return available filter values with counts for frontend dropdowns."""
        alive = self.get_alive()
        countries = defaultdict(int)
        protocols = defaultdict(int)
        anon_levels = defaultdict(int)
        for p in alive:
            countries[p.country or 'XX'] += 1
            protocols[p.protocol or 'socks5'] += 1
            anon_levels[p.anonymity or 'unknown'] += 1
        return {
            'total': len(alive),
            'countries': dict(sorted(countries.items(), key=lambda x: -x[1])),
            'protocols': dict(sorted(protocols.items(), key=lambda x: -x[1])),
            'anonymity': dict(sorted(anon_levels.items(), key=lambda x: -x[1])),
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
        proto_counts = defaultdict(int)
        anon_counts = defaultdict(int)
        for p in alive:
            proto_counts[p.protocol] += 1
            anon_counts[p.anonymity or 'unknown'] += 1
        return {
            'alive': len(alive),
            'countries': sorted(countries),
            'country_counts': self.country_stats(),
            'protocol_counts': dict(proto_counts),
            'anonymity_counts': dict(anon_counts),
            'avg_latency': round(sum(lats) / len(lats), 1) if lats else 0,
            'avg_uptime': round(sum(p.uptime for p in alive) / len(alive), 1) if alive else 0,
            'updated': datetime.utcnow().isoformat()
        }

    # ── Persistence ───────────────────────────────────────────────────
    def save_state(self):
        (cfg.OUTPUT_DIR / 'pool_state.json').write_text(
            json.dumps([asdict(p) for p in self.proxies.values()], indent=2))

    def load_state(self):
        p = cfg.OUTPUT_DIR / 'pool_state.json'
        if p.exists():
            try:
                for item in json.loads(p.read_text()):
                    for f in ('protocol', 'zipcode', 'org', 'asn', 'anonymity',
                              'uptime', 'checks', 'successes', 'first_seen'):
                        if f not in item:
                            if f in ('uptime', 'first_seen'):
                                item[f] = 0.0
                            elif f in ('checks', 'successes'):
                                item[f] = 0
                            else:
                                item[f] = '' if f != 'protocol' else 'socks5'
                    px = Proxy(**item)
                    self.proxies[(px.host, px.port)] = px
            except Exception as e:
                log.warning(f'Failed to load state: {e}')

    def ingest(self, proxy_text: str, source: str = '', validate: bool = False) -> dict:
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

    # ── Export sorted files ───────────────────────────────────────────
    def export(self):
        alive = self.get_alive()

        # Master lists
        (cfg.OUTPUT_DIR / 'ALL.txt').write_text(
            '\n'.join(f'{p.host}:{p.port}' for p in alive))
        (cfg.OUTPUT_DIR / 'ALL.json').write_text(
            json.dumps([asdict(p) for p in alive], indent=2))

        # By protocol
        by_proto = defaultdict(list)
        for p in alive:
            by_proto[p.protocol].append(p)
        for proto, proxies in by_proto.items():
            (cfg.OUTPUT_DIR / f'{proto.upper()}.txt').write_text(
                '\n'.join(f'{p.host}:{p.port}' for p in proxies))

        # By anonymity
        by_anon = defaultdict(list)
        for p in alive:
            level = p.anonymity or 'unknown'
            by_anon[level].append(p)
        for level, proxies in by_anon.items():
            (cfg.OUTPUT_DIR / f'ANON_{level.upper()}.txt').write_text(
                '\n'.join(f'{p.host}:{p.port}' for p in proxies))

        # By country (top 30)
        by_country = defaultdict(list)
        for p in alive:
            if p.country:
                by_country[p.country].append(p)
        for cc in sorted(by_country, key=lambda c: -len(by_country[c]))[:30]:
            (cfg.OUTPUT_DIR / f'COUNTRY_{cc}.txt').write_text(
                '\n'.join(f'{p.host}:{p.port}' for p in by_country[cc]))

        # Legacy compat
        s5 = by_proto.get('socks5', [])
        (cfg.OUTPUT_DIR / 'socks5_ALL.txt').write_text(
            '\n'.join(f'{p.host}:{p.port}' for p in s5))
        (cfg.OUTPUT_DIR / 'socks5_ALL.json').write_text(
            json.dumps([asdict(p) for p in s5], indent=2))


pool = ProxyPool()


class Scraper:
    def run_once(self):
        pool.load_state()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import threading
                def _run():
                    nl = asyncio.new_event_loop()
                    asyncio.set_event_loop(nl)
                    nl.run_until_complete(pool.run_cycle())
                    nl.close()
                t = threading.Thread(target=_run)
                t.start(); t.join(timeout=300)
            else:
                loop.run_until_complete(pool.run_cycle())
        except RuntimeError:
            asyncio.run(pool.run_cycle())

    def run_loop(self):
        pool.load_state()
        async def _loop():
            while True:
                try:
                    await pool.run_cycle()
                except Exception as e:
                    log.error(f'Scrape cycle failed: {e}')
                await asyncio.sleep(cfg.SCRAPE_INTERVAL_MINUTES * 60)
        asyncio.run(_loop())


scraper = Scraper()
