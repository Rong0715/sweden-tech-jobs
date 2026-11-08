# sweden-tech-jobs

A rerunnable dataset of tech job listings in Sweden, built to answer one question:
**which skills does the Swedish market ask for, how is that changing, and in what order is
it worth learning them?**

Each weekly run collects the live listings from Arbetsförmedlingen's open data and from
about 200 employers' own career boards, labels every ad with skills, seniority and role
family, and publishes aggregated statistics: skill demand with confidence intervals, skill
clusters, the entry-level vs senior gap, ten-year trends and a dependency-ordered learning map.

## How it works

| Step | Module | What it does |
|---|---|---|
| Live listings | `jobs/jobtech.py` | JobTech JobSearch API (Arbetsförmedlingen, open data), occupation fields *Data/IT* and *Tekniskt arbete*. Date windows are split recursively so each query stays under the API's result cap. |
| Employer boards | `jobs/adapters.py` | One adapter per applicant-tracking system, not per company: Teamtailor (RSS), Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Personio, Workday, Eightfold, Deel, plus a cautious HTML fallback. The employer list is `config/companies.csv`. |
| Board discovery | `jobs/detect.py` | Fills in the ATS for employers marked `unknown` from careers-page fingerprints and public board APIs. |
| Build | `jobs/build.py` | Normalises sources into one table, matches employers to tiers, labels each ad, and de-duplicates the same job posted on Platsbanken and on the employer's own board. |
| History | `jobs/history.py` | Streams JobTech's yearly bulk files (2016 onwards) and keeps per-ad features only. |
| Analysis | `jobs/analyze.py` | The statistics below. |

Labels are rules, so every decision can be audited:

- `jobs/skills.py`: about 75 skills as regular expressions. Ambiguous words (Go, C, R) only count next to another technical term.
- `jobs/classify.py`: seniority (thesis, intern, graduate, junior, mid, senior; from the title, then years of experience), role family, Swedish-language requirement, EU-only, security-clearance and visa signals, ad language.
- `tests/test_units.py` pins the tricky cases; `tests/make_synth.py` builds synthetic data with planted clusters and a planted trend as an end-to-end check.

## Outputs

The `data` branch holds aggregated statistics only, one folder per run.

- `analysis/<date>/demand.csv`: share of engineering ads mentioning each skill, by employer tier, role family and seniority, with Wilson 95% intervals and a tier-weighted index.
- `analysis/<date>/cooc.csv`, `clusters.csv`: NPMI co-occurrence and Louvain skill communities, with stability across seeds.
- `analysis/<date>/gap.csv`: entry-level vs senior log odds ratio per skill, with 95% intervals.
- `trends/trends.csv`, `trend_fit.csv`, `market.csv`: yearly skill shares since 2016 and quasi-binomial logistic slopes with intervals.
- `analysis/<date>/platsbanken_bias.csv`: how much of each employer's own board also reaches Platsbanken.
- `analysis/<date>/roi.csv`, `route.json`: skills ranked by demand, growth and learning cost, with bootstrap rank intervals, in prerequisite order.
- `logs/<date>/coverage.csv`: every employer, what was fetched or why it was skipped.

## Running it

```
pip install -r requirements.txt
python tests/test_units.py

python -m jobs.crawl   --out data/raw/<date>
python -m jobs.build   --raw data/raw/<date> --out data/snapshots/<date>
python -m jobs.history --years 2016-2026 --out data/history
python -m jobs.analyze --history data/history --out data/trends
python -m jobs.analyze --snapshot data/snapshots/<date> --history data/trends \
                       --out data/analysis/<date> --profile config/profile.example.json
```

`--profile` is optional. It gives a learner's current level per skill (0 to 1), so the
ranking favours what is still missing; `config/profile.example.json` shows the format.

GitHub Actions runs the crawl every Monday (`.github/workflows/crawl.yml`) and rebuilds the
history monthly (`history.yml`).

## Data ethics

- **robots.txt is respected for every host,** matched as RFC 9309 specifies (longest rule wins; an unreachable robots.txt means stay away). Disallowed URLs are not fetched; each refusal is logged with the rule that caused it in `logs/<date>/net_log.jsonl`.
- At most one request per second per host, one identifiable client name with a link to this repository, retries with back-off.
- Only public job listings: no sign-ins, no forms, no bot-check workarounds. LinkedIn is not touched.
- **Ad text is never stored in the repository or in public artifacts.** It is read in memory to compute labels and then dropped; only labels and aggregated counts are kept. Row-level listings without text are kept as a 14-day workflow artifact for debugging.
- JobTech data is open data published by Arbetsförmedlingen.

## Known biases

- Platsbanken under-covers big tech and scaleups; `platsbanken_bias.csv` measures by how much. Some large employers (for example Apple, Meta, IBM, SAP) run career sites that no adapter covers yet and are not in the employer list.
- Recruiters and consultancies repost; recruiter ads are excluded from skill statistics.
- A skill mentioned is not a skill required, and seniority from text is a heuristic.
- Learning costs in `skills.py` are judgement inputs to the ranking, not data.
