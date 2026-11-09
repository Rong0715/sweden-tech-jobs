"""Rule-based labels for a listing: seniority, role family, language and permit signals.

All rules work on English and Swedish text. Each function returns a value plus,
where useful, the evidence string so the labels can be audited.
"""
import re

I = re.IGNORECASE

# ---------- seniority ----------
_THESIS = re.compile(r"\b(master'?s? thesis|thesis (?:work|project|student|worker)|exjobb|examensarbete|degree project|thesis)\b", I)
_INTERN = re.compile(r"\b(intern(?:ship)?|praktik(?:ant|plats)?|sommarjobb|summer (?:job|intern|worker|student)|working student|student (?:job|position|developer)|extrajobb för student)\b", I)
_GRAD = re.compile(r"\b(graduate (?:program(?:me)?|engineer|developer|trainee|position|role|scheme)|new grad|nyexaminerad|trainee(?:program|ship)?|early career|young professional|karriärstart|entry[- ]level|recent graduates?|traineeprogram|\bgraduates?\b)", I)
_JUNIOR = re.compile(r"\b(junior|jr\.?|associate (?:software|engineer|developer|data))\b", I)
_SENIOR_T = re.compile(r"\b(senior|sr\.?|lead|principal|staff|chief|head of|director|architect|arkitekt|manager|chef|expert|specialist|teamlead|tech lead)\b", I)
_YEARS = re.compile(
    r"(?:(\d{1,2})\s*(?:\+|-\s*\d{1,2}|–\s*\d{1,2})?\s*(?:years?|yrs?|års?)\b(?:\s+(?:of\s+)?(?:professional\s+|relevant\s+|hands-on\s+|industry\s+|work\s+)?(?:experience|erfarenhet))?)"
    r"|(?:(?:minst|at least|minimum(?: of)?|över|more than)\s+(\d{1,2})\s*(?:years?|års?))", I)


def years_required(text):
    """Smallest plausible 'N years' requirement mentioned, or None."""
    if not text:
        return None
    vals = []
    for m in _YEARS.finditer(text):
        n = m.group(1) or m.group(2)
        if not n:
            continue
        n = int(n)
        tail = text[m.end():m.end() + 60].lower()
        head = text[max(0, m.start() - 40):m.start()].lower()
        ctx = head + text[m.start():m.end()].lower() + tail
        if "experience" in ctx or "erfarenhet" in ctx:
            if 0 < n <= 20:
                vals.append(n)
    return min(vals) if vals else None


def seniority(title, text=""):
    """thesis | intern | graduate | junior | mid | senior, plus years required."""
    t = title or ""
    yrs = years_required(text)
    if _THESIS.search(t):
        return "thesis", yrs
    if _INTERN.search(t):
        return "intern", yrs
    if _GRAD.search(t):
        return "graduate", yrs
    if _JUNIOR.search(t):
        return "junior", yrs
    if _SENIOR_T.search(t):
        return "senior", yrs
    # title silent: use body
    body = text or ""
    if _THESIS.search(body[:600]) and re.search(r"thesis|exjobb|examensarbete", t + body[:300], I):
        return "thesis", yrs
    if yrs is not None:
        if yrs <= 2:
            return "junior", yrs
        if yrs >= 5:
            return "senior", yrs
        return "mid", yrs
    if re.search(r"\b(junior|nyexaminerad|recent graduate|new grad|entry[- ]level)\b", body, I):
        return "junior", yrs
    if re.search(r"\b(senior|seniority|lång erfarenhet|extensive experience|proven track record)\b", body, I):
        return "senior", yrs
    return "mid", yrs


ENTRY = {"thesis", "intern", "graduate", "junior"}

