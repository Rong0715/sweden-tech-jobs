# sweden-tech-jobs

A rerunnable dataset of tech job listings in Sweden, built to answer one question:
**which skills does the Swedish market ask for, how is that changing, and in what order is
it worth learning them?**

Each weekly run collects the live listings from Arbetsförmedlingen's open data and from
about 200 employers' own career boards, labels every ad with skills, seniority and role
family, and publishes aggregated statistics: skill demand with confidence intervals, skill
clusters, the entry-level vs senior gap, yearly trends since 2020 and a dependency-ordered learning map.

## How it works

| Step | Module | What it does |
|---|---|---|
| Live listings | `jobs/jobtech.py` | JobTech JobSearch API (Arbetsförmedlingen, open data), occupation fields *Data/IT* and *Tekniskt arbete*. Date windows are split recursively so each query stays under the API's result cap. |
| Employer boards | `jobs/adapters.py` | One adapter per applicant-tracking system, not per company: Teamtailor (RSS), Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Personio, Workday, Eightfold, Deel, plus a cautious HTML fallback. The employer list is `config/companies.csv`. |
| Board discovery | `jobs/detect.py` | Fills in the ATS for employers marked `unknown` from careers-page fingerprints and public board APIs. |
| Build | `jobs/build.py` | Normalises sources into one table, matches employers to tiers, labels each ad, and de-duplicates the same job posted on Platsbanken and on the employer's own board. |
| History | `jobs/history.py` | Streams JobTech's yearly bulk files (2020 onwards by default; any year from 2016 can be built) and keeps per-ad features only. |
| Analysis | `jobs/analyze.py` | The statistics below. |

Labels are rules, so every decision can be audited:

- `jobs/skills.py`: about 75 skills as regular expressions. Ambiguous words (Go, C, R) only count next to another technical term.
- `jobs/classify.py`: seniority (thesis, intern, graduate, junior, mid, senior; from the title, then years of experience), role family, Swedish-language requirement, EU-only, security-clearance and visa signals, ad language.
- `tests/test_units.py` pins the tricky cases; `tests/make_synth.py` builds synthetic data with planted clusters and a planted trend as an end-to-end check.

## How accurate the labels are

Two blind reviewers read ads in full and listed the skills each one asks for; their labels were
compared with the tagger's. Intervals are Wilson 95%.

| Round | Ads | Skill precision | Skill recall | Ads labelled software that are software jobs |
|---|---|---|---|---|
| 1, tagger v1 (used to tune v2) | 33 | 0.885 (0.820–0.929) | 0.800 (0.728–0.857) | 19/33 |
| 2, tagger v2, held out | 34 | 0.925 (0.885–0.952) | 0.914 (0.872–0.943) | 30/34 |

- Weakest skills in round 2: system design (2 of 8 tags correct, so its share is overstated
  roughly 1.5 to 3 times), Docker (5 of 9 mentions found), security (9 right, 3 wrong, 4 missed).
- Swedish-required agrees with reviewers on 29/34 ads, ad language on 34/34.
- Of 30 ads the role filter dropped as "other engineering", reviewers judged 5 to be software
  jobs (17%, 7–34%), 4 of them borderline (test leads, system configuration). Applied to all
  dropped ads, the filter misses roughly 140 to 660 software ads next to 2,457 kept.

## Outputs

The `data` branch holds aggregated statistics only, one folder per run.

- `analysis/<date>/demand.csv`: share of engineering ads mentioning each skill, by employer tier, role family and seniority, with Wilson 95% intervals and a tier-weighted index.
- `analysis/<date>/cooc.csv`, `clusters.csv`: NPMI co-occurrence and Louvain skill communities, with stability across seeds.
- `analysis/<date>/gap.csv`: entry-level vs senior log odds ratio per skill, with 95% intervals; once for all early-career ads and once for graduate and junior jobs only (thesis projects and internships excluded).
- `analysis/<date>/robust.csv`: the same shares with an interval that resamples employers rather than ads, how many employers mention each skill, how much comes from the largest one, and the share when no employer counts for more than 10 ads.
- `analysis/<date>/signals.csv`: share of ads that require Swedish, are EU-only, need security clearance, mention visa sponsorship or are written in English, by tier and level.
- `trends/trends.csv`, `trend_fit.csv`, `market.csv`: yearly skill shares since 2020 and quasi-binomial logistic slopes with intervals. Years built earlier (2016 to 2019) are kept in `trends/earlier/` as background.
- `analysis/<date>/platsbanken_bias.csv`: how much of each employer's own board also reaches Platsbanken.
- `analysis/<date>/roi.csv`, `route.json`: skills ranked by demand, growth and learning cost, with bootstrap rank intervals, in prerequisite order.
- `logs/<date>/coverage.csv`: every employer, what was fetched or why it was skipped.

## Running it

```
pip install -r requirements.txt
python tests/test_units.py

python -m jobs.crawl   --out data/raw/<date>
python -m jobs.build   --raw data/raw/<date> --out data/snapshots/<date>
python -m jobs.history --years 2020-2026 --out data/history
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
- A few large employers post many similar ads (Saab, Ericsson); `robust.csv` shows when one employer carries a skill.
- Recruiters and consultancies repost; recruiter ads are excluded from skill statistics.
- A skill mentioned is not a skill required, and seniority from text is a heuristic.
- In the yearly history, 2022 reads high for almost every skill and 2023 low. 2022 ads are longer, but the jump survives
  standardising for ad length (`.github/diag_trends.py`), so read multi-year slopes, not single-year changes.
- Learning costs in `skills.py` are judgement inputs to the ranking, not data.
