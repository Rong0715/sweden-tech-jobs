"""Skill taxonomy: regex detectors plus the judgement inputs for the learning route.

Each skill has
  pat    regex (case-insensitive unless cs=True)
  cs     case-sensitive match
  ctx    ambiguous word: only counts when another *language/tool* skill is
         matched within CTX_WINDOW characters (e.g. "Go", "C", "R", "Rust")
  ctx_pat  extra pattern that counts only with such context (plain "API" also means
         active pharmaceutical ingredient)
  cat    category used for grouping in reports
  cost   rough hours for a CS master's student to reach "can use it in an
         interview / first job" level from zero (judgement, documented as such)
  pre    prerequisite skill ids (for the dependency map)
  site   practice site that trains it: algo (LeetCode map), ds (distributed lab),
         sd (system design), or ''
Costs are judgement inputs to the ROI model, not data. A learner's current level per
skill comes from a profile file (see config/profile.example.json).
"""
import re

CTX_WINDOW = 80

S = {}


def k(id, label, cat, pat, cost, pre=(), site="", cs=False, ctx=False, ctx_pat=None):
    S[id] = dict(id=id, label=label, cat=cat, pat=pat, cost=cost, pre=list(pre),
                 site=site, cs=cs, ctx=ctx, ctx_pat=ctx_pat)


# --- languages
k("python", "Python", "lang", r"\bpython\b", 60, site="algo")
k("java", "Java", "lang", r"\bjava\b(?!\s*script)", 80, site="algo")
k("kotlin", "Kotlin", "lang", r"\bkotlin\b", 40, pre=["java"])
k("scala", "Scala", "lang", r"\bscala\b", 80, pre=["java"])
k("go", "Go", "lang", r"\bgolang\b|(?<![\w.-])Go(?![\w-])", 40, site="ds", cs=True, ctx=True)
k("rust", "Rust", "lang", r"\brust\b", 120, pre=["cpp"], ctx=True)
k("cpp", "C++", "lang", r"c\+\+|\bcpp\b", 120)
k("c", "C", "lang", r"(?<![\w+#/.-])C(?![\w+#-])", 80, cs=True, ctx=True)
k("csharp", "C#/.NET", "lang", r"c#|\.net\b|\bdotnet\b|asp\.net", 80)
k("typescript", "TypeScript", "lang", r"\btypescript\b", 30, pre=["javascript"])
k("javascript", "JavaScript", "lang", r"\bjavascript\b|\bnode\.?js\b", 40)
k("sql", "SQL", "data", r"\bsql\b|\bt-sql\b|\bpl/sql\b", 40)
k("bash", "Shell/Bash/PowerShell", "tool", r"\bbash\b|shell[- ]script|powershell", 15)
k("r_lang", "R", "lang", r"(?<![\w&/.-])R(?![\w&/'’-])", 60, cs=True, ctx=True)
k("matlab", "MATLAB", "lang", r"\bmatlab\b", 30)
k("php", "PHP", "lang", r"\bphp\b", 40)
k("ruby", "Ruby", "lang", r"\bruby\b", 40)
k("swift", "Swift/iOS", "lang", r"\bSwift\b|\biOS\b", 80, cs=True)
k("elixir", "Elixir/Erlang", "lang", r"\belixir\b|\berlang\b", 80)
# --- frontend
k("react", "React", "frontend", r"\breact(?:\.js|js)?\b(?!\s*native)", 30, pre=["javascript"])
k("angular", "Angular", "frontend", r"\bangular\b", 40, pre=["typescript"])
k("vue", "Vue", "frontend", r"\bvue(?:\.js)?\b", 30, pre=["javascript"])
# --- backend frameworks
k("spring", "Spring/Spring Boot", "backend", r"\bspring(?:\s*boot)?\b(?=.{0,40}(java|boot|framework|microservice))|\bspring\s*boot\b|\bjava\W{1,6}(?:och |and )?spring\b", 40, pre=["java"])
k("django", "Django/FastAPI/Flask", "backend", r"\bdjango\b|\bfastapi\b|\bflask\b", 25, pre=["python"])
k("grpc", "gRPC/Protobuf", "backend", r"\bgrpc\b|\bprotobuf\b|protocol buffers", 15, pre=["rest"])
k("rest", "REST/HTTP APIs", "backend", r"\brestful\b|\brest[- ]?apis?\b|\brest(?:[- ]based|[- ]services?|[- ]?endpoints?|/json|/http)\b|\bhttp apis?\b|\bapi[- ]design|web ?services?|webbtjänster", 15,
  ctx_pat=r"\bAPI(?:s|er|:er|:s)?\b")
