#!/usr/bin/env python3
"""Robustness battery: malformed ATS payloads, scoring edge cases,
and resolver verify/regex paths.

Run: python3 -m unittest test_robustness -v
"""

import unittest
from unittest.mock import patch

import check_jobs as cj
import resolve_boards as rb


class ProbeMalformedPayloads(unittest.TestCase):
    """A single malformed job record must not kill the whole board."""

    def test_greenhouse_jobs_not_list(self):
        # board-level malformed payload -> probe reports dead (None),
        # same contract as a network failure
        for payload in [{"jobs": None}, {"jobs": {"a": 1}}, {"jobs": "x"}]:
            with self.subTest(payload=payload):
                with patch.object(cj, "get_json", return_value=payload):
                    self.assertIsNone(cj.probe_greenhouse("acme"))

    def test_greenhouse_job_missing_title(self):
        payload = {"jobs": [{"absolute_url": "https://x/1"},
                            {"title": "Good", "absolute_url": "u"}]}
        with patch.object(cj, "get_json", return_value=payload):
            out = cj.probe_greenhouse("acme")
        self.assertEqual([j["title"] for j in out], ["Good"])

    def test_greenhouse_missing_url_key(self):
        payload = {"jobs": [{"title": "T"}]}
        with patch.object(cj, "get_json", return_value=payload):
            out = cj.probe_greenhouse("acme")
        self.assertEqual(out[0]["url"], "")  # missing url degrades to ""

    def test_lever_job_missing_keys(self):
        payload = [{"text": "Eng"}, {}, {"categories": None}]
        with patch.object(cj, "get_json", return_value=payload):
            out = cj.probe_lever("acme")
        self.assertEqual([j["title"] for j in out], ["Eng"])

    def test_ashby_dict_payload_no_jobs_key(self):
        with patch.object(cj, "get_json", return_value={"other": []}):
            self.assertIsNone(cj.probe_ashby("acme"))

    def test_probes_return_none_on_network_fail(self):
        with patch.object(cj, "get_json", return_value=None):
            for probe in (cj.probe_greenhouse, cj.probe_lever, cj.probe_ashby):
                self.assertIsNone(probe("acme"))


class LocHelper(unittest.TestCase):
    def test_dict_string_none(self):
        self.assertEqual(cj._loc({"name": "Remote"}), "Remote")
        self.assertEqual(cj._loc("NYC"), "NYC")
        self.assertEqual(cj._loc(None), "")
        self.assertEqual(cj._loc({}), "")


class ScoreEdges(unittest.TestCase):
    def test_missing_body_and_location(self):
        job = {"title": "Machine Learning Engineer"}
        relevant, senior, loc, hits, level = cj.score(job)
        self.assertTrue(relevant)
        self.assertFalse(loc)
        self.assertIsInstance(hits, list)

    def test_year_cap_filters_implausible(self):
        job = {"title": "ML Engineer",
               "body": "requires 30+ years experience and PhD preferred"}
        *_, level = cj.score(job)
        # 30 > 15 cap -> filtered out; PhD context may still appear
        self.assertFalse(any("30" in l for l in level))

    def test_exclusion_regex_beats_keyword(self):
        # exclude_title_keywords are non-technical roles; a title
        # hitting both KEY_RE and EXCLUDE_RE must lose
        if cj.EXCLUDE_RE:
            self.assertFalse(cj.score(
                {"title": "Machine Learning Recruiter", "body": ""})[0])
            self.assertFalse(cj.score(
                {"title": "Data Science Account Manager", "body": ""})[0])

    def test_domain_hits_capped_and_lowered(self):
        job = {"title": "ML Engineer",
               "body": "Python PYTHON python PyTorch pytorch PYTORCH " * 5}
        *_, hits, _ = cj.score(job)
        self.assertTrue(all(h == h.lower() for h in hits))
        self.assertLessEqual(len(hits), 6)


class ResolverVerify(unittest.TestCase):
    def test_unknown_ats_none(self):
        self.assertIsNone(rb.verify("workday", "acme"))

    def test_bad_json_none(self):
        with patch.object(rb, "fetch", return_value=("not json", "u")):
            self.assertIsNone(rb.verify("greenhouse", "acme"))

    def test_jobs_not_list_none(self):
        with patch.object(rb, "fetch", return_value=('{"jobs": {"x": 1}}', "u")):
            self.assertIsNone(rb.verify("greenhouse", "acme"))

    def test_counts_jobs(self):
        with patch.object(rb, "fetch",
                          return_value=('{"jobs": [{"a":1},{"a":2}]}', "u")):
            self.assertEqual(rb.verify("greenhouse", "acme"), 2)

    def test_fetch_failure_none(self):
        with patch.object(rb, "fetch", return_value=(None, None)):
            self.assertIsNone(rb.verify("lever", "acme"))

    def test_ats_patterns_extract_slugs(self):
        html = ('<a href="https://boards.greenhouse.io/acme">jobs</a>'
                '<a href="https://jobs.lever.co/bigcorp">careers</a>')
        found = {(ats, slug) for ats, pat in rb.ATS_PATTERNS
                 for slug in set(__import__("re").findall(pat, html))}
        self.assertIn(("greenhouse", "acme"), found)
        self.assertIn(("lever", "bigcorp"), found)


if __name__ == "__main__":
    unittest.main()
