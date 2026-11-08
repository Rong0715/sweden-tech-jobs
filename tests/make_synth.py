"""Synthetic end-to-end data so build/analyze can be tested offline."""
import json, os, random, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jobs import jobtech
random.seed(1)
root = sys.argv[1]
os.makedirs(f"{root}/raw/2026-11-08", exist_ok=True); os.makedirs(f"{root}/history", exist_ok=True)
open(f"{root}/companies.csv","w").write("company,domain,tier,sector,sweden_sites,careers_url,ats,ats_key,evidence_url,notes\nSpotify,spotify.com,top,music,Stockholm,,lever,spotify,,\nAcme Scale,acme.io,scaleup,saas,Stockholm,,teamtailor,acme.teamtailor.com,,\n")
stacks = [["Java","Spring Boot","Kafka","Kubernetes","PostgreSQL"],["Python","PyTorch","machine learning","AWS","Docker"],
          ["C++","embedded","Linux","5G"],["Python","SQL","Airflow","BigQuery","dbt"],["Go","Kubernetes","Terraform","GCP","Prometheus"],["TypeScript","React","Node.js"]]
titles = ["Senior Backend Engineer","Junior Software Developer","Machine Learning Engineer","Data Engineer","Platform Engineer","Graduate Software Engineer","Systemutvecklare","Master Thesis: ML"]
def ad(i, src, comp):
    st = random.choice(stacks); t = random.choice(titles)
    return dict(source=src, company=comp, tier="", ext_id=i, title=t, location="Stockholm", country="Sweden", url=f"https://x/{i}",
                posted="2026-11-01", deadline="", description=f"We use {', '.join(st)}. " + random.choice(["3+ years of experience.","Swedish is a plus.","Du talar flytande svenska."]),
                department="", employment_type="", workplace="", in_sweden=True)
with open(f"{root}/raw/2026-11-08/ats.jsonl","w") as f:
    for i in range(300): f.write(json.dumps(ad(i,"lever" if i%2 else "teamtailor", "Spotify" if i%2 else "Acme Scale"))+"\n")
with open(f"{root}/raw/2026-11-08/jobtech.jsonl","w") as f:
    for i in range(600): f.write(json.dumps(ad(10000+i,"jobtech", random.choice(["Spotify AB","Foo Konsult AB","Academic Work Sweden AB","Bar Tech AB"])))+"\n")
for y in range(2016, 2027):
    lines = []
    for i in range(400):
        st = list(random.choice(stacks))
        if random.random() < (y-2015)/15: st.append("LLM")
        h = {"id": f"{y}-{i}", "headline": random.choice(titles), "description": {"text": "Vi söker. " + ", ".join(st)},
             "occupation_field": {"concept_id": "apaJ_2ja_LuF", "label": "Data/IT"}, "publication_date": f"{y}-05-01T00:00:00",
             "employer": {"name": "E"+str(i%40)}, "workplace_address": {"region": "Stockholms län"}}
        lines.append(json.dumps(h, ensure_ascii=False))
    pd.DataFrame(list(jobtech.history_rows(lines))).to_parquet(f"{root}/history/ads_{y}.parquet")
print("synth ok")
