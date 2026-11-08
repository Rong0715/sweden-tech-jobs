"""Polite HTTP: one client name, per-host rate limit, robots.txt, retries, a log of every refusal."""
import json
import threading
import time
import urllib.parse

import requests

from .robots import Robots

UA = "sweden-tech-jobs/0.3 (+https://github.com/Rong0715/sweden-tech-jobs)"
MIN_INTERVAL = 1.0          # seconds between requests to the same host
TIMEOUT = 30


class Net:
    def __init__(self, log_path=None):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"})
        self.last = {}
        self.robots = {}
        self.lock = threading.Lock()
        self.events = []
        self.log_path = log_path

    def log(self, **ev):
        ev["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.events.append(ev)
        if self.log_path:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    def _wait(self, host):
        with self.lock:
            now = time.time()
            t = self.last.get(host, 0) + MIN_INTERVAL
            if t > now:
                time.sleep(t - now)
            self.last[host] = time.time()

    def allowed(self, url):
        p = urllib.parse.urlsplit(url)
        host = p.netloc.lower()
        if host not in self.robots:
            try:
                self._wait(host)
                r = self.s.get(f"{p.scheme}://{host}/robots.txt", timeout=TIMEOUT)
                if r.status_code >= 500:
                    rp = Robots(disallow_all=True)  # unreachable: assume disallow (RFC 9309 2.3.1.4)
                elif r.status_code >= 400:
                    rp = Robots()               # any 4xx, 401/403 included, means "unavailable": allowed (RFC 9309 2.3.1.3)
                else:
                    rp = Robots(r.text)
            except requests.RequestException:
                rp = Robots(disallow_all=True)
            self.robots[host] = rp
        ok, rule = self.robots[host].match(UA, url)
        if not ok:
            self.log(kind="robots_disallow", url=url, rule=rule)
        return ok

    def get(self, url, *, params=None, as_json=True, method="GET", body=None, tries=4, headers=None):
        if not self.allowed(url):
            return None
        host = urllib.parse.urlsplit(url).netloc.lower()
        err = ""
        for i in range(tries):
            self._wait(host)
            try:
                r = self.s.request(method, url, params=params, json=body, timeout=TIMEOUT, headers=headers)
            except requests.RequestException as e:
                err = str(e)[:200]
                time.sleep(2 ** i)
                continue
            if r.status_code in (429, 502, 503, 504):
                time.sleep(int(r.headers.get("Retry-After", 2 ** (i + 1))) if str(r.headers.get("Retry-After", "")).isdigit() else 2 ** (i + 1))
                err = f"HTTP {r.status_code}"
                continue
            if r.status_code >= 400:
                self.log(kind="http_error", url=r.url, status=r.status_code)
                return None
            if as_json:
                try:
                    return r.json()
                except ValueError:
                    self.log(kind="bad_json", url=r.url)
                    return None
            return r.text
        self.log(kind="gave_up", url=url, error=err)
        return None
