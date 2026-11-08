"""Polite HTTP: one client name, per-host rate limit, robots.txt, retries, a log of every refusal."""
import json
import threading
import time
import urllib.parse
import urllib.robotparser

import requests

UA = "sweden-tech-jobs-research/0.2 (personal labour-market study; contact via GitHub repo)"
MIN_INTERVAL = 1.0          # seconds between requests to the same host
TIMEOUT = 30

# Hosts whose job feeds are documented public APIs meant for programmatic reading.
# robots.txt is still read and logged for them, but a robots "Disallow" written for
# web crawlers does not stop the documented API (it is reported in coverage.csv).
DOCUMENTED_APIS = {
    "jobsearch.api.jobtechdev.se", "historical.api.jobtechdev.se", "data.jobtechdev.se",
    "boards-api.greenhouse.io", "api.lever.co", "api.eu.lever.co", "api.ashbyhq.com",
    "api.smartrecruiters.com", "apply.workable.com",
}


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
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._wait(host)
                r = self.s.get(f"{p.scheme}://{host}/robots.txt", timeout=TIMEOUT)
                if r.status_code >= 400:
                    rp.parse([])          # no robots.txt -> allowed
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp.parse([])
            self.robots[host] = rp
        ok = self.robots[host].can_fetch(UA, url)
        if not ok and host in DOCUMENTED_APIS:
            self.log(kind="robots_disallow_documented_api", url=url)
            return True
        if not ok:
            self.log(kind="robots_disallow", url=url)
        return ok

    def get(self, url, *, params=None, as_json=True, method="GET", body=None, tries=4, headers=None):
        if not self.allowed(url):
            return None
        host = urllib.parse.urlsplit(url).netloc.lower()
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
