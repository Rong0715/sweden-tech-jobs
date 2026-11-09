"""Diagnostics for the yearly skill trends, run on the per-ad feature tables (no ad text).

Prints aggregated CSV only: per-year text length and skills-per-ad, and per-skill shares
standardised to one pooled ad-length distribution, so that a year whose ads are shorter
(less text, so fewer skills found) does not read as falling demand.
"""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from jobs import classify
from jobs.analyze import skill_matrix

h = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(sys.argv[1] + "/ads_*.parquet"))], ignore_index=True)
h = h[h.year.notna() & (h.year >= 2020)].copy()
h["year"] = h.year.astype(int)
it = h[h.sw_title & h.family.isin(classify.ENG_FAMILIES)].reset_index(drop=True)
M, ids = skill_matrix(it)
nsk = M.sum(1)
edges = np.unique(np.quantile(it.text_len, np.linspace(0, 1, 11)))
it["bin"] = np.clip(np.searchsorted(edges, it.text_len, side="right") - 1, 0, len(edges) - 2)
ref = it.bin.value_counts(normalize=True).sort_index()
print("YEARCSV,year,n,len_p10,len_median,len_p90,zero_skill_share,mean_skills,top_employer,top_employer_share,dup_title_employer_share")
for y, g in it.groupby("year"):
    m = (it.year == y).values
    top = g.employer.value_counts()
    dup = g.duplicated(["title", "employer"]).mean()
    print(f"YEARCSV,{y},{len(g)},{g.text_len.quantile(.1):.0f},{g.text_len.median():.0f},{g.text_len.quantile(.9):.0f},"
          f"{(nsk[m]==0).mean():.4f},{nsk[m].mean():.3f},\"{top.index[0]}\",{top.iloc[0]/len(g):.4f},{dup:.4f}")
print("BINCSV,year," + ",".join(f"b{i}" for i in range(len(edges) - 1)))
for y, g in it.groupby("year"):
    vc = g.bin.value_counts(normalize=True).reindex(range(len(edges) - 1), fill_value=0)
    print(f"BINCSV,{y}," + ",".join(f"{v:.4f}" for v in vc))
print("STDCSV,year,skill,k,n,raw,std,dedup_std")
rng = np.random.default_rng(0)
for y in sorted(it.year.unique()):
    m = (it.year == y).values
    g = it[m]
    keep = ~g.duplicated(["title", "employer"]).values
    for j, sid in enumerate(ids):
        col = M[m, j]
        raw = col.mean()
        df = pd.DataFrame(dict(b=g.bin.values, v=col, keep=keep))
        sb = df.groupby("b").v.mean().reindex(ref.index)
        std = float(np.nansum(sb.values * ref.values) / ref[sb.notna()].sum())
        sbd = df[df.keep].groupby("b").v.mean().reindex(ref.index)
        dstd = float(np.nansum(sbd.values * ref.values) / ref[sbd.notna()].sum())
        print(f"STDCSV,{y},{sid},{int(col.sum())},{int(m.sum())},{raw:.5f},{std:.5f},{dstd:.5f}")
print("EDGES," + ",".join(f"{e:.0f}" for e in edges))

# Does one employer carry a skill in a year? Share with each employer capped at 10 ads a year,
# and the largest employer's part of the ads that mention the skill.
print("CAPCSV,year,skill,k,capped_share,top_employer_part,employers")
for y in sorted(it.year.unique()):
    m = (it.year == y).values
    g = it[m].reset_index(drop=True)
    rank = g.groupby("employer").cumcount()
    capm = (rank < 10).values
    for j, sid in enumerate(ids):
        col = M[m, j]
        k = int(col.sum())
        if k == 0:
            continue
        emp = g.employer[col == 1].value_counts()
        print(f"CAPCSV,{y},{sid},{k},{col[capm].mean():.5f},{emp.iloc[0]/k:.4f},{len(emp)}")

# Swedish required, ad in English, entry level: raw, employer-capped, and without the year's largest employer.
print("SIGCSV,year,signal,raw,capped,without_top")
for y in sorted(it.year.unique()):
    g = it[it.year == y].reset_index(drop=True)
    capm = (g.groupby("employer").cumcount() < 10).values
    top = g.employer.value_counts().index[0]
    rest = (g.employer != top).values
    for name, v in [("sv_required", g.sv_req.astype(float)), ("ad_in_english", (g.ad_lang == "en").astype(float)),
                    ("entry", g.seniority.isin(classify.ENTRY).astype(float))]:
        print(f"SIGCSV,{y},{name},{v.mean():.4f},{v[capm].mean():.4f},{v[rest].mean():.4f}")