# ---------- role family ----------
_FAM = [
    ("ml_ai", r"machine learning|\bml\b|\bai\b|artificial intelligence|data scien|deep learning|\bllm|genai|computer vision|nlp|research (?:engineer|scientist)|applied scien|mlops|maskininlärning|AI-"),
    ("data", r"data engineer|dataingenjör|analytics engineer|data platform|\betl\b|data warehouse|big data|data architect|bi[- ]developer|business intelligence|data analyst|dataanalytiker"),
    ("platform", r"platform|devops|\bsre\b|site reliability|infrastructure|infrastruktur|cloud|moln|kubernetes|systems? engineer|drift|reliability|network engineer|nätverk"),
    ("security", r"security|säkerhet|cyber|pentest|soc analyst|appsec|\biam\b"),
    ("embedded", r"embedded|inbyggd|firmware|fpga|hardware|asic|baseband|dsp|signal processing|rf engineer|automotive software|autosar|realtid"),
    ("mobile", r"\bios\b|android|mobile|mobil(?:utvecklare|app)"),
    ("frontend", r"front[- ]?end|frontendutvecklare|ui developer|react developer|web developer|webbutvecklare|ux engineer"),
    ("qa", r"\btest(?:are|er|ing|automation|ledare)?\b|\bqa\b|quality assurance|verification|verifiering"),
    ("backend", r"back[- ]?end|backendutvecklare|server[- ]side|\bapi\b|java developer|\.net developer|python developer|go developer|distributed"),
    ("fullstack", r"full[- ]?stack|fullstackutvecklare"),
    ("software", r"software|mjukvara|systemutvecklare|utvecklare|developer|programmer|programmerare|engineer|ingenjör|kodare"),
    ("pm_design", r"product (?:manager|owner|designer)|produktägare|scrum master|agile coach|ux|designer|project manager|projektledare"),
    ("it_ops", r"support|helpdesk|servicedesk|it-administratör|administrator|tekniker|technician|systemförvaltare|förvaltning"),
]
_FAM_RX = [(n, re.compile(p, I)) for n, p in _FAM]


def role_family(title, text=""):
    t = title or ""
    for name, rx in _FAM_RX:
        if rx.search(t):
            return name
    head = (text or "")[:800]
    for name, rx in _FAM_RX[:5]:
        if rx.search(head):
            return name
    return "other"


# Families picked from a generic title word ("ingenjör", "engineer", "tekniker", "säkerhet") or from
# the first lines of the ad text are often mechanical, quality, lab or support jobs. A blind hand
# check of 40 ads (Nov 2026) found 14 of 33 "engineering" ads were not software roles. So such ads
# count as engineering only when the title itself is clearly a software/IT-engineering title or the
# ad names at least two core software skills; otherwise they become "other_eng".
_SW_TITLE = re.compile(
    r"software|mjukvar|\bsw\b|utvecklare|developer|programmer|programmerare|kodare|\bdevops\b|\bsre\b|"
    r"site reliability|cloud|moln|kubernetes|platform engineer|plattformsingenjör|\bdata\b|dataingenjör|"
    r"dataanalytiker|data analyst|back[- ]?end|front[- ]?end|full[- ]?stack|machine learning|\bml\b|\bai\b|AI-|"
    r"maskininlärning|data scien|security engineer|säkerhetsingenjör|cyber|it-säkerhet|informationssäkerhet|"
    r"pentest|\bsoc\b|appsec|embedded|inbyggd|firmware|fpga|test ?automat|qa engineer|sdet|"
    r"(?:solution|lösnings|system|it|cloud|moln|software|mjukvaru|enterprise|data|ai|integration|security|säkerhets)[- ]?(?:arkitekt|architect)|"
    r"systemutvecklare|it[- ]?ingenjör|network engineer|nätverksingenjör|\bml ?ops|\bllm|genai", re.I)
_CORE_CATS = {"lang", "frontend", "backend", "arch", "data", "cloud", "ml", "tool"}
_CORE_EXTRA = {"docker", "k8s", "terraform", "cicd", "linux", "observ", "ansible", "embedded", "gpu", "os"}
_SOFT_FAMS = {"software", "platform", "security", "qa", "embedded", "ml_ai", "data", "mobile", "frontend", "backend", "fullstack"}


def gate_family(family, title, skill_ids):
    """Demote an engineering family to 'other_eng' unless the title or the skills show a software core."""
    if family not in _SOFT_FAMS:
        return family
    if _SW_TITLE.search(title or ""):
        return family
    from .skills import SKILLS
    core = [s for s in skill_ids if SKILLS.get(s, {}).get("cat") in _CORE_CATS or s in _CORE_EXTRA]
    return family if len(core) >= 2 else "other_eng"


