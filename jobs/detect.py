"""Fill in ats / ats_key for companies the research pass left as unknown.

  python -m jobs.detect --companies config/companies.csv --out config/companies.csv

1. Fetch careers_url (and a few common paths on the domain) and look for an ATS fingerprint.
2. If none, probe public board APIs with slug guesses made from the company name.
Every change is written to config/detect_log.csv with the evidence URL.
"""
import argparse
import csv
import re
import unicodedata

from .net import Net

FP = [
    ("teamtailor", r"https?://([a-z0-9.-]+\.teamtailor\.com)|([a-z0-9.-]+)/jobs\.rss|teamtailor-cdn"),
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)"),
    ("lever", r"jobs(?:\.eu)?\.lever\.co/([a-z0-9_.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)"),
    ("workable", r"apply\.workable\.com/([a-z0-9_-]+)"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("recruitee", r"([a-z0-9-]+)\.recruitee\.com"),
    ("personio", r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
    ("workday", r"(https://[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?[A-Za-z0-9_-]+)"),
    ("deel", r"jobs\.deel\.com/(?:job-boards/)?([a-z0-9_-]+)"),
    ("jobylon", r"(emp\.jobylon\.com/companies/[0-9]+-[a-z0-9-]+)"),
    ("varbi", r"([a-z0-9-]+\.varbi\.com)"),
    ("reachmee", r"(site\d*\.reachmee\.com/[^\"' ]+)"),
    ("successfactors", r"(career\d*\.successfactors\.(?:eu|com)/[^\"' ]+|jobs\.sap\.com)"),
    ("eightfold", r"([a-z0-9.-]+)/careers\?[^\"']*domain=|eightfold\.ai"),
]
FP = [(n, re.compile(p, re.I)) for n, p in FP]
PATHS = ["", "/careers", "/jobs", "/career", "/en/careers", "/karriar", "/jobb", "/lediga-jobb", "/about/careers"]


def slugs(name, domain):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(ab|group|sweden|sverige|technologies|tech)\b", "", s).strip()
    out = {re.sub(r"[^a-z0-9]", "", s), re.sub(r"[^a-z0-9]+", "-", s).strip("-")}
    if domain:
        out.add(domain.split(".")[0].lower())
    return [x for x in out if x]


def fingerprint(html):
    for name, rx in FP:
        m = rx.search(html or "")
        if m:
            key = next((g for g in m.groups() if g), "") if m.groups() else ""
            return name, key
    return None, None


def probe(net, s):
    tries = [
        ("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs", lambda d: isinstance(d, dict) and "jobs" in d),
        ("lever", f"https://api.lever.co/v0/postings/{s}?mode=json&limit=1", lambda d: isinstance(d, list)),
        ("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{s}", lambda d: isinstance(d, dict) and "jobs" in d),
        ("workable", f"https://apply.workable.com/api/v1/widget/accounts/{s}", lambda d: isinstance(d, dict) and "jobs" in d),
        ("smartrecruiters", f"https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=1",
         lambda d: isinstance(d, dict) and d.get("totalFound", 0) > 0),
    ]
    for ats, url, ok in tries:
        d = net.get(url, tries=1)
        if d is not None and ok(d):
            return ats, s, url
    rss = net.get(f"https://{s}.teamtailor.com/jobs.rss", as_json=False, tries=1)
    if rss and "<rss" in rss[:500]:
        return "teamtailor", f"{s}.teamtailor.com", f"https://{s}.teamtailor.com/jobs.rss"
    return None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--companies", default="config/companies.csv")
    ap.add_argument("--out", default="config/companies.csv")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.companies, newline="", encoding="utf-8")))
    fields = list(rows[0].keys())
    net = Net()
    log = []
    for r in rows:
        if r.get("ats") not in ("", "unknown", None):
            continue
        found = None
        urls = [r["careers_url"]] if r.get("careers_url") else []
        urls += [f"https://www.{r['domain']}{p}" for p in PATHS if r.get("domain")]
        for u in urls[:5]:
            page = net.get(u, as_json=False, tries=1)
            ats, key = fingerprint(page)
            if ats:
                found = (ats, key, u)
                break
        if not found:
            for s in slugs(r["company"], r.get("domain", "")):
                ats, key, u = probe(net, s)
                if ats:
                    found = (ats, key, u)
                    break
        if found:
            r["ats"], r["ats_key"], r["evidence_url"] = found
            r["notes"] = (r.get("notes", "") + " [auto-detected]").strip()
            log.append(dict(company=r["company"], ats=found[0], key=found[1], evidence=found[2]))
            print("detected", r["company"], found)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with open("config/detect_log.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["company", "ats", "key", "evidence"])
        w.writeheader()
        w.writerows(log)


if __name__ == "__main__":
    main()
