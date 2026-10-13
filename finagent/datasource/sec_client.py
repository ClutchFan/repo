import time, httpx

class SECClient:
    BASE = "https://data.sec.gov"
    WWW = "https://www.sec.gov"

    def __init__(self, user_agent: str, cache, client: httpx.Client | None = None, min_interval: float = 0.2):
        self._ua = user_agent
        self._cache = cache
        self._http = client or httpx.Client(headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate"
        })
        self._min_interval = min_interval
        self._last = 0.0

    def _throttle(self):
        if self._min_interval:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
        self._last = time.monotonic()

    def get_json(self, path: str) -> dict:
        url = path if path.startswith("http") else f"{self.BASE}{path}"
        hit = self._cache.get(url)
        if hit is not None:
            import json
            return json.loads(hit)

        self._throttle()
        r = self._http.get(url)
        r.raise_for_status()
        self._cache.set(url, r.text)
        return r.json()

    def get_company_facts(self, cik: int) -> dict:
        return self.get_json(f"/api/xbrl/companyfacts/CIK{int(cik):010d}.json")

    def get_submissions(self, cik: int) -> dict:
        return self.get_json(f"/submissions/CIK{int(cik):010d}.json")

    def get_ticker_index(self) -> list[dict]:
        data = self.get_json(f"{self.WWW}/files/company_tickers.json")
        return list(data.values())
