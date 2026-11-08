"""Statistics on the snapshot + the 10-year history, and the learning route.

  python -m jobs.analyze --snapshot data/<date> --history data/history --out data/analysis/<date>

Outputs (CSV unless noted):
  demand.csv        share of engineering ads that mention each skill, overall, per tier, per role
                    family and per seniority, with Wilson 95% intervals; plus a tier-weighted index
  cooc.csv          skill pairs: co-count, lift, NPMI
  clusters.csv      skill communities (Louvain on the NPMI graph, 20 seeds), with stability
  gap.csv           entry vs senior: log odds ratio per skill with 95% interval
  trends.csv        per skill per year share in Data/IT ads, Wilson interval
  trend_fit.csv     quasi-binomial logistic slope per skill over the fit window, with 95% interval
  market.csv        per year: ad volume, Swedish-required share, entry share, AI-mention share
  platsbanken_bias.csv  per company: postings on its own ATS vs on Platsbanken
  roi.csv           ROI per skill with bootstrap rank interval
  route.json        dependency-ordered learning map
  summary.json      headline numbers
"""
import argparse
import glob
import heapq
import json
import math
import os

import networkx as nx
import numpy as np
import pandas as pd

from . import classify
from .skills import SKILLS

Z = 1.959964
TIER_W = {"top": 0.35, "scaleup": 0.25, "mid": 0.20, "consultancy": 0.10, "public": 0.05, "other": 0.05, "recruiter": 0.0}
AI_SET = {"llm", "rag", "agents", "aitools"}


def wilson(k, n):
    if n == 0:
        return (np.nan, np.nan, np.nan)
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return p, max(0, c - h), min(1, c + h)


def skill_matrix(df):
    ids = list(SKILLS)
    sets = df["skills"].fillna("").map(lambda s: set(s.split("|")) - {""})
    M = np.zeros((len(df), len(ids)), dtype=np.uint8)
    for i, s in enumerate(sets):
        for sid in s:
            if sid in SKILLS:
                M[i, ids.index(sid)] = 1
    return M, ids


def shares(M, ids, mask=None, weights=None):
    X = M if mask is None else M[mask]
    w = None if weights is None else (weights if mask is None else weights[mask])
    n = len(X)
    out = {}
    for j, sid in enumerate(ids):
        if w is None:
            k = int(X[:, j].sum())
            out[sid] = (k, n) + wilson(k, n)
        else:
            sw = w.sum()
            p = float((X[:, j] * w).sum() / sw) if sw else np.nan
            neff = (sw ** 2) / (w ** 2).sum() if sw else 0   # Kish effective n for the interval
            lo, hi = wilson(p * neff, neff)[1:] if neff else (np.nan, np.nan)
            out[sid] = (round(p * neff), neff, p, lo, hi)
    return out


def demand(df, M, ids):
    rows = []
    groups = [("all", None)]
    groups += [(f"tier:{t}", (df.tier == t).values) for t in sorted(df.tier.unique())]
    groups += [(f"family:{f}", (df.family == f).values) for f in sorted(df.family.unique())]
    groups += [("level:entry", df.entry.values), ("level:mid", (df.seniority == "mid").values),
               ("level:senior", (df.seniority == "senior").values)]
    w = df.tier.map(TIER_W).fillna(0.05).values.astype(float)
    tgt = df.family.isin(classify.TARGET_FAMILIES).values
    for name, mask in groups:
        sh = shares(M, ids, mask)
        for sid, (k, n, p, lo, hi) in sh.items():
            rows.append(dict(group=name, skill=sid, label=SKILLS[sid]["label"], k=k, n=n, share=p, lo=lo, hi=hi))
    for name, mask in [("weighted:target_families", tgt), ("weighted:target_entry", tgt & df.entry.values)]:
        sh = shares(M, ids, mask, w)
        for sid, (k, n, p, lo, hi) in sh.items():
            rows.append(dict(group=name, skill=sid, label=SKILLS[sid]["label"], k=k, n=round(n, 1), share=p, lo=lo, hi=hi))
    return pd.DataFrame(rows)


def cooc(M, ids, min_count):
    n = len(M)
    C = M.T.astype(np.int64) @ M.astype(np.int64)
    f = np.diag(C)
    rows = []
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            c = C[a, b]
            if c < min_count or f[a] == 0 or f[b] == 0:
                continue
            pab, pa, pb = c / n, f[a] / n, f[b] / n
            pmi = math.log(pab / (pa * pb))
            npmi = pmi / -math.log(pab)
            rows.append(dict(a=ids[a], b=ids[b], count=int(c), lift=pab / (pa * pb), npmi=npmi,
                             p_b_given_a=c / f[a], p_a_given_b=c / f[b]))
    return pd.DataFrame(rows)


