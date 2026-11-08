"""Statistics on the snapshot + the yearly history, and the learning route.

  python -m jobs.analyze --snapshot data/snapshots/<date> --history data/history --out data/analysis/<date>
  python -m jobs.analyze --history data/history --out data/trends        # trends only

Outputs (CSV unless noted):
  demand.csv        share of engineering ads that mention each skill, overall, per tier, per role
                    family and per seniority, with Wilson 95% intervals; plus a tier-weighted index
  cooc.csv          skill pairs: co-count, lift, NPMI
  clusters.csv      skill communities (Louvain on the NPMI graph, 20 seeds), with stability
  gap.csv           entry vs senior: log odds ratio per skill with 95% interval
                    (cohort "entry" = all early-career ads, "jobs" = graduate and junior only)
  robust.csv        demand shares with an employer-resampled interval, employer concentration and a
                    per-employer cap, for all / target families / top+scaleup / graduate+junior ads
  signals.csv       Swedish requirement, EU-only, clearance, visa and English-ad shares by tier and level
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


def _company_boot(comp, reps, seed):
    """Weights for a bootstrap that resamples employers, not ads: ads from one employer are not independent."""
    codes, uniq = pd.factorize(comp)
    rng = np.random.default_rng(seed)
    W = rng.multinomial(len(uniq), np.full(len(uniq), 1 / len(uniq)), size=reps).astype(float)
    return codes, len(uniq), W


def robust(df, M, ids, reps=400, cap=10, seed=7):
    """Checks on demand shares that the Wilson interval ignores.

    boot_lo/boot_hi: 95% interval from resampling employers (ads from one employer move together).
    n_companies, top_company, top_share: how many employers mention the skill and how much of the
    count comes from the single largest one. share_cap: share when each employer counts for at most
    `cap` ads, so one big poster cannot carry a skill."""
    groups = [("all", np.ones(len(df), bool)),
              ("target_families", df.family.isin(classify.TARGET_FAMILIES).values),
              ("top_scaleup", df.tier.isin(["top", "scaleup"]).values),
              ("graduate_junior", df.seniority.isin(["graduate", "junior"]).values)]
    rows = []
    for name, mask in groups:
        d, X = df[mask], M[mask].astype(float)
        if len(d) == 0:
            continue
        codes, nc, W = _company_boot(d.company.values, reps, seed)
        K = np.zeros((nc, X.shape[1])); np.add.at(K, codes, X)
        N = np.bincount(codes, minlength=nc).astype(float)
        boot = (W @ K) / (W @ N)[:, None]
        wcap = np.minimum(1.0, cap / N)[codes]
        capped = (X * wcap[:, None]).sum(0) / wcap.sum()
        names = pd.factorize(d.company.values)[1]
        for j, sid in enumerate(ids):
            k = int(K[:, j].sum())
            p, lo, hi = wilson(k, len(d))
            top = int(K[:, j].argmax()) if k else None
            rows.append(dict(group=name, skill=sid, label=SKILLS[sid]["label"], k=k, n=len(d), share=p, lo=lo, hi=hi,
                             boot_lo=float(np.quantile(boot[:, j], .025)), boot_hi=float(np.quantile(boot[:, j], .975)),
                             n_companies=int((K[:, j] > 0).sum()), top_company=names[top] if k else "",
                             top_share=float(K[top, j] / k) if k else np.nan, share_cap=float(capped[j]),
                             small_n=len(d) < 100 or k < 10))
    return pd.DataFrame(rows)


def gap_boot(df, M, ids, levels, reps=400, seed=11):
    """Employer-resampled 95% interval for the early-career vs senior log odds ratio."""
    e = df.seniority.isin(levels).values if levels else df.entry.values
    s = (df.seniority == "senior").values
    m = e | s
    d, X, e, s = df[m], M[m].astype(float), e[m], s[m]
    codes, nc, W = _company_boot(d.company.values, reps, seed)
    def agg(mask):
        K = np.zeros((nc, X.shape[1])); np.add.at(K, codes[mask], X[mask])
        return K, np.bincount(codes[mask], minlength=nc).astype(float)
    Ke, Ne = agg(e); Ks, Ns = agg(s)
    ke, ne, ks, ns = W @ Ke, W @ Ne, W @ Ks, W @ Ns
    lor = np.log(((ke + .5) / (ne[:, None] - ke + .5)) / ((ks + .5) / (ns[:, None] - ks + .5)))
    return np.quantile(lor, .025, axis=0), np.quantile(lor, .975, axis=0), (Ke > 0).sum(0)


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


def gap(df, M, ids, cohort="entry", levels=None):
    """Log odds ratio of each skill, an early-career cohort vs senior ads.

    cohort "entry" is every early-career ad (thesis, intern, graduate, junior); "jobs" drops
    thesis projects and internships, which lean towards research topics (ML, 5G) and would
    otherwise make those look like entry-level skills."""
    e = df.seniority.isin(levels).values if levels else df.entry.values
    s = (df.seniority == "senior").values
    ne, ns = e.sum(), s.sum()
    rows = []
    for j, sid in enumerate(ids):
        a, b = M[e, j].sum() + 0.5, ne - M[e, j].sum() + 0.5
        c, d = M[s, j].sum() + 0.5, ns - M[s, j].sum() + 0.5
        lor = math.log((a / b) / (c / d))
        se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
        rows.append(dict(skill=sid, label=SKILLS[sid]["label"], entry_share=(a - .5) / max(ne, 1), senior_share=(c - .5) / max(ns, 1),
                         log_or=lor, lo=lor - Z * se, hi=lor + Z * se, n_entry=int(ne), n_senior=int(ns), cohort=cohort))
    return pd.DataFrame(rows)


SIGNALS = ["swedish_required", "swedish_plus", "eu_only", "clearance", "visa_ok"]


def signals(df):
    """Share of engineering ads with each hiring signal, overall and by tier and seniority, with Wilson intervals."""
    d = df.copy()
    d["english_ad"] = d["ad_lang"].eq("en")
    rows = []
    groups = [("all", d)] + [(f"tier:{t}", g) for t, g in d.groupby("tier")] + \
             [(f"level:{l}", g) for l, g in d.groupby(d.seniority.map(lambda x: "entry" if x in classify.ENTRY else x))]
    for name, g in groups:
        for col in SIGNALS + ["english_ad"]:
            if col not in g:
                continue
            k, n = int(g[col].fillna(False).astype(bool).sum()), len(g)
            p, lo, hi = wilson(k, n)
            rows.append(dict(group=name, signal=col, k=k, n=n, share=p, lo=lo, hi=hi))
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


def history_tables(hist_dir):
    """Per-year skill counts and market figures from the history feature tables.

    Reads ads_<year>.parquet when present (built by jobs.history); otherwise falls back to
    already aggregated trends.csv / market.csv in the same folder, which is what the public
    data branch carries.
    """
    files = sorted(glob.glob(os.path.join(hist_dir, "ads_*.parquet")))
    if not files:
        t, m = os.path.join(hist_dir, "trends.csv"), os.path.join(hist_dir, "market.csv")
        if os.path.exists(t):
            return pd.read_csv(t), (pd.read_csv(m) if os.path.exists(m) else None)
        return None, None
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
    return tr, pd.DataFrame(mrows)


def fit_trends(tr, fit_from):
    """Quasi-binomial logistic slope per skill over the years from fit_from on."""
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
    return pd.DataFrame(frows)


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


LEVEL = {}   # learner's current level per skill, 0..1; filled from --profile


def load_profile(path):
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        lv = json.load(f).get("levels", {})
    unknown = set(lv) - set(SKILLS)
    if unknown:
        raise SystemExit(f"profile has unknown skill ids: {sorted(unknown)}")
    return {k: min(1.0, max(0.0, float(v))) for k, v in lv.items()}


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
            unlock = 0.3 * sum(val[t] * (1 - LEVEL.get(t, 0.0)) for t in dependents[s])
            gapv = 1 - LEVEL.get(s, 0.0)
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
                         growth_3y=growth.get(s, np.nan), level=LEVEL.get(s, 0.0), cost_h=SKILLS[s]["cost"],
                         rank_median=float(np.median(rk)), rank_p05=float(np.percentile(rk, 5)),
                         rank_p95=float(np.percentile(rk, 95)), site=SKILLS[s]["site"], prereq="|".join(SKILLS[s]["pre"])))
    return pd.DataFrame(rows).sort_values("roi", ascending=False)


def route(r, top=22):
    """Topological order of the top-ROI skills plus their prerequisites, highest ROI first among ready ones."""
    roi_of = dict(zip(r.skill, r.roi))
    want = set(r[r.level < 0.9].head(top).skill)
    stack = list(want)
    while stack:
        s = stack.pop()
        for p in SKILLS[s]["pre"]:
            if p not in want and LEVEL.get(p, 0.0) < 0.9:
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
                 level=LEVEL.get(s, 0.0), cost_h=SKILLS[s]["cost"]) for i, s in enumerate(order)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None, help="snapshot folder from jobs.build; omit to compute trends only")
    ap.add_argument("--history", default="data/history")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fit-from", type=int, default=2020)
    ap.add_argument("--profile", default=None,
                    help="JSON with a learner's current level per skill (see config/profile.example.json); "
                         "without it every skill counts as not yet learned")
    a = ap.parse_args()
    LEVEL.update(load_profile(a.profile))
    if not a.snapshot and not a.out:
        ap.error("--out is required without --snapshot")
    out = a.out or os.path.join("data", "analysis", os.path.basename(a.snapshot.rstrip("/")))
    os.makedirs(out, exist_ok=True)
    tr, mk = history_tables(a.history)
    fit = fit_trends(tr, a.fit_from) if tr is not None else None
    if tr is not None:
        tr.to_csv(os.path.join(out, "trends.csv"), index=False)
        fit.to_csv(os.path.join(out, "trend_fit.csv"), index=False)
        if mk is not None:
            mk.to_csv(os.path.join(out, "market.csv"), index=False)
    if not a.snapshot:
        print(f"trends for {tr.year.nunique() if tr is not None else 0} years written to {out}")
        return
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
    parts = []
    for cohort, levels in [("entry", None), ("jobs", ["graduate", "junior"])]:
        g = gap(df, M, ids, cohort, levels)
        g["boot_lo"], g["boot_hi"], g["entry_companies"] = gap_boot(df, M, ids, levels)
        parts.append(g)
    gp = pd.concat(parts, ignore_index=True)
    gp.to_csv(os.path.join(out, "gap.csv"), index=False)
    robust(df, M, ids).to_csv(os.path.join(out, "robust.csv"), index=False)
    signals(df).to_csv(os.path.join(out, "signals.csv"), index=False)
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
