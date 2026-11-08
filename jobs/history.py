"""Build the 10-year history table from JobTech's yearly bulk files.

  python -m jobs.history --years 2020-2026 --out data/history [--keep-zip]

For each year: download the zip (0.2-1.5 GB), stream every ad, keep tech ads only
(Data/IT occupation field, plus software-like titles elsewhere, flagged field_it=False),
extract features (skills, seniority, family, Swedish requirement...) and write
data/history/ads_<year>.parquet. The text itself is not kept.
"""
import argparse
import json
import os
import tempfile
import time

import pandas as pd

from . import jobtech
from .net import Net


def parse_years(s):
    if "-" in s:
        a, b = s.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(",")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2020-2026")
    ap.add_argument("--out", default="data/history")
    ap.add_argument("--keep-zip", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    net = Net(log_path=os.path.join(a.out, "net_log.jsonl"))
    tmp = tempfile.mkdtemp(prefix="jobtech_")
    stats = {}
    for y in parse_years(a.years):
        dest = os.path.join(a.out, f"ads_{y}.parquet")
        if os.path.exists(dest) and not a.force and y < time.gmtime().tm_year:
            print(f"{y}: cached")
            continue
        rows, files = [], []
        t0 = time.time()
        for name in jobtech.history_files(y):
            path = jobtech.download(net, name, tmp)
            if not path:
                continue
            files.append(name)
            n_lines = 0

            def counted(it):
                nonlocal n_lines
                for line in it:
                    n_lines += 1
                    yield line
            rows.extend(jobtech.history_rows(counted(jobtech.iter_jsonl_zip(path))))
            stats.setdefault(str(y), {})[name] = n_lines
            if not a.keep_zip:
                os.remove(path)
        if not rows:
            print(f"{y}: no data ({files})")
            continue
        df = pd.DataFrame(rows)
        df.to_parquet(dest, index=False)
        print(f"{y}: {len(df)} tech ads ({int(df.field_it.sum())} in Data/IT) from {files} in {time.time()-t0:.0f}s")
    json.dump(stats, open(os.path.join(a.out, "lines_per_file.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
