"""Draw a reproducible sample of engineering ads for checking the skill tagger by hand.

  python -m jobs.sample --snapshot data/snapshots/<date> --n 40 --seed 20261108

Prints one line per ad: id, link to the public ad, title, employer and the skills the tagger
found. Someone then reads each ad at its link, lists the skills it asks for without looking at
the tagger column, and the two lists give precision and recall. No ad text is printed.
"""
import argparse

import pandas as pd

from . import classify


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=20261108)
    a = ap.parse_args()
    df = pd.read_parquet(f"{a.snapshot}/listings.parquet")
    df = df[df.family.isin(classify.ENG_FAMILIES) & (df.tier != "recruiter") & df.url.fillna("").str.startswith("https://")]
    s = df.sample(n=min(a.n, len(df)), random_state=a.seed)
    print("TAGGER_SAMPLE_BEGIN")
    print(s[["uid", "source", "url", "title", "company", "family", "seniority", "skills"]].to_csv(index=False), end="")
    print("TAGGER_SAMPLE_END")


if __name__ == "__main__":
    main()