def clusters(cc, M, ids, df, seeds=20, thr=0.08):
    G = nx.Graph()
    for r in cc.itertuples():
        if r.npmi > thr:
            G.add_edge(r.a, r.b, weight=r.npmi)
    if G.number_of_edges() == 0:
        return pd.DataFrame(), {}
    runs = [nx.community.louvain_communities(G, weight="weight", resolution=1.0, seed=s) for s in range(seeds)]
    nodes = list(G.nodes)
    co = {(u, v): 0 for u in nodes for v in nodes}
    for comms in runs:
        lab = {n: i for i, c in enumerate(comms) for n in c}
        for u in nodes:
            for v in nodes:
                co[(u, v)] += lab[u] == lab[v]
    best = max(runs, key=lambda c: nx.community.modularity(G, c, weight="weight"))
    mod = nx.community.modularity(G, best, weight="weight")
    prev = M.mean(0)
    rows = []
    for ci, comm in enumerate(sorted(best, key=lambda c: -sum(prev[ids.index(s)] for s in c))):
        comm = sorted(comm, key=lambda s: -prev[ids.index(s)])
        cols = [ids.index(s) for s in comm]
        hit = M[:, cols].sum(1) >= 2
        fam = df.family[hit].value_counts(normalize=True).head(3).round(2).to_dict()
        ent = float(df.entry[hit].mean()) if hit.any() else np.nan
        for s in comm:
            stab = np.mean([co[(s, t)] / seeds for t in comm if t != s]) if len(comm) > 1 else 1.0
            rows.append(dict(cluster=ci, skill=s, label=SKILLS[s]["label"], prevalence=float(prev[ids.index(s)]),
                             stability=round(float(stab), 2), ads_with_2plus=int(hit.sum()),
                             top_families=json.dumps(fam), entry_share=ent))
    return pd.DataFrame(rows), dict(modularity=mod, edges=G.number_of_edges(), nodes=G.number_of_nodes())


def gap(df, M, ids):
    e, s = df.entry.values, (df.seniority == "senior").values
    ne, ns = e.sum(), s.sum()
    rows = []
    for j, sid in enumerate(ids):
        a, b = M[e, j].sum() + 0.5, ne - M[e, j].sum() + 0.5
        c, d = M[s, j].sum() + 0.5, ns - M[s, j].sum() + 0.5
        lor = math.log((a / b) / (c / d))
        se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
        rows.append(dict(skill=sid, label=SKILLS[sid]["label"], entry_share=(a - .5) / max(ne, 1), senior_share=(c - .5) / max(ns, 1),
                         log_or=lor, lo=lor - Z * se, hi=lor + Z * se, n_entry=int(ne), n_senior=int(ns)))
    return pd.DataFrame(rows)


def logit_fit(years, k, n):
    """Aggregated-binomial logistic regression share ~ year by IRLS; quasi-binomial SE."""
    x = np.asarray(years, float) - np.mean(years)
    k, n = np.asarray(k, float), np.asarray(n, float)
    X = np.column_stack([np.ones_like(x), x])
    beta = np.array([math.log((k.sum() + .5) / (n.sum() - k.sum() + .5)), 0.0])
    for _ in range(50):
        eta = X @ beta
        p = 1 / (1 + np.exp(-eta))
        W = n * p * (1 - p)
        z = eta + (k - n * p) / np.maximum(W, 1e-9)
        XtW = X.T * W
        new = np.linalg.solve(XtW @ X, XtW @ z)
        if np.max(np.abs(new - beta)) < 1e-10:
            beta = new
            break
        beta = new
    p = 1 / (1 + np.exp(-(X @ beta)))
    W = n * p * (1 - p)
    cov = np.linalg.inv((X.T * W) @ X)
    pearson = np.sum((k - n * p) ** 2 / np.maximum(n * p * (1 - p), 1e-9))
    df_ = max(len(x) - 2, 1)
    phi = max(1.0, pearson / df_)
    se = math.sqrt(cov[1, 1] * phi)
    return beta[1], se, phi


