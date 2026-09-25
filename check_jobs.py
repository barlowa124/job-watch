#!/usr/bin/env python3
"""Job board watcher for impact-aligned roles.

Probes the public job-board APIs (Greenhouse, Lever, Ashby) of a company
watchlist, plus optional aggregator APIs (Adzuna, SerpApi Google Jobs).
Deduplicates against seen.json so each run reports only new or reopened
postings, and flags postings that disappeared since the last run.

No third-party dependencies. macOS notifications via osascript when new
relevant postings appear.

Usage:
    python3 check_jobs.py              # digest of new postings
    python3 check_jobs.py --all        # re-report all currently open postings
    python3 check_jobs.py --probe      # print which ATS responded per company
    python3 check_jobs.py --quiet      # write digest file only, no stdout

Config: watchlist.json (companies, keywords, aggregator queries).
State:  seen.json (url -> {first_seen, last_seen}).
Output: digest-YYYY-MM-DD.md in this directory.

Env vars (optional):
    ADZUNA_APP_ID, ADZUNA_APP_KEY   free tier at developer.adzuna.com
    SERPAPI_KEY                   serpapi.com, google_jobs engine
    JOB_WATCH_NOTIFY=0            disable macOS notification
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
WATCHLIST = json.loads((HERE / "watchlist.json").read_text())
SEEN_PATH = HERE / "seen.json"
_raw_seen = json.loads(SEEN_PATH.read_text()) if SEEN_PATH.exists() else {}
SEEN = {url: (meta if isinstance(meta, dict)
              else {"first_seen": meta, "last_seen": meta})
        for url, meta in _raw_seen.items()}

TIMEOUT = 15


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "job-watch/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _loc(v):
    if isinstance(v, dict):
        return v.get("name", "")
    return v or ""


def probe_greenhouse(slug):
    data = get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not isinstance(data, dict) or "jobs" not in data:
        return None
    return [{"title": j["title"], "url": j["absolute_url"],
             "location": _loc(j.get("location")),
             "body": j.get("content", "")}
            for j in data["jobs"]]


def probe_lever(slug):
    data = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(data, list):
        return None
    return [{"title": j["text"], "url": j["hostedUrl"],
             "location": _loc((j.get("categories") or {}).get("location")),
             "body": j.get("descriptionPlain", "")}
            for j in data]


def probe_ashby(slug):
    data = get_json(
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        "?includeCompensation=true")
    if not isinstance(data, dict) or "jobs" not in data:
        return None
    return [{"title": j["title"], "url": j.get("jobUrl") or "",
             "location": _loc(j.get("location")),
             "body": j.get("descriptionPlain") or j.get("descriptionHtml", "")}
            for j in data["jobs"]]


PROBES = {"greenhouse": probe_greenhouse,
          "lever": probe_lever,
          "ashby": probe_ashby}


def discover_company(company):
    """Probe ATS endpoints for each slug; keep the first that answers.

    If watchlist.json pins an "ats" field for the company, try that probe
    first to skip needless requests.
    """
    order = list(PROBES)
    if company.get("ats") in PROBES:
        order.remove(company["ats"])
        order.insert(0, company["ats"])
    for slug in company["slugs"]:
        for ats in order:
            jobs = PROBES[ats](slug)
            if jobs:
                for j in jobs:
                    j["company"] = company["name"]
                    j["ats"] = ats
                return {"name": company["name"], "ats": ats,
                        "slug": slug, "jobs": jobs}
    return {"name": company["name"], "ats": None, "slug": None, "jobs": []}


def zintellect():
    """ORISE fellowship catalog (EPA/NIH/USDA research appointments).

    Uses the site's public DataTables endpoint. No key required.
    """
    out = []
    for q in WATCHLIST.get("zintellect_queries", []):
        data = urllib.parse.urlencode({
            "draw": "1", "start": "0", "length": "25",
            "search[value]": q, "search[regex]": "false",
        }).encode()
        req = urllib.request.Request(
            "https://www.zintellect.com/Catalog/Index_DataTableResult",
            data=data, headers={
                "User-Agent": "job-watch/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                payload = json.loads(r.read())
        except Exception:
            continue
        for j in payload.get("data", []):
            ref = j.get("referenceCode", "")
            if not ref:
                continue
            out.append({
                "title": j.get("title", ""), "ats": "zintellect",
                "url": f"https://www.zintellect.com/Opportunity/Details/{ref}",
                "location": j.get("location", ""),
                "company": f"ORISE ({j.get('posted', '')})",
                "body": ""})
    return out


def adzuna():
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY", "")
    if not app_id or not app_key:
        return None
    out = []
    for q in WATCHLIST["adzuna_queries"]:
        url = (f"https://api.adzuna.com/v1/api/jobs/us/search/1"
               f"?app_id={app_id}&app_key={app_key}&results_per_page=30"
               f"&what={urllib.parse.quote_plus(q)}"
               f"&max_days_old=30&content-type=application/json")
        data = get_json(url)
        for j in (data or {}).get("results", []):
            out.append({"title": j["title"], "url": j["redirect_url"],
                        "location": _loc(j.get("location", {}).get("display_name")
                                         if isinstance(j.get("location"), dict)
                                         else j.get("location")),
                        "company": (j.get("company") or {}).get("display_name", "Adzuna"),
                        "body": j.get("description", ""), "ats": "adzuna"})
    return out


def serpapi():
    key = os.environ.get("SERPAPI_KEY", "")
    if not key:
        return None
    out = []
    for q in WATCHLIST["serpapi_queries"]:
        url = ("https://serpapi.com/search.json?engine=google_jobs"
               f"&q={urllib.parse.quote_plus(q)}&location=United+States"
               f"&api_key={key}")
        data = get_json(url)
        for j in (data or {}).get("jobs_results", []):
            link = (j.get("share_link")
                    or (j.get("related_links") or [{}])[0].get("link", ""))
            out.append({"title": j.get("title", ""), "url": link,
                        "location": j.get("location", ""),
                        "company": j.get("company_name", "Google Jobs"),
                        "body": j.get("description", ""), "ats": "serpapi"})
    return out


KEY_RE = re.compile("|".join(re.escape(k)
                    for k in WATCHLIST["relevance_keywords"]), re.I)
EXCLUDE_RE = re.compile("|".join(re.escape(k) for k in
                        WATCHLIST.get("exclude_title_keywords", [])), re.I) \
    if WATCHLIST.get("exclude_title_keywords") else None
SEN_RE = re.compile(r"\b(" + "|".join(
    k.replace(".", r"\.") for k in WATCHLIST["seniority_flags"]) + r")\b", re.I)
LOC_RE = re.compile("|".join(
    r"\b" + re.escape(k) + r"\b"
    for k in WATCHLIST.get("preferred_locations", [])), re.I) \
    if WATCHLIST.get("preferred_locations") else None


DOMAIN_RE = re.compile("|".join(re.escape(k) for k in
                       WATCHLIST.get("domain_keywords", [])), re.I) \
    if WATCHLIST.get("domain_keywords") else None
YEARS_RE = re.compile(r"(\d+)\+?\s*(?:or more\s+)?years?", re.I)
PHD_RE = re.compile(r"ph\.?d\.?", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def score(job):
    """Return (relevant, senior, loc_match, domain_hits, level_hint)."""
    title = job["title"]
    relevant = bool(KEY_RE.search(title)) and not (
        EXCLUDE_RE and EXCLUDE_RE.search(title))
    senior = bool(SEN_RE.search(title))
    loc_match = bool(LOC_RE and LOC_RE.search(job.get("location", "")))

    body = TAG_RE.sub(" ", job.get("body", ""))
    hits = sorted({m.lower() for m in DOMAIN_RE.findall(body)})[:6] \
        if DOMAIN_RE else []

    years = [int(y) for y in YEARS_RE.findall(body) if int(y) <= 15]
    level = []
    if years:
        level.append(f"{max(years)}+ yrs")
    if PHD_RE.search(body):
        phd_ctx = body[max(0, PHD_RE.search(body).start() - 100):
                       PHD_RE.search(body).end() + 100].lower()
        level.append("PhD preferred" if "prefer" in phd_ctx or
                     "or equivalent" in phd_ctx else "PhD")
    return relevant, senior, loc_match, hits, level


def notify(count, new_relevant_titles, digest_path):
    hook = os.environ.get("JOB_WATCH_WEBHOOK", "")
    if hook and count:
        payload = json.dumps({
            "text": f"job-watch: {count} new relevant posting(s)",
            "digest": str(digest_path),
            "titles": new_relevant_titles[:10]}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(
                hook, data=payload,
                headers={"Content-Type": "application/json"}),
                timeout=TIMEOUT)
        except Exception:
            pass
    if os.environ.get("JOB_WATCH_NOTIFY", "1") == "0" or count == 0:
        return
    if sys.platform != "darwin":
        return
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{count} new relevant posting(s)" '
         f'with title "job-watch"'], check=False)


def main():
    show_all = "--all" in sys.argv
    quiet = "--quiet" in sys.argv
    if "--probe" in sys.argv:
        with ThreadPoolExecutor(max_workers=10) as ex:
            for fut in as_completed(
                    {ex.submit(discover_company, c): c
                     for c in WATCHLIST["companies"]}):
                r = fut.result()
                board = (f"{r['ats']}:{r['slug']} ({len(r['jobs'])} jobs)"
                         if r["ats"] else "no board found")
                print(f"{r['name']:25} {board}")
        return

    all_jobs, probed = [], set()
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(discover_company, c): c
                for c in WATCHLIST["companies"]}
        for fut in as_completed(futs):
            r = fut.result()
            all_jobs.extend(r["jobs"])
            if r["ats"]:
                probed.add(r["name"])

    for source, fn in (("zintellect", zintellect),
                       ("adzuna", adzuna), ("serpapi", serpapi)):
        try:
            jobs = fn()
            if jobs:
                all_jobs.extend(jobs)
            elif jobs is None and not quiet:
                print(f"[{source}] skipped (no API key)", file=sys.stderr)
        except Exception as e:
            print(f"[{source}] error: {e}", file=sys.stderr)

    today = date.today().isoformat()
    current_urls = {j["url"] for j in all_jobs if j["url"]}
    new_jobs = []
    for j in all_jobs:
        if not j["url"]:
            continue
        if j["url"] in SEEN:
            SEEN[j["url"]]["last_seen"] = today
        else:
            SEEN[j["url"]] = {"first_seen": today, "last_seen": today}
            new_jobs.append(j)

    # A posting is closed if its company's board answered this run and
    # the posting is absent. Boards that failed to answer are skipped to
    # avoid mass false-closures on transient errors.
    closed = [{"title": m.get("title", url), "url": url,
               "company": m.get("company", "?")}
              for url, m in SEEN.items()
              if url not in current_urls
              and m.get("source") == "watchlist"
              and m.get("company") in probed]
    # Drop closed entries older than 60 days from state to bound file size.
    for url, m in list(SEEN.items()):
        if url not in current_urls and m.get("last_seen", today) < today \
                and (date.today() - date.fromisoformat(m["last_seen"])).days > 60:
            del SEEN[url]

    for j in all_jobs:
        if j["url"] in SEEN and "title" not in SEEN[j["url"]]:
            SEEN[j["url"]].update({"title": j["title"], "company": j["company"],
                                   "source": "watchlist" if j["ats"] in PROBES else j["ats"]})

    SEEN_PATH.write_text(json.dumps(SEEN, indent=1, sort_keys=True))

    report = all_jobs if show_all else new_jobs
    relevant = [(j, *score(j)) for j in report]
    relevant = [x for x in relevant if x[1]]
    # Ordering: attainable first (no seniority flag), local/remote first,
    # then most domain-keyword overlap, then alpha by company.
    relevant.sort(key=lambda x: (x[2], not x[3], -len(x[4]),
                                 x[0]["company"], x[0]["title"]))

    n_new_relevant = sum(1 for j in new_jobs if score(j)[0])

    lines = [f"# Job digest {today}",
             f"New: {len(new_jobs)} ({n_new_relevant} relevant) | "
             f"Open across boards: {len(all_jobs)} | "
             f"Closed since last seen: {len(closed)}", ""]
    lines.append("## New relevant postings\n")
    for j, _, senior, loc_match, hits, level in relevant:
        flags = []
        if senior:
            flags.append("seniority")
        if loc_match:
            flags.append("location match")
        flag = f" *({', '.join(flags)})*" if flags else ""
        meta = ""
        if level or hits:
            meta = " `" + " · ".join(
                ([", ".join(level)] if level else []) + hits) + "`"
        lines.append(f"- [{j['company']}] [{j['title']}]"
                     f"({j['url']}) — {j.get('location', '')}{flag}{meta}")
    if closed:
        lines += ["", "## Closed since last check\n"]
        lines += [f"- [{c['company']}] {c['title']}" for c in closed[:20]]
    lines += ["", "## Manual checks\n"]
    lines += [f"- {u}" for u in WATCHLIST["manual_check_urls"]]

    digest = "\n".join(lines)
    out = HERE / f"digest-{today}.md"
    out.write_text(digest)
    notify(n_new_relevant, [j["title"] for j, *_ in relevant], out)
    if not quiet:
        print(digest)


if __name__ == "__main__":
    main()