# role families we treat as "engineering" for skill statistics
ENG_FAMILIES = {"ml_ai", "data", "platform", "security", "embedded", "mobile", "frontend", "qa", "backend", "fullstack", "software"}
TARGET_FAMILIES = {"ml_ai", "data", "platform", "backend", "software", "fullstack", "embedded"}

# ---------- language & permit signals ----------
_SV_REQ = re.compile(
    r"(flytande|god|goda|mycket god|utmärkt|obehindrad)[^.\n]{0,25}svenska|svenska (?:och engelska )?i (?:tal och skrift|både tal och skrift)|"
    r"behärska[rs]? (?:det )?svenska|kunskaper i svenska|svenska är ett krav|krav på svenska|"
    r"fluent (?:in )?swedish|swedish (?:is )?(?:required|a must|mandatory)|proficien\w* in swedish|"
    r"(?:professional|full) (?:working )?proficiency in swedish|speak(?:s|ing)? (?:fluent )?swedish|swedish and english(?:,)? (?:both )?(?:written and spoken|fluently)|"
    r"excellent (?:written and verbal )?(?:command of )?swedish|native swedish|"
    r"good (?:command of|knowledge of) swedish|swedish (?:language )?skills", I)
_SV_PLUS = re.compile(r"swedish (?:is )?(?:a plus|an advantage|meriting|nice to have|preferred)|svenska (?:är )?(?:meriterande|ett plus)", I)
_EU_ONLY = re.compile(
    r"\b(eu|eea|ees|eu/ees|eu/eea)[- ]?(?:citizen|medborgare|citizenship|nationals?|passport)|"
    r"(?:citizens? of|medborgare i) (?:an? )?(?:eu|eea|ees|the european union)|"
    r"(?:svenskt|swedish) (?:medborgarskap|citizenship)|"
    r"must (?:already )?have (?:the )?(?:legal )?right to work in (?:sweden|the eu)|"
    r"(?:valid|existing) work permit (?:is )?required|we (?:do not|don't|cannot|can't) (?:offer|provide) (?:visa )?sponsorship|"
    r"no (?:visa )?sponsorship|without (?:the need for )?sponsorship", I)
_CLEARANCE = re.compile(r"säkerhetsprövning|säkerhetsskydd|security clearance|säkerhetsklass|registerkontroll", I)
_VISA_OK = re.compile(r"visa sponsorship|relocation (?:support|package|assistance)|we (?:can )?sponsor|support(?:s)? work permits?|help with (?:your )?(?:visa|work permit)", I)
_REMOTE = re.compile(r"\b(remote|fully remote|distansarbete|på distans|work from anywhere)\b", I)
_HYBRID = re.compile(r"\bhybrid\b", I)

_SV_STOP = re.compile(r"\b(och|att|det|som|för|med|är|vi|du|på|av|har|till|en|kommer|inom|våra|dig)\b", I)
_EN_STOP = re.compile(r"\b(and|the|to|of|you|we|with|for|our|in|is|are|will|be|your|as)\b", I)


def ad_language(text):
    if not text:
        return ""
    s = text[:3000]
    sv, en = len(_SV_STOP.findall(s)), len(_EN_STOP.findall(s))
    if sv + en < 10:
        return ""
    return "sv" if sv > en else "en"


def signals(text, must_langs=None):
    text = text or ""
    must = [l.lower() for l in (must_langs or [])]
    sv_req = bool(_SV_REQ.search(text)) or any(l in ("svenska", "swedish") for l in must)
    if sv_req and _SV_PLUS.search(text) and not re.search(r"krav|required|must", text, I):
        sv_req = False
    rem = "remote" if _REMOTE.search(text) else ("hybrid" if _HYBRID.search(text) else "")
    return dict(
        swedish_required=sv_req,
        swedish_plus=bool(_SV_PLUS.search(text)),
        eu_only=bool(_EU_ONLY.search(text)),
        clearance=bool(_CLEARANCE.search(text)),
        visa_ok=bool(_VISA_OK.search(text)),
        remote=rem,
        ad_lang=ad_language(text),
    )