def history(hist_dir, fit_from):
    files = sorted(glob.glob(os.path.join(hist_dir, "ads_*.parquet")))
    if not files:
        return None, None, None
    h = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    h = h[h.year.notna()]
    h["year"] = h.year.astype(int)
    it = h[h.field_it & h.family.isin(classify.ENG_FAMILIES)].copy()
    M, ids = skill_matrix(it)
    trows = []
    years = sorted(it.year.unique())
    for y in years:
        m = (it.year == y).values
        n = int(m.sum())
        for j, sid in enumerate(ids):
            k = int(M[m, j].sum())
            p, lo, hi = wilson(k, n)
            trows.append(dict(year=y, skill=sid, k=k, n=n, share=p, lo=lo, hi=hi))
    tr = pd.DataFrame(trows)
    frows = []
    for sid, g in tr[tr.year >= fit_from].groupby("skill"):
        g = g[g.n > 0]
        if len(g) < 3 or g.k.sum() < 20:
            continue
        b, se, phi = logit_fit(g.year, g.k, g.n)
        first, last = g.iloc[0], g.iloc[-1]
        frows.append(dict(skill=sid, label=SKILLS[sid]["label"], slope=b, lo=b - Z * se, hi=b + Z * se, overdispersion=phi,
                          share_first=first.share, share_last=last.share, year_first=int(first.year), year_last=int(last.year),
                          k_last=int(last.k), growth_3y=math.exp(3 * b)))
    fit = pd.DataFrame(frows)
    mrows = []
    ai_cols = [ids.index(s) for s in AI_SET]
    for y in years:
        allm = h[(h.year == y)]
        itm = it[it.year == y]
        m = (it.year == y).values
        mrows.append(dict(year=y, tech_ads=len(allm), it_eng_ads=len(itm),
                          vacancies=int(itm.vacancies.fillna(1).clip(upper=50).sum()),
                          sv_required=itm.sv_req.mean(), ad_in_english=(itm.ad_lang == "en").mean(),
                          entry_share=itm.seniority.isin(classify.ENTRY).mean(),
                          ai_mention=float((M[m][:, ai_cols].sum(1) > 0).mean()) if m.any() else np.nan,
                          llm_mention=float(M[m, ids.index("llm")].mean()) if m.any() else np.nan,
                          median_skills=float(np.median(M[m].sum(1))) if m.any() else np.nan,
                          employers=itm.employer.nunique()))
    return tr, fit, pd.DataFrame(mrows)


def platsbanken_bias(df_all):
    """For companies with an ATS board, how many of their Swedish postings are also on Platsbanken."""
    rows = []
    for comp, g in df_all.groupby("company"):
        srcs = g.sources.str.split("|")
        ats = srcs.map(lambda s: any(x != "jobtech" for x in s))
        if ats.sum() == 0:
            continue
        both = srcs.map(lambda s: "jobtech" in s and any(x != "jobtech" for x in s))
        only_pb = srcs.map(lambda s: s == ["jobtech"])
        rows.append(dict(company=comp, tier=g.tier.iloc[0], ats_postings=int(ats.sum()), also_on_platsbanken=int(both.sum()),
                         platsbanken_only=int(only_pb.sum()), share_on_platsbanken=both.sum() / ats.sum()))
    return pd.DataFrame(rows)


def roi(df, M, ids, fit, boots=300, seed=0):
    tgt = df.family.isin(classify.TARGET_FAMILIES).values
    w = df.tier.map(TIER_W).fillna(0.05).values.astype(float)
    entry = df.entry.values
    growth = {r.skill: min(2.0, max(0.5, r.growth_3y)) for r in fit.itertuples()} if fit is not None and len(fit) else {}
    dependents = {s: [t for t, d in SKILLS.items() if s in d["pre"]] for s in SKILLS}

    def score(idx):
        X, ww, tg, en = M[idx], w[idx], tgt[idx], entry[idx]
        a = tg
        b = tg & en
        D = (X[a] * ww[a, None]).sum(0) / max(ww[a].sum(), 1e-9)
        E = (X[b] * ww[b, None]).sum(0) / max(ww[b].sum(), 1e-9) if b.any() else D
        val = {}
        for j, s in enumerate(ids):
            val[s] = (0.5 * D[j] + 0.5 * E[j]) * growth.get(s, 1.0)
        out = {}
        for s in ids:
            d = SKILLS[s]
            unlock = 0.3 * sum(val[t] * (1 - SKILLS[t]["rong"]) for t in dependents[s])
            gapv = 1 - d["rong"]
            out[s] = ((val[s] + unlock) * gapv) / (d["cost"] * gapv + 10) * 100
        return out, D, E

    base, D, E = score(np.arange(len(df)))
    rng = np.random.default_rng(seed)
    ranks = {s: [] for s in ids}
    for _ in range(boots):
        idx = rng.integers(0, len(df), len(df))
        sc, _, _ = score(idx)
        order = sorted(ids, key=lambda s: -sc[s])
        for r, s in enumerate(order, 1):
            ranks[s].append(r)
    rows = []
    for j, s in enumerate(ids):
        rk = np.array(ranks[s])
        rows.append(dict(skill=s, label=SKILLS[s]["label"], roi=base[s], demand_target=D[j], demand_entry=E[j],
                         growth_3y=growth.get(s, np.nan), rong_level=SKILLS[s]["rong"], cost_h=SKILLS[s]["cost"],
                         rank_median=float(np.median(rk)), rank_p05=float(np.percentile(rk, 5)),
                         rank_p95=float(np.percentile(rk, 95)), site=SKILLS[s]["site"], prereq="|".join(SKILLS[s]["pre"])))
    return pd.DataFrame(rows).sort_values("roi", ascending=False)


