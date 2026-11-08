"""Merge the research parts into config/companies.csv (dedupe by domain, then by name)."""
import csv, glob, os, re
here = os.path.dirname(os.path.abspath(__file__))
rows, seen = [], set()
for p in sorted(glob.glob(os.path.join(here, "parts", "*.csv"))):
    for r in csv.DictReader(open(p, newline="", encoding="utf-8")):
        if not r.get("company"):
            continue
        key = (r.get("domain") or "").lower().strip() or re.sub(r"\W", "", r["company"].lower())
        name = re.sub(r"\W", "", r["company"].lower())
        if key in seen or name in seen:
            continue
        seen |= {key, name}
        r = {k: (v or "").strip() for k, v in r.items() if k}
        r["ats"] = (r.get("ats") or "unknown").lower()
        rows.append(r)
cols = ["company", "domain", "tier", "sector", "sweden_sites", "careers_url", "ats", "ats_key", "evidence_url", "notes"]
with open(os.path.join(here, "companies.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader(); w.writerows(rows)
from collections import Counter
print(len(rows), "companies;", dict(Counter(r["ats"] for r in rows).most_common()), dict(Counter(r["tier"] for r in rows)))
