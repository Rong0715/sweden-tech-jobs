"""One adapter per applicant tracking system (ATS), not per company.

Every adapter takes (net, row) where row is a companies.csv dict and returns a list
of postings in one intermediate shape (see `posting`). Adapters keep every posting
they see and mark whether it is in Sweden; filtering happens later.
"""
import html as htmllib
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET

SE_PLACES = [
    "sweden", "sverige", "stockholm", "göteborg", "goteborg", "gothenburg", "malmö", "malmo", "lund", "uppsala",
    "linköping", "linkoping", "västerås", "vasteras", "örebro", "orebro", "norrköping", "norrkoping", "umeå", "umea",
    "luleå", "lulea", "jönköping", "jonkoping", "helsingborg", "karlskrona", "kista", "solna", "sundbyberg",
    "södertälje", "sodertalje", "borås", "boras", "gävle", "gavle", "sundsvall", "karlstad", "växjö", "vaxjo",
    "halmstad", "kalmar", "skövde", "skovde", "trollhättan", "trollhattan", "mölndal", "molndal", "danderyd",
    "nacka", "lidingö", "täby", "taby", "sollentuna", "järfälla", "huddinge", "kiruna", "östersund", "ostersund",
    "falun", "eskilstuna", "nyköping", "lindholmen", "ronneby", "motala", "olofström", "arlöv", "landskrona",
]
_SE_RX = re.compile(r"\b(" + "|".join(re.escape(p) for p in SE_PLACES) + r")\b", re.I)
_SE_CODE = re.compile(r"(?:^|[,\s(])(SE|SWE)(?:$|[,\s)])")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def strip_html(s):
    if not s:
        return ""
    s = htmllib.unescape(s)
    s = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", s)
    s = _TAG.sub(" ", s)
    s = htmllib.unescape(s)
    s = _WS.sub(" ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def in_sweden(*parts):
    txt = " ".join(p for p in parts if p)
    return bool(_SE_RX.search(txt) or _SE_CODE.search(txt))


def posting(source, row, ext_id, title, location="", url="", posted="", description="",
            department="", employment_type="", workplace="", country="", deadline=""):
    return dict(
        source=source, company=row["company"], tier=row.get("tier", ""), ext_id=str(ext_id),
        title=(title or "").strip(), location=(location or "").strip(), country=country or "",
        url=url or "", posted=str(posted or "")[:10], deadline=str(deadline or "")[:10],
        description=description or "", department=department or "", employment_type=employment_type or "",
        workplace=workplace or "", in_sweden=in_sweden(location, country),
    )


def _ms_date(ms):
    import datetime
    try:
        return datetime.datetime.utcfromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


# ---------------- Greenhouse ----------------
def greenhouse(net, row):
    slug = row["ats_key"]
    d = None
    for host in ("boards-api.greenhouse.io", "boards-api.eu.greenhouse.io"):
        d = net.get(f"https://{host}/v1/boards/{slug}/jobs", params={"content": "true"})
        if d and d.get("jobs") is not None:
            break
    out = []
    for j in (d or {}).get("jobs", []):
        locs = [j.get("location", {}).get("name", "")] + [o.get("location") or o.get("name") or "" for o in j.get("offices", [])]
        out.append(posting("greenhouse", row, j.get("id"), j.get("title"), "; ".join(l for l in locs if l),
                           j.get("absolute_url"), j.get("first_published") or j.get("updated_at"),
                           strip_html(j.get("content")), ", ".join(x.get("name", "") for x in j.get("departments", []))))
    return out, d is not None


# ---------------- Lever ----------------
def lever(net, row):
    slug = row["ats_key"]
    d = None
    for base in ("https://api.lever.co", "https://api.eu.lever.co"):
        d = net.get(f"{base}/v0/postings/{slug}", params={"mode": "json"})
        if d:
            break
    out = []
    for j in d or []:
        c = j.get("categories", {}) or {}
        locs = c.get("allLocations") or [c.get("location", "")]
        desc = "\n".join([j.get("descriptionPlain", "") or j.get("openingPlain", "")] +
                         [f"{l.get('text','')}\n{strip_html(l.get('content',''))}" for l in j.get("lists", [])] +
                         [j.get("additionalPlain", "")])
        out.append(posting("lever", row, j.get("id"), j.get("text"), "; ".join(l for l in locs if l),
                           j.get("hostedUrl"), _ms_date(j.get("createdAt")), desc,
                           c.get("team") or c.get("department", ""), c.get("commitment", ""),
                           j.get("workplaceType", ""), j.get("country", "")))
    return out, d is not None


# ---------------- Ashby ----------------
def ashby(net, row):
    slug = row["ats_key"]
    d = net.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "false"})
    out = []
    for j in (d or {}).get("jobs", []):
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations", []) or []]
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        out.append(posting("ashby", row, j.get("id"), j.get("title"), "; ".join(l for l in locs if l),
                           j.get("jobUrl"), j.get("publishedAt"), j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
                           j.get("team") or j.get("department", ""), j.get("employmentType", ""),
                           j.get("workplaceType") or ("remote" if j.get("isRemote") else ""),
                           addr.get("addressCountry", "")))
    return out, d is not None


