"""Crawl today's snapshot: JobTech + every company's ATS board.

  python -m jobs.crawl [--only jobtech|ats] [--companies config/companies.csv] [--out data/raw/<date>]

Writes raw/<source>.jsonl (one posting per line), coverage.csv (one row per company:
status, postings seen, postings in Sweden) and net_log.jsonl (robots/HTTP refusals).
"""
import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import json
import os
import traceback

from . import adapters, jobtech
from .net import Net


def load_companies(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("company")]


def crawl_company(net, row):
    ats = (row.get("ats") or "").strip().lower()
    key = (row.get("ats_key") or "").strip()
    if ats in ("", "unknown", "custom", "jobylon", "varbi", "reachmee", "successfactors", "icims", "oracle"):
        if row.get("careers_url") and ats not in ("",):
            # the generic fallback reads the careers page itself; ats_key is often a bare
            # host or a vendor id there, not a URL
            start = key if key.startswith(("http://", "https://")) else row["careers_url"]
            fn, row = adapters.html, dict(row, ats_key=start)
            ats = "html"
        else:
            return [], dict(status="skipped_no_adapter", ats=ats)
    else:
        fn = adapters.ADAPTERS.get(ats)
        if not fn or not key:
            return [], dict(status="skipped_no_key", ats=ats)
    try:
        posts, ok = fn(net, row)
    except Exception as e:  # one broken board must not stop the crawl
        return [], dict(status="error", ats=ats, error=f"{type(e).__name__}: {e}"[:300], tb=traceback.format_exc()[-800:])
    return posts, dict(status="ok" if ok else "fetch_failed", ats=ats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--companies", default="config/companies.csv")
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", choices=["jobtech", "ats"], default=None)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    day = dt.date.today().isoformat()
    out = a.out or os.path.join("data", "raw", day)
    os.makedirs(out, exist_ok=True)
    net = Net(log_path=os.path.join(out, "net_log.jsonl"))

    if a.only in (None, "jobtech"):
        n = 0
        with open(os.path.join(out, "jobtech.jsonl"), "w", encoding="utf-8") as f:
            for h in jobtech.current_ads(net):
                f.write(json.dumps(jobtech.ad_to_posting(h), ensure_ascii=False) + "\n")
                n += 1
        print(f"jobtech: {n} ads")

    if a.only in (None, "ats"):
        rows = load_companies(a.companies)
        cov = []
        with open(os.path.join(out, "ats.jsonl"), "w", encoding="utf-8") as f, \
                cf.ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(crawl_company, net, r): r for r in rows}
            for fu in cf.as_completed(futs):
                r = futs[fu]
                posts, st = fu.result()
                for p in posts:
                    f.write(json.dumps(p, ensure_ascii=False) + "\n")
                cov.append(dict(company=r["company"], tier=r.get("tier", ""), ats=st.get("ats"), status=st["status"],
                                seen=len(posts), in_sweden=sum(p["in_sweden"] for p in posts), error=st.get("error", "")))
                print(f"{r['company']:<32} {st['status']:<20} {len(posts):>4} seen {cov[-1]['in_sweden']:>4} SE")
        with open(os.path.join(out, "coverage.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(cov[0].keys()) if cov else ["company"])
            w.writeheader()
            w.writerows(sorted(cov, key=lambda c: c["company"].lower()))


if __name__ == "__main__":
    main()
