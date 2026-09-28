#!/usr/bin/env python3
"""Repost detection: flag a new posting that looks like a previously
closed one under a fresh URL or ID.

Boards relist roles constantly. URL-keyed dedup (seen.json) cannot see
through a new posting ID. This module scores a new posting against
recently closed ones at the same company.

Two scorers, same interface:
- token similarity (default, zero-dep): Jaccard over normalized title
  tokens plus location match. Catches identical and lightly retitled
  reposts.
- embedding similarity (optional): cosine over E5-small-v2 embeddings
  from vdb_mcp (pip install vector-db-mcp[embed]). Used only when the
  package imports cleanly; catches retitles with different wording.
"""
from __future__ import annotations

import re

# Jaccard on normalized title tokens above which a same-company pair is
# reported as a probable repost. Identical titles score 1.0. A repost
# that gains or drops a seniority or team word still clears this.
REPOST_MIN_TOKEN_SIM = 0.6
# Cosine over E5 passage embeddings. Near-identical text sits ~0.95+.
REPOST_MIN_COSINE = 0.90

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return set(_WORD.findall(text.lower()))


def token_similarity(a, b):
    """Jaccard similarity over normalized title tokens, plus a small
    bonus when the location strings match."""
    ta, tb = _tokens(a["title"]), _tokens(b["title"])
    if not ta or not tb:
        return 0.0
    sim = len(ta & tb) / len(ta | tb)
    la, lb = a.get("location", ""), b.get("location", "")
    if la and lb and _tokens(la) == _tokens(lb):
        sim = min(1.0, sim + 0.1)
    return sim


def _embedder():
    try:
        from vdb_mcp.embed import embed_passage
        import numpy as np
    except Exception:
        return None

    def sim(a, b):
        va = embed_passage(f"{a['title']} {a.get('location', '')}")
        vb = embed_passage(f"{b['title']} {b.get('location', '')}")
        return float(np.dot(va, vb))

    return sim


def scorer():
    """Best available similarity function: vdb_mcp embeddings when
    installed, else token Jaccard."""
    emb = _embedder()
    if emb is not None:
        return emb, REPOST_MIN_COSINE, "embedding"
    return token_similarity, REPOST_MIN_TOKEN_SIM, "token"


def find_reposts(new_jobs, closed):
    """Match each new posting against closed postings at the same
    company. Returns {new_url: (closed_url, score, scorer_name)}."""
    sim, threshold, name = scorer()
    out = {}
    for j in new_jobs:
        best = None
        for c in closed:
            if c.get("company") != j.get("company"):
                continue
            s = sim(j, c)
            if s >= threshold and (best is None or s > best[1]):
                best = (c["url"], s)
        if best:
            out[j["url"]] = (best[0], round(best[1], 3), name)
    return out
