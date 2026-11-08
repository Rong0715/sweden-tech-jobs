"""Arbetsförmedlingen / JobTech open data.

current_ads(): every live ad in the chosen occupation fields from the JobSearch API.
  The API caps offset+limit at about 2100, so the time range is split until each
  window holds fewer ads than that.
history_year(): streams one yearly bulk file from data.jobtechdev.se and yields
  compact feature rows for tech ads, without keeping the text.
"""
import datetime as dt
import io
import json
import os
import re
import zipfile

from . import classify, skills

SEARCH = "https://jobsearch.api.jobtechdev.se/search"
FIELDS = {
    "apaJ_2ja_LuF": "Data/IT",
    "6Hq3_tKo_V57": "Tekniskt arbete",   # embedded / engineering roles often sit here
}
CAP = 2000


def _count(net, field, after, before):
    d = net.get(SEARCH, params={"occupation-field": field, "published-after": after,
                                "published-before": before, "limit": 0})
    return (d or {}).get("total", {}).get("value", 0)


def _windows(net, field, start, end):
    """Split [start, end) into windows with < CAP ads each."""
    stack, out = [(start, end)], []
    while stack:
        a, b = stack.pop()
        n = _count(net, field, a.isoformat(timespec="seconds"), b.isoformat(timespec="seconds"))
        if n == 0:
            continue
        if n < CAP or (b - a) <= dt.timedelta(hours=6):
            out.append((a, b, n))
        else:
            mid = a + (b - a) / 2
            stack += [(a, mid), (mid, b)]
    return sorted(out)


def current_ads(net, fields=FIELDS, days_back=400):
    end = dt.datetime.utcnow().replace(microsecond=0) + dt.timedelta(days=1)
    start = end - dt.timedelta(days=days_back)
    seen = set()
    for field, flabel in fields.items():
        for a, b, n in _windows(net, field, start, end):
            off = 0
            while off < min(n, CAP + 100):
                d = net.get(SEARCH, params={"occupation-field": field, "published-after": a.isoformat(timespec="seconds"),
                                            "published-before": b.isoformat(timespec="seconds"), "limit": 100, "offset": off})
                hits = (d or {}).get("hits", [])
                for h in hits:
                    if h["id"] in seen:
                        continue
                    seen.add(h["id"])
                    h["_field"] = flabel
                    yield h
                if len(hits) < 100:
                    break
                off += 100


def ad_to_posting(h):
    emp = h.get("employer") or {}
    wa = h.get("workplace_address") or {}
    desc = (h.get("description") or {}).get("text") or ""
    langs = [l.get("label", "") for l in ((h.get("must_have") or {}).get("languages") or [])]
    return dict(
        source="jobtech", company=emp.get("name") or emp.get("workplace") or "", tier="",
        ext_id=h.get("id"), title=h.get("headline", ""),
        location=", ".join(x for x in (wa.get("municipality"), wa.get("region")) if x) or (wa.get("country") or ""),
        country=wa.get("country") or "Sverige", url=h.get("webpage_url", ""),
        posted=(h.get("publication_date") or "")[:10], deadline=(h.get("application_deadline") or "")[:10],
        description=desc, department="", employment_type=(h.get("employment_type") or {}).get("label") or "",
        workplace=(h.get("workplace_model") or {}).get("label") or "", in_sweden=(wa.get("country_code") in (None, "", "199")) or (wa.get("country") in (None, "", "Sverige")),
        org_nr=emp.get("organization_number") or "", must_langs=langs, field=h.get("_field", ""),
        occupation=(h.get("occupation") or {}).get("label") or "", apply_url=(h.get("application_details") or {}).get("url") or "",
    )


# ---------------- historical bulk ----------------
HIST_BASE = "https://data.jobtechdev.se/annonser/historiska/"
IT_MARKERS = ("apaJ_2ja_LuF", '"Data/IT"')
TECH_TITLE = re.compile(r"software|mjukvar|utvecklare|developer|programmer|programmerare|data engineer|dataingenjör|devops|"
                        r"machine learning|data scien|embedded|inbyggd|firmware|backend|frontend|fullstack|"
                        r"systemarkitekt|cloud|site reliability|\bsre\b", re.I)


def history_files(year):
    if year >= 2026:
        return [f"{year}-Q{q}.jsonl.zip" for q in (1, 2, 3, 4)]
    return [f"{year}.jsonl.zip"]


def download(net, name, dest):
    """Stream a bulk file to disk; returns path or None (file missing)."""
    import requests
    url = HIST_BASE + name
    if not net.allowed(url):
        return None
    path = os.path.join(dest, name)
    if os.path.exists(path):
        return path
    with net.s.get(url, stream=True, timeout=120) as r:
        if r.status_code != 200:
            net.log(kind="http_error", url=url, status=r.status_code)
            return None
        with open(path + ".part", "wb") as f:
            for chunk in r.iter_content(1 << 22):
                f.write(chunk)
    os.replace(path + ".part", path)
    return path


def iter_jsonl_zip(path):
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            with z.open(name) as raw:
                for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
                    yield line


def _get(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def history_rows(lines):
    """Yield compact feature rows from raw JSONL lines of a bulk file."""
    for line in lines:
        is_it = any(m in line for m in IT_MARKERS)
        if not is_it and not TECH_TITLE.search(line[:4000]):
            continue
        try:
            h = json.loads(line)
        except ValueError:
            continue
        title = h.get("headline") or ""
        fid = _get(h, "occupation_field", "concept_id") or ""
        flab = _get(h, "occupation_field", "label") or ""
        field_it = fid == "apaJ_2ja_LuF" or flab == "Data/IT"
        if not field_it and not TECH_TITLE.search(title):
            continue
        text = (_get(h, "description", "text") or "")
        full = title + "\n" + text
        sen, yrs = classify.seniority(title, text)
        langs = [l.get("label", "") for l in (_get(h, "must_have", "languages") or []) if isinstance(l, dict)]
        sig = classify.signals(text, langs)
        pub = (h.get("publication_date") or "")[:10]
        yield dict(
            id=str(h.get("id", "")), date=pub, year=int(pub[:4]) if pub[:4].isdigit() else None,
            employer=_get(h, "employer", "name") or "", org_nr=_get(h, "employer", "organization_number") or "",
            title=title[:200], occupation=_get(h, "occupation", "label") or "", field_it=field_it,
            family=classify.role_family(title, text), seniority=sen, years_req=yrs,
            skills="|".join(skills.extract(full)), sv_req=sig["swedish_required"], eu_only=sig["eu_only"],
            clearance=sig["clearance"], ad_lang=sig["ad_lang"], remote=sig["remote"],
            region=_get(h, "workplace_address", "region") or "", municipality=_get(h, "workplace_address", "municipality") or "",
            vacancies=h.get("number_of_vacancies") or 1, text_len=len(text),
        )
