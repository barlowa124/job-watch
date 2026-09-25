#!/usr/bin/env python3
"""Discover a company's public job board from its domain.

Fetches the homepage and careers page, looks for Greenhouse, Lever,
Ashby, Workable, SmartRecruiters, BambooHR, and generic /jobs links,
then verifies candidates against the ATS APIs.

Usage:
    python3 resolve_boards.py believermeats.com bluenalu.com ...
"""

import json
import re
import sys
import urllib.request
from urllib.parse import urljoin

UA = {"User-Agent": "Mozilla/5.0 (job-watch board resolver)"}
TIMEOUT = 15

ATS_PATTERNS = [
    ("greenhouse", r"(?:boards\.greenhouse\.io|job-boards\.greenhouse\.io)/([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.lever\.co/([A-Za-z0-9_-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("smartrecruiters", r"jobs\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("bamboohr", r"([A-Za-z0-9_-]+)\.bamboohr\.com"),
    ("workday", r"([A-Za-z0-9._-]+)\.wd\d+\.myworkdayjobs\.com"),
]

CAREER_PATHS = ["/careers", "/jobs", "/career", "/join-us", "/company/careers"]


def fetch(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8", "replace"), r.url
    except Exception:
        return None, None


def verify(ats, slug):
    urls = {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "lever": f"https://api.lever.co/v0/postings/{slug}",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
    }
    if ats not in urls:
        return None
    body, _ = fetch(urls[ats])
    if not body:
        return None
    try:
        data = json.loads(body)
    except Exception:
        return None
    if isinstance(data, dict):
        data = data.get("jobs")
    if not isinstance(data, list):
        return None
    return len(data)


def resolve(domain):
    candidates = []
    html, base = fetch(f"https://{domain}/")
    pages = [("", html, base)] if html else []
    career_hrefs = set()
    if html:
        for m in re.findall(r'href="([^"]*)"', html):
            if re.search(r"career|jobs|join|work", m, re.I):
                career_hrefs.add(urljoin(base, m))
    for path in CAREER_PATHS:
        career_hrefs.add(urljoin(f"https://{domain}/", path))
    for href in sorted(career_hrefs)[:8]:
        h, real = fetch(href)
        if h:
            pages.append((href, h, real))
    for href, html, _ in pages:
        if not html:
            continue
        for ats, pat in ATS_PATTERNS:
            for slug in set(re.findall(pat, html)):
                candidates.append((ats, slug, href))
    verified = []
    for ats, slug, src in candidates:
        n = verify(ats, slug)
        if n is not None:
            verified.append({"ats": ats, "slug": slug, "jobs": n, "via": src})
    return verified, candidates


def main():
    for domain in sys.argv[1:]:
        ok, cand = resolve(domain)
        if ok:
            for v in ok:
                print(f"{domain:30} VERIFIED {v['ats']}:{v['slug']} "
                      f"({v['jobs']} jobs) via {v['via']}")
        elif cand:
            seen = {(a, s) for a, s, _ in cand}
            for a, s in sorted(seen):
                print(f"{domain:30} candidate {a}:{s} (unverified)")
        else:
            print(f"{domain:30} no ATS links found")


if __name__ == "__main__":
    main()