k("graphql", "GraphQL", "backend", r"\bgraphql\b", 15, pre=["rest"])
k("microservices", "Microservices", "arch", r"micro-?services?|mikrotjänst", 30, pre=["rest"], site="sd")
k("distributed", "Distributed systems", "arch", r"distributed systems?|distribuerade system|consensus (?:algorithms?|protocols?)|\braft\b|\bpaxos\b", 100, site="ds")
k("sysdesign", "System design/scalability", "arch", r"scalability|scalable (?:systems?|services?|architectures?|backends?|infrastructure|platforms?|software|apis?|data|environments?|applications?|distributed)|skalbarhet|skalbar[at]? (?:system|tjänst|arkitektur|plattform|miljö|lösningar inom moln)\w*|fault[- ]toleran\w*|feltolerant\w*|\b(?:system|software|solution|cloud|mjukvaru|lösnings|moln)[- ]?(?:architecture|arkitektur)|high[- ]availability|low[- ]latency|high[- ]throughput|system design|large[- ]scale (?:systems?|distributed)", 60, pre=["distributed"], site="sd")
# --- data stores / streaming
k("postgres", "PostgreSQL", "data", r"postgres(?:ql)?", 20, pre=["sql"], site="sd")
k("mysql", "MySQL/MariaDB", "data", r"\bmysql\b|\bmariadb\b", 15, pre=["sql"])
k("mongodb", "MongoDB", "data", r"\bmongo(?:db)?\b", 15)
k("redis", "Redis", "data", r"\bredis\b", 10, site="sd")
k("cassandra", "Cassandra/Bigtable/Dynamo", "data", r"\bcassandra\b|\bbigtable\b|\bdynamodb\b|\bscylla", 25, pre=["distributed"], site="sd")
k("elastic", "Elasticsearch/OpenSearch", "data", r"elasticsearch|opensearch|\belk\b", 20)
k("kafka", "Kafka", "data", r"\bkafka\b", 30, pre=["distributed"], site="sd")
k("mq", "Message queues (RabbitMQ/PubSub/SQS)", "data", r"rabbitmq|pub/?sub|\bsqs\b|\bnats\b|activemq|message (?:queue|broker)|\bmqtt\b|\bamqp\b|service bus|event hubs?", 15, site="sd")
k("spark", "Spark", "data", r"apache spark|pyspark|databricks|\bspark\b(?=.{0,60}(sql|scala|python|hadoop|data|streaming))", 40, pre=["python", "sql"])
k("flink", "Flink/Beam", "data", r"\bflink\b|apache beam|dataflow", 40, pre=["kafka"])
k("airflow", "Airflow/dbt/orchestration", "data", r"\bairflow\b|\bdbt\b|dagster|prefect", 20, pre=["sql", "python"])
k("dwh", "Data warehouse (BigQuery/Snowflake/Redshift)", "data", r"bigquery|snowflake|redshift|synapse", 20, pre=["sql"])
# --- cloud / platform
k("aws", "AWS", "cloud", r"\baws\b|amazon web services", 60, pre=["linux"])
k("gcp", "GCP", "cloud", r"\bgcp\b|google cloud", 60, pre=["linux"])
k("azure", "Azure", "cloud", r"\bazure\b", 60, pre=["linux"])
k("docker", "Docker/containers", "platform", r"\bdocker\b|\bpodman\b|containeri[sz]|container (?:orchestration|platforms?|images?|runtimes?|technolog\w*|registry)", 15, pre=["linux"])
k("k8s", "Kubernetes", "platform", r"kubernetes|\bk8s\b|\bopenshift\b|\beks\b|\bgke\b|\baks\b", 50, pre=["docker"])
k("terraform", "Terraform/IaC", "platform", r"terraform|infrastructure as code|\biac\b|pulumi|cloudformation|\bbicep\b", 25, pre=["aws"])
k("cicd", "CI/CD", "platform", r"ci/cd|\bci\b/?\bcd\b|continuous (?:integration|delivery|deployment)|github actions|gitlab ci|jenkins|argo ?cd|azure devops|azure pipelines", 15, pre=["git"])
k("linux", "Linux", "platform", r"\blinux\b|\bunix\b", 20)
k("git", "Git", "tool", r"\bgit\b|github|gitlab|bitbucket", 5)
k("observ", "Observability (Prometheus/Grafana/OTel)", "platform", r"prometheus|grafana|opentelemetry|observability|datadog|splunk|new relic|(?:system|application|infrastructure|service|log|performance|cloud|it)[- ]?monitoring|log management|logghantering|\bkibana\b|\bjaeger\b|distributed tracing", 15, pre=["linux"], site="sd")
k("ansible", "Ansible/config mgmt", "platform", r"\bansible\b|\bpuppet\b|\bsaltstack\b|chef (?:infra|cookbooks?|recipes)", 15, pre=["linux"])
k("networking", "Networking (TCP/IP)", "platform", r"tcp/ip|computer network|network(?:ing)? protocols?|nätverks(?:teknik|säkerhet|infrastruktur|design|arkitektur)|network (?:engineering|security|infrastructure|design|architecture)|\bbgp\b|\bdns\b|load balanc|\bsdn\b|\bvlan|firewalls?|brandväggar?|\bcisco\b|\bjuniper\b|\brouting\b|\bswitching\b", 40)
k("security", "Security (IAM/OWASP/crypto)", "platform", r"cyber ?security|cybersäkerhet|it-säkerhet|informationssäkerhet|\bowasp\b|\biam\b|penetration test|appsec|devsecops|zero trust|\bsiem\b|\bsoar\b|vulnerabilit\w*|sårbarhet\w*|threat (?:detection|hunting|modell?ing)|incident response|iso ?27001|\bnis ?2\b", 40)
# --- ML / AI
k("ml", "Machine learning", "ml", r"machine learning|maskininlärning|\bml\b|\bmlops\b", 80, pre=["python"])
k("dl", "Deep learning (PyTorch/TF)", "ml", r"deep learning|pytorch|tensorflow|\bkeras\b|\bjax\b|neural net", 60, pre=["ml"])
k("llm", "LLM/GenAI", "ml", r"\bllms?\b|large language model|generative ai|\bgenai\b|gen ai|\bgpt\b|chatgpt|openai|anthropic|claude (?:ai|api|sonnet|opus|models?)|gemini (?:api|pro|models?)|google gemini|prompt engineering|foundation model|språkmodell", 30, pre=["python"])
k("rag", "RAG/vector search", "ml", r"\brag\b|retrieval[- ]augmented|vector (?:db|database|search|store)|embeddings?|pinecone|weaviate|pgvector|langchain|llamaindex", 20, pre=["llm"])
k("agents", "AI agents/tool use", "ml", r"\bai[- ]?agent\w*|agentic|agentisk\w*|agent(?:ic)? (?:systems?|workflows?|frameworks?)|multi-agent|tool[- ]use|function calling|\bmcp\b|model context protocol|langgraph|autogen|crewai", 20, pre=["llm"])
k("aitools", "AI coding tools", "ml", r"copilot|cursor\b|\bclaude\b|chatgpt|ai[- ]assisted|ai-driven development|ai coding|codex|ai[- ]verktyg|ai[- ]tools|ai[- ]assisterad", 5)
k("mlops", "MLOps/model serving", "ml", r"\bmlops\b|model serving|kubeflow|mlflow|sagemaker|vertex ai|triton|\bvllm\b|feature store|experiment tracking|\bdvc\b|weights (?:&|and) biases|model (?:deployment|monitoring|registry)", 40, pre=["ml", "docker"])
k("cv", "Computer vision", "ml", r"computer vision|datorseende|opencv|image (?:recognition|segmentation)|object detection", 60, pre=["dl"])
k("nlp", "NLP", "ml", r"\bnlp\b|natural language processing|information extraction|entity (?:extraction|recognition)|text (?:classification|mining)|språkteknologi", 40, pre=["ml"])
k("stats", "Statistics/analytics", "ml", r"\bstatistics\b|\bstatistical\b|\bstatistik\b|statistisk[a]? (?:analys|modell|metod)\w*|a/b test|experimentation|causal inference|bayesian", 40)
# --- embedded / systems
k("embedded", "Embedded/firmware", "embedded", r"embedded (?:systems?|software|linux|c\b|c\+\+|rust|development|engineer\w*|developer|programming|hardware|devices?|platforms?|targets?)|inbyggda system|inbyggd mjukvara|firmware|\brtos\b|microcontroller|mikrokontroller|\bfpga\b|autosar|\bcan[- ]bus\b|\bcan\b(?= ?(bus|protocol))", 100, pre=["c"])
k("os", "OS/kernel/low-level", "embedded", r"linux kernel|(?<!semantic )\bkernel\b|device driver|operating systems?|\bllvm\b|compiler", 100, pre=["c"])
k("gpu", "GPU/CUDA/HPC", "embedded", r"\bcuda\b|\bgpu\b|\bhpc\b|\bmpi\b|opencl", 60, pre=["cpp"])
k("5g", "Telecom (5G/RAN)", "embedded", r"\b[456]G\b|\bLTE\b|\bRAN\b|[Bb]aseband|3GPP|O-RAN", 80, pre=["c"], cs=True)
# --- practices
k("tdd", "Testing/TDD", "practice", r"\btdd\b|test[- ]driven|unit test|automated test|testautomat|integration test|\bjunit\b|\bpytest\b|(?:software|automated|unit|end-to-end|e2e|regression)[- ]?test\w*|test frameworks?|testramverk|selenium|playwright|cypress|\bjest\b", 15)
k("agile", "Agile/Scrum", "practice", r"\bagile\b|\bagil[at]?\b|\bscrum\b|\bkanban\b|\bsafe\b(?= ?framework)", 5)
k("devops", "DevOps/SRE", "practice", r"(?<!azure )\bdevops\b|\bsre\b|site reliability|on-?call|incident management", 30, pre=["linux", "cicd"])
k("dsa", "Algorithms/data structures", "practice", r"data structures|datastrukturer|leetcode|competitive programming|algorithmic problem[- ]solving|algorithms? (?:and|&) complexity|complexity analysis", 80, site="algo")
k("oop", "OOP/design patterns", "practice", r"object[- ]oriented|objektorienter|design patterns|\bsolid\b(?= principles)|domain[- ]driven|\bddd\b", 20)