# ---------------- Workable ----------------
def workable(net, row):
    slug = row["ats_key"]
    d = net.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", params={"details": "true"})
    out = []
    for j in (d or {}).get("jobs", []):
        locs = [", ".join(x for x in (j.get("city"), j.get("country")) if x)] + \
               [", ".join(x for x in (l.get("city"), l.get("country")) if x) for l in j.get("locations", []) or []]
        out.append(posting("workable", row, j.get("shortcode"), j.get("title"), "; ".join(l for l in locs if l),
                           j.get("url") or j.get("shortlink"), j.get("published_on") or j.get("created_at"),
                           strip_html(j.get("description")), j.get("department", ""), j.get("employment_type", ""),
                           "remote" if j.get("telecommuting") else "", j.get("country", "")))
    return out, d is not None


# ---------------- SmartRecruiters ----------------
def smartrecruiters(net, row, detail_cap=150):
    cid = row["ats_key"]
    out, offset, ok = [], 0, False
    while True:
        d = net.get(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings",
                    params={"limit": 100, "offset": offset, "country": "se"})
        if d is None:
            break
        ok = True
        items = d.get("content", [])
        for j in items:
            loc = j.get("location", {}) or {}
            desc = ""
            if len(out) < detail_cap:
                det = net.get(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings/{j.get('id')}")
                secs = ((det or {}).get("jobAd") or {}).get("sections", {}) or {}
                desc = "\n".join(strip_html((secs.get(s) or {}).get("text", "")) for s in
                                 ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))
            out.append(posting("smartrecruiters", row, j.get("id"), j.get("name"),
                               ", ".join(x for x in (loc.get("city"), loc.get("country")) if x),
                               f"https://jobs.smartrecruiters.com/{cid}/{j.get('id')}", j.get("releasedDate"), desc,
                               (j.get("department") or {}).get("label", ""),
                               (j.get("typeOfEmployment") or {}).get("label", ""),
                               "remote" if loc.get("remote") else "", loc.get("country", "")))
        offset += len(items)
        if not items or offset >= d.get("totalFound", 0):
            break
    return out, ok


# ---------------- Recruitee ----------------
def recruitee(net, row):
    slug = row["ats_key"]
    d = net.get(f"https://{slug}.recruitee.com/api/offers/")
    out = []
    for j in (d or {}).get("offers", []):
        out.append(posting("recruitee", row, j.get("id"), j.get("title"),
                           ", ".join(x for x in (j.get("city"), j.get("country")) if x) or j.get("location", ""),
                           j.get("careers_url"), j.get("published_at"),
                           strip_html((j.get("description") or "") + "\n" + (j.get("requirements") or "")),
                           j.get("department", ""), j.get("employment_type_code", ""),
                           "remote" if j.get("remote") else "", j.get("country_code", "")))
    return out, d is not None


# ---------------- Teamtailor (public RSS feed of the career site) ----------------
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def teamtailor(net, row):
    host = row["ats_key"].replace("https://", "").replace("http://", "").strip("/")
    xml = net.get(f"https://{host}/jobs.rss", as_json=False)
    out = []
    if not xml:
        return out, False
    try:
        root = ET.fromstring(xml.encode("utf-8"))
    except ET.ParseError:
        net.log(kind="bad_rss", url=host)
        return out, False
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        f = {"locations": []}
        for ch in item.iter():
            n = _local(ch.tag)
            if n in ("title", "link", "description", "pubDate", "guid", "department", "remoteStatus"):
                f.setdefault(n, (ch.text or "").strip())
            elif n in ("city", "name", "country", "location") and (ch.text or "").strip():
                f["locations"].append(ch.text.strip())
        out.append(posting("teamtailor", row, f.get("guid") or f.get("link"), f.get("title"),
                           "; ".join(dict.fromkeys(f["locations"])), f.get("link"), _rss_date(f.get("pubDate")),
                           strip_html(f.get("description")), f.get("department", ""), "",
                           f.get("remoteStatus", "")))
    return out, True


