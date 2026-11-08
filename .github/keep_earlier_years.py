"""Before a history rebuild overwrites trends/, keep the per-year rows for years it did not rebuild.

  python .github/keep_earlier_years.py <data/trends> <out/trends>

Rows go to <data/trends>/earlier/<file>.csv and are merged with what is already there. They were
labelled by whichever taxonomy was current when they were built, so treat them as background.
"""
import os
import sys

import pandas as pd

old_dir, new_dir = sys.argv[1], sys.argv[2]
for name in ("trends.csv", "market.csv"):
    old, new = os.path.join(old_dir, name), os.path.join(new_dir, name)
    if not (os.path.exists(old) and os.path.exists(new)):
        continue
    o, n = pd.read_csv(old), pd.read_csv(new)
    if "year" not in o or "year" not in n:
        continue
    keep = o[~o.year.isin(set(n.year))]
    if keep.empty:
        continue
    os.makedirs(os.path.join(old_dir, "earlier"), exist_ok=True)
    dst = os.path.join(old_dir, "earlier", name)
    if os.path.exists(dst):
        prev = pd.read_csv(dst)
        keep = pd.concat([prev[~prev.year.isin(set(keep.year))], keep], ignore_index=True)
    keep.sort_values(list(keep.columns[:2])).to_csv(dst, index=False)
    print(f"kept {keep.year.nunique()} earlier years of {name} in {dst}")