SKILLS = S
_RX, _CRX = {}, {}
for sid, d in S.items():
    flags = 0 if d["cs"] else re.IGNORECASE
    _RX[sid] = re.compile(d["pat"], flags)
    if d["ctx_pat"]:
        _CRX[sid] = re.compile(d["ctx_pat"])

# tokens that make an ambiguous single-letter / common word count
_CTX_IDS = [s for s, d in S.items() if d["cat"] in ("lang", "data", "platform", "cloud", "backend", "tool", "embedded", "frontend") and not d["ctx"]]
_CTX_RX = re.compile("|".join(f"(?:{S[s]['pat']})" for s in _CTX_IDS), re.IGNORECASE)


def extract(text):
    """Return the sorted list of skill ids mentioned in text."""
    if not text:
        return []
    found = []
    for sid, rx in _RX.items():
        if not S[sid]["ctx"]:
            if rx.search(text):
                found.append(sid)
                continue
            rx = _CRX.get(sid)
            if rx is None:
                continue
        for m in rx.finditer(text):
            lo, hi = max(0, m.start() - CTX_WINDOW), m.end() + CTX_WINDOW
            window = text[lo:m.start()] + " " + text[m.end():hi]
            if _CTX_RX.search(window):
                found.append(sid)
                break
    return sorted(found)