def _rss_date(s):
    import email.utils
    try:
        return email.utils.parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


# ---------------- Personio ----------------
def personio(net, row):
    slug = row["ats_key"]
    xml = net.get(f"https://{slug}.jobs.personio.de/xml", as_json=False)
    out = []
    if not xml:
        return out, False
    root = ET.fromstring(xml.encode("utf-8"))
    for p in root.iter("position"):
        g = lambda t: (p.findtext(t) or "").strip()
        desc = "\n".join(f"{(d.findtext('name') or '')}\n{strip_html(d.findtext('value'))}" for d in p.iter("jobDescription"))
        out.append(posting("personio", row, g("id"), g("name"), g("office"),
                           f"https://{slug}.jobs.personio.de/job/{g('id')}", g("createdAt"), desc,
                           g("department"), g("employmentType")))
    return out, True


# ---------------- Workday (public CXS endpoints behind the career site) ----------------
def _workday_sweden_facet(facets):
    """Find the facet value that selects Sweden (country or location facet), if the site has one."""
    stack = [(None, f) for f in facets or []]
    while stack:
        param, f = stack.pop()
        if not isinstance(f, dict):
            continue
        param = f.get("facetParameter") or param
        if str(f.get("descriptor", "")).strip().lower() in ("sweden", "sverige") and f.get("id") and param:
            return param, f["id"]
        stack.extend((param, v) for v in f.get("values") or [])
    return None


