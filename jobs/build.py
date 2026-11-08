"""Normalise raw postings into one table, label them, dedupe across sources.

  python -m jobs.build --raw data/raw/<date> [--ericsson ../ericsson/<file>.csv]

Outputs in data/<date>/: listings.csv, listings.parquet, listings.sqlite, summary.json
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sqlite3
import unicodedata

import pandas as pd

from . import classify, skills

RECRUITER = re.compile(r"bemanning|rekryter|recruit|staffing|academic work|experis|randstad|adecco|manpower|"
                       r"dfind|ework|keyman|wise (?:it|professionals)|poolia|perido|onepartner|cinode|"
                       r"\bjefferson wells\b|hays|nexer recruit|incluso|clevry|talent ?search", re.I)
CONSULT = re.compile(r"consult|konsult|accenture|capgemini|\bcgi\b|tietoevry|\bhiq\b|knowit|sigma|netlight|"
                     r"alten|afry|sopra|devoteam|combitech|syntronic|etteplan|semcon|softhouse|squeed|"
                     r"omegapoint|tretton37|valtech|nexer|bouvet|kvadrat|prevas|cybercom|knightec|data edge|"
                     r"\bmpya\b|crisp\b|agical|redpill|deloitte|\bey\b|kpmg|pwc|infosys|\btcs\b|tata consultancy|"
                     r"wipro|hcl|cognizant|epam|tech mahindra|\bqrios\b|ework|addq|b3 |iteam|xlent", re.I)
_SUFFIX = re.compile(r"\b(ab|aktiebolag|\(publ\)|publ|sverige|sweden|svenska|nordic|nordics|group|grupp|ltd|inc|"
                     r"gmbh|as|a/s|oy|plc|international|technologies|technology|tech|holding|services|"
                     r"filial|branch|norden|europe|scandinavia)\b", re.I)


def norm_name(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", _SUFFIX.sub(" ", s))
    return re.sub(r"\s+", " ", s).strip()


def norm_title(s):
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", (s or "").lower())
    s = re.sub(r"[^a-z0-9åäö+# ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def first_city(loc):
    from .adapters import _SE_RX
    m = _SE_RX.search(loc or "")
    return m.group(1).lower().replace("gothenburg", "göteborg").replace("goteborg", "göteborg") if m else ""


def tier_lookup(companies):
    by = {}
    for r in companies:
        for n in {r["company"], r.get("domain", "").split(".")[0]}:
            nn = norm_name(n)
            if nn:
                by[nn] = r
    return by


def match_tier(name, by):
    nn = norm_name(name)
    if not nn:
        return None
    if nn in by:
        return by[nn]
    toks = nn.split()
    for i in range(len(toks), 0, -1):          # longest prefix match ("volvo car corporation" -> "volvo cars"? no; "spotify technology" -> spotify)
        cand = " ".join(toks[:i])
        if cand in by and len(cand) >= 3:
            return by[cand]
    return None


def label(p):
    text = p.get("description") or ""
    full = f"{p.get('title','')}\n{text}"
    sen, yrs = classify.seniority(p.get("title"), text)
    sig = classify.signals(text, p.get("must_langs"))
    return dict(
        seniority=sen, entry=sen in classify.ENTRY, years_req=yrs,
        family=classify.role_family(p.get("title"), text),
        skills="|".join(skills.extract(full)),
        **{k: v for k, v in sig.items()},
        text_len=len(text),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--companies", default="config/companies.csv")
    ap.add_argument("--ericsson", default=None, help="optional CSV from the Ericsson crawler (read only)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    day = os.path.basename(a.raw.rstrip("/"))
    out = a.out or os.path.join("data", day)
    os.makedirs(out, exist_ok=True)

    with open(a.companies, newline="", encoding="utf-8") as f:
        companies = [r for r in csv.DictReader(f) if r.get("company")]
    by = tier_lookup(companies)

    rows = []
    for path in sorted(glob.glob(os.path.join(a.raw, "*.jsonl"))):
        if path.endswith("net_log.jsonl"):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                rows.append(json.loads(line))
    if a.ericsson and os.path.exists(a.ericsson):
        e = pd.read_csv(a.ericsson)
        cols = {c.lower(): c for c in e.columns}
        g = lambda r, *ks: next((r[cols[k]] for k in ks if k in cols and pd.notna(r[cols[k]])), "")
        for _, r in e.iterrows():
            rows.append(dict(source="eightfold_ericsson", company="Ericsson", tier="top", ext_id=g(r, "id", "job_id"),
                             title=g(r, "title", "name"), location=g(r, "location", "locations"), country="",
                             url=g(r, "url", "link"), posted=str(g(r, "posted", "date", "t_create"))[:10], deadline="",
                             description=g(r, "description", "job_description", "text"), department=g(r, "department"),
                             employment_type="", workplace="", in_sweden=True))

    recs = []
    for p in rows:
        if not p.get("in_sweden"):
            continue
        c = match_tier(p["company"], by)
        tier = p.get("tier") or (c or {}).get("tier", "")
        if not tier:
            tier = "recruiter" if RECRUITER.search(p["company"] or "") else \
                   "consultancy" if CONSULT.search(p["company"] or "") else "other"
        canon = (c or {}).get("company") or p["company"]
        lab = label(p)
        recs.append(dict(
            company=canon, company_raw=p["company"], tier=tier, sector=(c or {}).get("sector", ""),
            title=p["title"], city=first_city(p.get("location")), location=p.get("location", ""),
            remote=p.get("workplace") or lab["remote"], posted=p.get("posted", ""), deadline=p.get("deadline", ""),
            url=p.get("url", ""), source=p["source"], ext_id=p.get("ext_id", ""), field=p.get("field", ""),
            occupation=p.get("occupation", ""), org_nr=p.get("org_nr", ""),
            seniority=lab["seniority"], entry=lab["entry"], years_req=lab["years_req"], family=lab["family"],
            skills=lab["skills"], swedish_required=lab["swedish_required"], swedish_plus=lab["swedish_plus"],
            eu_only=lab["eu_only"], clearance=lab["clearance"], visa_ok=lab["visa_ok"], ad_lang=lab["ad_lang"],
            text_len=lab["text_len"], description=(p.get("description") or "")[:30000],
        ))
    df = pd.DataFrame(recs)
    if df.empty:
        print("no rows")
        return
    # dedupe: same employer + same normalised title + same city = one job. Prefer the
    # company's own ATS (direct link, richer text) over Platsbanken.
    base = (df["company"].map(norm_name) + "|" + df["title"].map(norm_title) + "|" + df["city"])
    # several real openings can share a title at one employer (different teams), so only
    # collapse ACROSS sources: the i-th copy on one source matches the i-th copy on another.
    df = df.sort_values(["posted", "ext_id"])
    df["dkey"] = base.loc[df.index] + "#" + df.groupby([base.loc[df.index], df["source"]]).cumcount().astype(str)
    pref = {"jobtech": 1}
    df["_rank"] = df["source"].map(lambda s: pref.get(s, 0))
    df["_len"] = -df["text_len"]
    df = df.sort_values(["dkey", "_rank", "_len"])
    srcs = df.groupby("dkey")["source"].agg(lambda s: "|".join(sorted(set(s))))
    df = df.drop_duplicates("dkey", keep="first").copy()
    df["sources"] = df["dkey"].map(srcs)
    df["uid"] = df["dkey"].map(lambda k: hashlib.sha1(k.encode()).hexdigest()[:12])
    df = df.drop(columns=["_rank", "_len"])
    df["snapshot"] = day

    df.drop(columns=["description"]).to_csv(os.path.join(out, "listings.csv"), index=False)
    df.to_parquet(os.path.join(out, "listings.parquet"), index=False)
    con = sqlite3.connect(os.path.join(out, "listings.sqlite"))
    df.to_sql("listings", con, if_exists="replace", index=False)
    con.close()
    summ = dict(snapshot=day, listings=len(df), companies=int(df["company"].nunique()),
                by_source=df["sources"].str.split("|").explode().value_counts().to_dict(),
                by_tier=df["tier"].value_counts().to_dict(), by_seniority=df["seniority"].value_counts().to_dict(),
                by_family=df["family"].value_counts().to_dict())
    json.dump(summ, open(os.path.join(out, "summary.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(summ, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