def route(r, top=22):
    """Topological order of the top-ROI skills plus their prerequisites, highest ROI first among ready ones."""
    roi_of = dict(zip(r.skill, r.roi))
    want = set(r[r.rong_level < 0.9].head(top).skill)
    stack = list(want)
    while stack:
        s = stack.pop()
        for p in SKILLS[s]["pre"]:
            if p not in want and SKILLS[p]["rong"] < 0.9:
                want.add(p)
                stack.append(p)
    indeg = {s: sum(p in want for p in SKILLS[s]["pre"]) for s in want}
    heap = [(-roi_of[s], s) for s in want if indeg[s] == 0]
    heapq.heapify(heap)
    order, depth = [], {}
    while heap:
        _, s = heapq.heappop(heap)
        depth[s] = 1 + max([depth[p] for p in SKILLS[s]["pre"] if p in depth] or [0])
        order.append(s)
        for t in want:
            if s in SKILLS[t]["pre"]:
                indeg[t] -= 1
                if indeg[t] == 0:
                    heapq.heappush(heap, (-roi_of[t], t))
    return [dict(step=i + 1, skill=s, label=SKILLS[s]["label"], layer=depth[s], roi=round(roi_of[s], 3),
                 needs=[p for p in SKILLS[s]["pre"] if p in want], site=SKILLS[s]["site"],
                 rong_level=SKILLS[s]["rong"], cost_h=SKILLS[s]["cost"]) for i, s in enumerate(order)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--history", default="data/history")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fit-from", type=int, default=2020)
    a = ap.parse_args()
    out = a.out or os.path.join("data", "analysis", os.path.basename(a.snapshot.rstrip("/")))
    os.makedirs(out, exist_ok=True)
    df_all = pd.read_parquet(os.path.join(a.snapshot, "listings.parquet"))
    pb = platsbanken_bias(df_all)
    pb.to_csv(os.path.join(out, "platsbanken_bias.csv"), index=False)
    df = df_all[df_all.family.isin(classify.ENG_FAMILIES) & (df_all.tier != "recruiter")].reset_index(drop=True)
    df["entry"] = df["entry"].astype(bool)
    M, ids = skill_matrix(df)
    dem = demand(df, M, ids)
    dem.to_csv(os.path.join(out, "demand.csv"), index=False)
    cc = cooc(M, ids, min_count=max(5, int(0.005 * len(df))))
    cc.to_csv(os.path.join(out, "cooc.csv"), index=False)
    cl, clmeta = clusters(cc, M, ids, df)
    cl.to_csv(os.path.join(out, "clusters.csv"), index=False)
    gp = gap(df, M, ids)
    gp.to_csv(os.path.join(out, "gap.csv"), index=False)
    tr, fit, mk = history(a.history, a.fit_from)
    if tr is not None:
        tr.to_csv(os.path.join(out, "trends.csv"), index=False)
        fit.to_csv(os.path.join(out, "trend_fit.csv"), index=False)
        mk.to_csv(os.path.join(out, "market.csv"), index=False)
    r = roi(df, M, ids, fit)
    r.to_csv(os.path.join(out, "roi.csv"), index=False)
    rt = route(r)
    json.dump(rt, open(os.path.join(out, "route.json"), "w"), indent=1, ensure_ascii=False)
    summ = dict(engineering_ads=len(df), all_listings=len(df_all), companies=int(df.company.nunique()),
                entry_ads=int(df.entry.sum()), by_seniority=df.seniority.value_counts().to_dict(),
                by_tier=df.tier.value_counts().to_dict(), clusters=clmeta,
                platsbanken_share_ats=(float(pb.also_on_platsbanken.sum() / pb.ats_postings.sum()) if len(pb) else None))
    json.dump(summ, open(os.path.join(out, "summary.json"), "w"), indent=1, ensure_ascii=False, default=str)
    print(json.dumps(summ, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
