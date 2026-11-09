import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jobs import skills, classify, adapters

def ex(t): return set(skills.extract(t))

def test_skills():
    assert {"python","k8s","kafka","go"} <= ex("We use Python, Go and Kafka on Kubernetes.")
    assert "go" not in ex("Ready to go the extra mile? Go for it")
    assert "c" in ex("Strong C and C++ skills, Python is a plus") and "cpp" in ex("C++")
    assert "c" not in ex("C-level stakeholders. Category C.")
    assert "rest" not in ex("for the rest of the team") and "rest" in ex("design REST APIs")
    assert "java" in ex("Java 21") and "java" not in ex("JavaScript only") and "javascript" in ex("JavaScript")
    assert "r_lang" in ex("Python or R, SQL") and "r_lang" not in ex("R&D department")
    assert "5g" in ex("5G RAN baseband") and "5g" not in ex("she ran fast")
    assert "llm" in ex("experience with LLMs and RAG") and "rag" in ex("experience with LLMs and RAG")
    assert "spark" not in ex("spark curiosity") and "spark" in ex("Apache Spark")

def test_seniority():
    assert classify.seniority("Senior Backend Engineer")[0] == "senior"
    assert classify.seniority("Master Thesis: Distributed tracing")[0] == "thesis"
    assert classify.seniority("Examensarbete inom AI")[0] == "thesis"
    assert classify.seniority("Graduate Software Engineer 2027")[0] == "graduate"
    assert classify.seniority("Backendutvecklare", "Du har minst 5 års erfarenhet av Java")[0] == "senior"
    assert classify.seniority("Software Engineer", "1-2 years of experience")[0] == "junior"
    assert classify.seniority("Software Engineer", "")[0] == "mid"
    assert classify.years_required("at least 3 years of professional experience") == 3

def test_family_signals():
    assert classify.role_family("Machine Learning Engineer") == "ml_ai"
    assert classify.role_family("Systemutvecklare Java") == "software"
    assert classify.role_family("Platform Engineer") == "platform"
    assert classify.role_family("IT-tekniker") in ("it_ops", "platform")
    s = classify.signals("Du talar och skriver flytande svenska och engelska.")
    assert s["swedish_required"] and s["ad_lang"] in ("sv", "")
    s = classify.signals("Swedish is a plus. We offer visa sponsorship and relocation support.")
    assert not s["swedish_required"] and s["visa_ok"]
    assert classify.signals("Applicants must be EU citizens")["eu_only"]
    assert classify.signals("Tjänsten kräver säkerhetsprövning")["clearance"]

class FakeNet:
    def __init__(self, data): self.data = data
    def get(self, url, **kw): return self.data.get(url)
    def log(self, **kw): pass

def test_lever_fixture():
    d = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "lever_spotify.json")))
    net = FakeNet({"https://api.lever.co/v0/postings/spotify": d})
    posts, ok = adapters.lever(net, {"company": "Spotify", "ats_key": "spotify", "tier": "top"})
    assert ok and len(posts) == 1
    p = posts[0]
    assert p["in_sweden"] and p["title"] == "AV Engineer - Platform" and "Q-SYS" in p["description"]
    assert p["posted"].startswith("2026")

def test_rss():
    xml = open(os.path.join(os.path.dirname(__file__), "fixtures", "teamtailor.rss")).read()
    class N(FakeNet):
        def get(self, url, **kw): return xml
    posts, ok = adapters.teamtailor(N({}), {"company": "X", "ats_key": "x.teamtailor.com"})
    assert ok and len(posts) == 2 and posts[0]["in_sweden"] and not posts[1]["in_sweden"], posts
    assert "Kubernetes" in posts[0]["description"]

def test_false_friends():
    from jobs.skills import extract as ex
    no = {"Du rapporterar till närmaste chef": "ansible", "Our team is embedded in the product org": "embedded",
          "Hantering av containers i hamnen": "docker", "SWIFT payments and ISO 20022": "swift",
          "We build consensus across teams": "distributed", "scalable solutions for customers": "sysdesign",
          "Inspect rust and corrosion on steel": "rust"}
    for text, skill in no.items():
        assert skill not in ex(text), (text, skill)
    yes = {"Embedded software in C for microcontrollers": "embedded", "Docker and container orchestration": "docker",
           "iOS developer with Swift": "swift", "Build scalable services in Go": "sysdesign",
           "Systems programming in Rust and C++": "rust", "Vi arbetar agilt i team": "agile",
           "Ansible and Chef cookbooks": "ansible"}
    for text, skill in yes.items():
        assert skill in ex(text), (text, skill)


def test_robots():
    from jobs.robots import Robots
    ua = "sweden-tech-jobs/0.3 (+https://github.com/Rong0715/sweden-tech-jobs)"
    r = Robots("User-agent: *\nDisallow: /\nAllow: /api/pcsx\n")
    assert r.can_fetch(ua, "https://x.com/api/pcsx/search?domain=a")
    assert not r.can_fetch(ua, "https://x.com/careers")
    r = Robots("User-agent: *\nAllow: /jobs\nDisallow: /jobs/apply\n")
    assert r.can_fetch(ua, "https://x.com/jobs/123") and not r.can_fetch(ua, "https://x.com/jobs/apply/1")
    r = Robots("User-agent: sweden-tech-jobs\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert not r.can_fetch(ua, "https://x.com/a")
    r = Robots("User-agent: *\nDisallow: /*.pdf$\nDisallow:\n")
    assert not r.can_fetch(ua, "https://x.com/a/b.pdf") and r.can_fetch(ua, "https://x.com/a/b.pdfx")
    assert Robots("").can_fetch(ua, "https://x.com/") and not Robots(disallow_all=True).can_fetch(ua, "https://x.com/")


def test_tagger_v2():
    """Cases from the blind hand check of 40 ads (Nov 2026)."""
    from jobs.skills import extract as ex
    yes = {"Vi bygger AI-agenter för kundtjänst": "agents", "MQTT och OPC UA mot maskiner": "mq",
           "Analys i SIEM och SOAR-plattformar": "security", "Script i PowerShell": "bash",
           "Java, Spring, Kafka och Kubernetes": "spring", "Build APIs in Python and Go": "rest",
           "experiment tracking and model registry": "mlops", "entity extraction from documents": "nlp",
           "Automated tests with Playwright": "tdd", "Pipelines in Azure DevOps": "cicd"}
    for text, skill in yes.items():
        assert skill in ex(text), (text, skill)
    no = {"Statistiska centralbyrån söker IT-supporttekniker": "stats", "Pipelines in Azure DevOps": "devops",
          "API production in a GMP pharma plant": "rest", "Microsoft Semantic Kernel": "os",
          "Claude Svensson, rekryterare": "llm", "control algorithms for motors": "dsa"}
    for text, skill in no.items():
        assert skill not in ex(text), (text, skill)
    g = classify.gate_family
    assert g("software", "Kvalitetsingenjör", []) == "other_eng"
    assert g("platform", "Labbtekniker", []) == "platform" or classify.role_family("Labbtekniker") != "platform"
    assert g("software", "Senior systemingenjör", ["python", "linux"]) == "software"
    assert g("software", "Backend Developer", []) == "software"
    assert g("security", "Lösningsarkitekt", ["security"]) == "security"


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); print("ok", k)
