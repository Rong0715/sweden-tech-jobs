# sweden-tech-jobs

A rerunnable dataset of tech job listings in Sweden, built to answer one question:
**which skills does the Swedish market pay for, how is that changing, and in what order
should a new graduate learn them?**

## Sources

| Source | What | How |
|---|---|---|
| JobTech JobSearch API (Arbetsförmedlingen, open data) | every live ad in the *Data/IT* and *Tekniskt arbete* occupation fields | `jobs/jobtech.py`, time windows split so each stays under the API's ~2,100-result cap |
| JobTech historical bulk files | every ad published 2016 to 2026 Q3 (yearly JSONL zips, ~9 GB) | `jobs/history.py`, streamed; only features are kept, not the text |
| Company career boards | ~250 employers (big tech offices, scaleups, banks, industrials, consultancies, public sector) | `jobs/adapters.py`, one adapter per ATS: Teamtailor (RSS), Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Personio, Workday, Eightfold, Deel, plus a cautious generic HTML fallback |

The employer list is `config/companies.csv` (tier, ATS, board key, evidence URL).
`python -m jobs.detect` fills in boards for rows marked `unknown`.

## Politeness

One client name, 1 request per second per host, robots.txt read for every host
(refusals logged in `net_log.jsonl`; documented public job APIs are logged but read),
no sign-ins, no forms, no bot-check workarounds, LinkedIn not touched.
`coverage.csv` lists every company with what was fetched or why it was skipped.

## Pipeline

```
python -m jobs.crawl   --out data/raw/<date>                      # snapshot
python -m jobs.build   --raw data/raw/<date> --out data/snapshots/<date>
python -m jobs.history --years 2016-2026 --out data/history       # once a month is plenty
python -m jobs.analyze --snapshot data/snapshots/<date> --history data/history --out data/analysis/<date>
```

GitHub Actions (`.github/workflows/crawl.yml`) runs this every Monday and on pushes to
`main`, and commits results to the `data` branch.

## Labels (rules, auditable)

- `jobs/skills.py`: ~75 skills as regexes; ambiguous words (Go, C, R) only count next to another tech term.
- `jobs/classify.py`: seniority (thesis / intern / graduate / junior / mid / senior, from title, then years of experience), role family, Swedish requirement, EU-only / clearance / visa signals, ad language.
- `tests/test_units.py` pins the tricky cases; `tests/make_synth.py` builds synthetic data with planted clusters and a planted trend for an end-to-end check.

## Analysis outputs (`data/analysis/<date>/`)

`demand.csv` (share of engineering ads per skill, by tier / family / level, Wilson 95% CI, plus a tier-weighted index),
`cooc.csv` and `clusters.csv` (NPMI co-occurrence, Louvain communities with seed stability),
`gap.csv` (entry vs senior log-odds with CI), `trends.csv` / `trend_fit.csv` / `market.csv`
(10-year shares, quasi-binomial logistic slopes), `platsbanken_bias.csv` (how much of each
company's own board also reaches Platsbanken), `roi.csv` (bootstrap rank intervals) and `route.json`.

## Known biases

- Platsbanken under-covers big tech and scaleups; `platsbanken_bias.csv` measures by how much.
- Recruiters and consultancies repost; recruiter ads are excluded from skill statistics.
- A skill mentioned is not a skill required; seniority from text is a heuristic.
- Learning cost and current level per skill in `skills.py` are judgement inputs to the ROI model, not data.
