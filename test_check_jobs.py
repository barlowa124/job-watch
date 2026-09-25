#!/usr/bin/env python3
"""Tests for check_jobs.py: board probes, scoring, level heuristics.

Run: python3 -m unittest test_check_jobs -v
"""

import unittest
from unittest.mock import patch

import check_jobs as cj


class ProbeTests(unittest.TestCase):

    def test_greenhouse_parses_jobs(self):
        payload = {"jobs": [
            {"title": "ML Engineer", "absolute_url": "https://x/1",
             "location": {"name": "Remote"}, "content": "<p>PyTorch</p>"}]}
        with patch.object(cj, "get_json", return_value=payload):
            jobs = cj.probe_greenhouse("acme")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["location"], "Remote")

    def test_greenhouse_empty_board_is_empty_list(self):
        with patch.object(cj, "get_json", return_value={"jobs": []}):
            self.assertEqual(cj.probe_greenhouse("acme"), [])

    def test_greenhouse_404_is_none(self):
        with patch.object(cj, "get_json", return_value=None):
            self.assertIsNone(cj.probe_greenhouse("nope"))

    def test_lever_parses_jobs(self):
        payload = [{"text": "Scientist", "hostedUrl": "https://x/2",
                    "categories": {"location": "Boston"},
                    "descriptionPlain": "seq"}]
        with patch.object(cj, "get_json", return_value=payload):
            jobs = cj.probe_lever("acme")
        self.assertEqual(jobs[0]["title"], "Scientist")

    def test_ashby_string_and_dict_location(self):
        payload = {"jobs": [
            {"title": "A", "jobUrl": "u1", "location": "SF office"},
            {"title": "B", "jobUrl": "u2",
             "location": {"name": "Remote"}}]}
        with patch.object(cj, "get_json", return_value=payload):
            jobs = cj.probe_ashby("acme")
        self.assertEqual(jobs[0]["location"], "SF office")
        self.assertEqual(jobs[1]["location"], "Remote")

    def test_discover_stops_at_first_answer(self):
        calls = []
        with patch.dict(cj.PROBES, {
                "greenhouse": lambda s: calls.append(("gh", s)) or None,
                "lever": lambda s: calls.append(("lv", s)) or [],
                "ashby": lambda s: calls.append(("ab", s)) or None}):
            r = cj.discover_company({"name": "X", "slugs": ["x"]})
        self.assertEqual(r["ats"], "lever")
        self.assertNotIn(("ab", "x"), calls)

    def test_discover_uses_pinned_ats_first(self):
        calls = []
        with patch.dict(cj.PROBES, {
                "greenhouse": lambda s: calls.append(("gh", s)) or [],
                "lever": lambda s: calls.append(("lv", s)) or None,
                "ashby": lambda s: calls.append(("ab", s)) or []}):
            r = cj.discover_company(
                {"name": "X", "slugs": ["x"], "ats": "ashby"})
        self.assertEqual(r["ats"], "ashby")
        self.assertEqual(calls[0], ("ab", "x"))


class ZintellectTests(unittest.TestCase):

    def _opps(self):
        return {"data": [
            {"referenceCode": "EPA-ORD-2026-01", "title": "Comp Tox",
             "location": "RTP, NC", "posted": "09-01-2026"},
            {"title": "no ref, skipped"}]}

    def test_zintellect_maps_reference_codes(self):
        cj.WATCHLIST["zintellect_queries"] = ["toxicology"]
        import urllib.request
        class R:
            def __init__(self, b): self.b = b
            def read(self): return self.b
            def __enter__(self): return self
            def __exit__(self, *a): return False
        import json
        body = json.dumps(self._opps()).encode()
        with patch.object(urllib.request, "urlopen", return_value=R(body)):
            jobs = cj.zintellect()
        self.assertEqual(len(jobs), 1)
        self.assertIn("EPA-ORD-2026-01", jobs[0]["url"])
        self.assertEqual(jobs[0]["location"], "RTP, NC")


class ScoreTests(unittest.TestCase):

    def _job(self, title, loc="", body=""):
        return {"title": title, "location": loc, "body": body,
                "company": "T", "url": "u", "ats": "test"}

    def test_relevant_title(self):
        self.assertTrue(cj.score(self._job("Machine Learning Engineer"))[0])

    def test_excluded_title(self):
        self.assertFalse(cj.score(self._job("Finance Manager"))[0])

    def test_irrelevant_title(self):
        self.assertFalse(cj.score(self._job("Entomologist"))[0])

    def test_seniority_flag(self):
        self.assertTrue(cj.score(self._job("Senior Data Scientist"))[1])
        self.assertFalse(cj.score(self._job("Data Scientist"))[1])

    def test_location_match_word_boundary(self):
        self.assertTrue(cj.score(self._job("X", loc="Raleigh, NC"))[2])
        self.assertFalse(cj.score(self._job("X", loc="San Francisco"))[2])

    def test_domain_hits_from_body(self):
        _, _, _, hits, _ = cj.score(
            self._job("Scientist", body="PyTorch and bayesian protein work"))
        self.assertIn("protein", hits)
        self.assertIn("bayesian", hits)
        self.assertIn("pytorch", hits)

    def test_level_years_and_phd(self):
        _, _, _, _, level = cj.score(
            self._job("Scientist",
                      body="Requires 3+ years experience. PhD preferred."))
        self.assertIn("3+ yrs", level)
        self.assertIn("PhD preferred", level)

    def test_level_phd_required(self):
        _, _, _, _, level = cj.score(
            self._job("Scientist", body="A PhD is required for this role."))
        self.assertIn("PhD", level)
        self.assertNotIn("PhD preferred", level)

    def test_body_html_stripped(self):
        _, _, _, hits, _ = cj.score(
            self._job("Scientist", body="<p>uses <b>protein</b></p>"))
        self.assertIn("protein", hits)


if __name__ == "__main__":
    unittest.main()