def workday(net, row, detail_cap=600):
    site_url = row["ats_key"].rstrip("/")
    p = urllib.parse.urlsplit(site_url)
    tenant = p.netloc.split(".")[0]
    segs = [s for s in p.path.split("/") if s and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", s)]
    if not segs:
        return [], False
    site = segs[-1]
    base = f"{p.scheme}://{p.netloc}/wday/cxs/{tenant}/{site}"
    first = net.get(f"{base}/jobs", method="POST", body={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
    if first is None:
        return [], False
    # Prefer the site's own Sweden facet; a small board is read whole; a big global board
    # without a country facet falls back to a text search for "Sweden".
    fac = _workday_sweden_facet(first.get("facets"))
    applied, text = ({fac[0]: [fac[1]]}, "") if fac else ({}, "" if first.get("total", 0) <= 2000 else "Sweden")
    out, offset, seen, total = [], 0, set(), 0
    while offset < 2000:
        d = net.get(f"{base}/jobs", method="POST",
                    body={"appliedFacets": applied, "limit": 20, "offset": offset, "searchText": text})
        if d is None:
            break
        total = total or d.get("total", 0)      # Workday only reports the total on the first page
        items = d.get("jobPostings", [])
        for j in items:
            path = j.get("externalPath", "")
            if path in seen:
                continue
            seen.add(path)
            loc = j.get("locationsText", "")
            desc, posted, country = "", j.get("postedOn", ""), "Sweden" if fac else ""
            if fac or in_sweden(loc) or "location" in loc.lower():
                if len(out) < detail_cap:
                    det = net.get(base + path)
                    info = (det or {}).get("jobPostingInfo", {}) or {}
                    desc = strip_html(info.get("jobDescription"))
                    loc = info.get("location") or loc
                    country = (info.get("country") or {}).get("descriptor", "") or country
                    posted = info.get("startDate") or posted
            out.append(posting("workday", row, path.rsplit("_", 1)[-1] or path, j.get("title"), loc,
                               f"{p.scheme}://{p.netloc}/{site}{path}", posted, desc, country=country))
        offset += 20
        if not items or offset >= total:
            break
    return out, True


# ---------------- Eightfold ----------------
def _ts_date(ts):
    try:
        ts = int(ts)
        return _ms_date(ts if ts > 10 ** 11 else ts * 1000)
    except (TypeError, ValueError):
        return ""


def eightfold_pcsx(net, row, detail_cap=200):
    """Newer Eightfold career sites (e.g. jobs.ericsson.com): /api/pcsx/search, 10 per page."""
    host = row["ats_key"].replace("https://", "").strip("/")
    domain = row.get("domain", "")
    out, start, ok, count = [], 0, False, None
    while start < 2000:
        d = net.get(f"https://{host}/api/pcsx/search",
                    params={"domain": domain, "query": "", "location": "Sweden", "start": start})
        data = (d or {}).get("data") or {}
        pos = data.get("positions") or []
        if d is None:
            break
        ok = True
        count = data.get("count", count)
        for p in pos:
            det = {}
            if len(out) < detail_cap:
                det = (net.get(f"https://{host}/api/pcsx/position_details",
                               params={"position_id": p["id"], "domain": domain, "hl": "en"}) or {}).get("data") or {}
            out.append(posting("eightfold", row, p["id"], det.get("name") or p.get("name", ""),
                               "; ".join(det.get("locations") or p.get("locations") or []),
                               det.get("publicUrl") or f"https://{host}/careers/job/{p['id']}",
                               _ts_date(det.get("postedTs") or p.get("postedTs")), strip_html(det.get("jobDescription", "")),
                               det.get("department") or p.get("department", ""), "", det.get("workLocationOption", "")))
        start += len(pos)
        if not pos or (count is not None and start >= count):
            break
    return out, ok


def eightfold(net, row, detail_cap=200):
    out, ok = eightfold_pcsx(net, row, detail_cap)
    if ok and out:
        return out, ok
    host = row["ats_key"].replace("https://", "").strip("/")
    domain = row.get("domain", "")
    out, start, ok = [], 0, False
    while start < 2000:
        d = net.get(f"https://{host}/api/apply/v2/jobs",
                    params={"domain": domain, "start": start, "num": 100, "location": "Sweden"})
        if d is None:
            break
        ok = True
        pos = d.get("positions", [])
        for j in pos:
            locs = j.get("locations") or [j.get("location", "")]
            desc = j.get("job_description", "")
            if not desc and len(out) < detail_cap:
                det = net.get(f"https://{host}/api/apply/v2/jobs/{j.get('id')}", params={"domain": domain})
                desc = (det or {}).get("job_description", "")
            out.append(posting("eightfold", row, j.get("id"), j.get("name"), "; ".join(locs),
                               j.get("canonicalPositionUrl", ""), _ms_date((j.get("t_create") or 0) * 1000),
                               strip_html(desc), j.get("department", "")))
        start += len(pos)
        if not pos or start >= d.get("count", 0):
            break
    return out, ok


# ---------------- Deel job boards (server-rendered Next.js pages) ----------------
_JOBLINK = re.compile(r'href="(/[^"/]+/job-details/([0-9a-f-]{36})[^"]*)"')


def deel(net, row, detail_cap=200):
    slug = row["ats_key"]
    page = net.get(f"https://jobs.deel.com/{slug}", as_json=False)
    if not page:
        return [], False
    out = []
    jobs = _next_data_jobs(page)
    if not jobs:          # fall back to links + detail pages
        jobs = [{"id": m.group(2), "path": m.group(1)} for m in _JOBLINK.finditer(page)]
    if not jobs:          # app-router pages ship the list inside escaped RSC payload strings
        flat = page.replace('\\"', '"').replace("\\/", "/")
        uuid = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        hits = [(m.start(), m.group(1)) for m in re.finditer(r'"id"\s*:\s*"(' + uuid + r')"(?=[^{}]{0,400}"title")', flat)]
        for k, (pos, jid) in enumerate(hits):
            # the job's own fields sit between its id and the next job's id
            chunk = flat[pos:hits[k + 1][0] if k + 1 < len(hits) else pos + 3000]
            t = re.search(r'"title"\s*:\s*"([^"]{1,200})"', chunk)
            place = _SE_RX.search(chunk)
            jobs.append({"id": jid, "title": t.group(1) if t else "", "location": place.group(1) if place else ""})
        if not jobs:
            jobs = [{"id": i} for i in re.findall(r"job-details/(" + uuid + ")", flat)]
    jobs = list({j["id"]: j for j in jobs}.values())
    if not jobs:
        net.log(kind="no_jobs_found", url=f"https://jobs.deel.com/{slug}", page_bytes=len(page),
                next_data="__NEXT_DATA__" in page, rsc="__next_f" in page)
    for j in jobs[:detail_cap]:
        jid = j.get("id")
        url = f"https://jobs.deel.com/{slug}/job-details/{jid}/overview"
        title, loc, desc = j.get("title", ""), j.get("location", ""), j.get("description", "")
        if not desc:
            det = net.get(url, as_json=False) or ""
            nd = _next_data(det)
            if nd:
                blob = json.dumps(nd)
                title = title or _first(nd, "title") or _first(nd, "name")
                loc = loc or _first(nd, "location") or _first(nd, "locationName")
                desc = strip_html(_first(nd, "description") or "")
            if not desc:
                m = re.search(r"<h1[^>]*>(.*?)</h1>", det, re.S)
                title = title or (strip_html(m.group(1)) if m else "")
                desc = strip_html(re.sub(r"(?is)<(script|style).*?</\1>", " ", det))[:20000]
        loc = loc if isinstance(loc, str) else json.dumps(loc)
        if not in_sweden(loc):          # location often only in the rendered text
            m = _SE_RX.search(desc[:3000])
            loc = loc or (m.group(1) if m else "")
        out.append(posting("deel", row, jid, title, loc, url, j.get("posted", ""), desc))
    return out, True


def _next_data(page):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _first(obj, key):
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if key in o and isinstance(o[key], (str, int)) and o[key]:
                return o[key]
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None


def _next_data_jobs(page):
    nd = _next_data(page)
    if not nd:
        return None
    found = []
    stack = [nd]
    while stack:
        o = stack.pop()
        if isinstance(o, list) and o and all(isinstance(x, dict) for x in o) and \
                any(("title" in x or "name" in x) and "id" in x for x in o[:3]):
            for x in o:
                if re.fullmatch(r"[0-9a-f-]{36}", str(x.get("id", ""))):
                    found.append({"id": x["id"], "title": x.get("title") or x.get("name", ""),
                                  "location": x.get("location") or x.get("locationName") or "",
                                  "posted": x.get("publishedAt") or x.get("createdAt") or ""})
        elif isinstance(o, dict):
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return list({j["id"]: j for j in found}.values()) or None


# ---------------- generic HTML careers page (last resort) ----------------
_JOBPATH = re.compile(r"/(jobs?|positions?|vacanc|lediga|jobb|career/job|careers/job|opening|annons)", re.I)


def _html_location(body, row):
    """A careers page rarely marks up its location. Take the first Swedish place named near
    the top of the ad; failing that, a Swedish employer's own site (.se domain, or a public
    body) is taken to advertise Swedish jobs, using the sites listed for it."""
    m = _SE_RX.search(body[:3000])
    if m:
        return m.group(1)
    if (row.get("domain", "").endswith(".se") or row.get("tier") == "public") and row.get("sweden_sites"):
        return row["sweden_sites"].split(";")[0]
    return ""


def html(net, row, cap=60):
    url = row.get("ats_key") or row.get("careers_url")
    page = net.get(url, as_json=False) if url else None
    if not page:
        return [], False
    base = urllib.parse.urlsplit(url)
    links = []
    for href in re.findall(r'href="([^"#]+)"', page):
        u = urllib.parse.urljoin(url, htmllib.unescape(href))
        pu = urllib.parse.urlsplit(u)
        if pu.netloc == base.netloc and _JOBPATH.search(pu.path) and u.rstrip("/") != url.rstrip("/") \
                and len(pu.path.strip("/").split("/")) >= 2:
            links.append(u)
    out = []
    for u in list(dict.fromkeys(links))[:cap]:
        det = net.get(u, as_json=False)
        if not det:
            continue
        m = re.search(r"<h1[^>]*>(.*?)</h1>", det, re.S) or re.search(r"<title>(.*?)</title>", det, re.S)
        body = strip_html(re.sub(r"(?is)<(script|style|nav|footer|header).*?</\1>", " ", det))
        out.append(posting("html", row, u, strip_html(m.group(1)) if m else "", _html_location(body, row), u, "",
                           body[:20000]))
    return out, True


ADAPTERS = dict(greenhouse=greenhouse, lever=lever, ashby=ashby, workable=workable,
                smartrecruiters=smartrecruiters, recruitee=recruitee, teamtailor=teamtailor,
                personio=personio, workday=workday, eightfold=eightfold, deel=deel, html=html)
