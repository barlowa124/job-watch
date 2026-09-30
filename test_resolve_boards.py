#!/usr/bin/env python3
"""Tests for resolve_boards.py: ATS slug extraction, verify(), and the
resolve() homepage->careers->verify flow. All network is stubbed.

Run: python3 -m unittest test_resolve_boards -v
"""

import json
import unittest
from unittest.mock import patch

import resolve_boards as rb

HOME = "https://acme.test/"


def _pages(mapping, default=("<html>nothing</html>", None)):
    """URL -> (html, real) router for rb.fetch."""
    def fake(url):
        if url in mapping:
            return mapping[url]
        return default[0], url
    return fake


class VerifyTests(unittest.TestCase):

    def test_greenhouse_list_counts(self):
        body = json.dumps({"jobs": [{"title": "a"}, {"title": "b"}]})
        with patch.object(rb, "fetch", return_value=(body, "u")):
            self.assertEqual(rb.verify("greenhouse", "acme"), 2)

    def test_lever_top_level_list(self):
        body = json.dumps([{"text": "a"}])
        with patch.object(rb, "fetch", return_value=(body, "u")):
            self.assertEqual(rb.verify("lever", "acme"), 1)

    def test_unknown_ats(self):
        self.assertIsNone(rb.verify("workday", "acme"))

    def test_non_json_body(self):
        with patch.object(rb, "fetch",
                          return_value=("<html>no</html>", "u")):
            self.assertIsNone(rb.verify("greenhouse", "acme"))

    def test_fetch_failure(self):
        with patch.object(rb, "fetch", return_value=(None, None)):
            self.assertIsNone(rb.verify("greenhouse", "acme"))

    def test_dict_without_jobs_list(self):
        with patch.object(rb, "fetch",
                          return_value=(json.dumps({"error": "x"}), "u")):
            self.assertIsNone(rb.verify("greenhouse", "acme"))


class ResolveTests(unittest.TestCase):

    def test_finds_greenhouse_link_on_homepage(self):
        home = '<a href="https://boards.greenhouse.io/acme">jobs</a>'
        with patch.object(rb, "fetch",
                          side_effect=_pages({HOME: (home, HOME)})), \
                patch.object(rb, "verify", return_value=7):
            verified, candidates = rb.resolve("acme.test")
        self.assertIn({"ats": "greenhouse", "slug": "acme", "jobs": 7,
                       "via": ""}, verified)
        self.assertEqual(len(verified), 1)

    def test_career_path_link_followed(self):
        careers_url = "https://acme.test/careers"
        careers_html = '<a href="https://jobs.lever.co/acme/x">openings</a>'
        with patch.object(rb, "fetch", side_effect=_pages(
                {HOME: ("<html></html>", HOME),
                 careers_url: (careers_html, careers_url)})), \
                patch.object(rb, "verify", return_value=3):
            verified, _ = rb.resolve("acme.test")
        self.assertEqual(verified[0]["ats"], "lever")
        self.assertEqual(verified[0]["via"], careers_url)

    def test_unverified_candidates_reported_not_promoted(self):
        home = '<a href="https://jobs.ashbyhq.com/acme">jobs</a>'
        with patch.object(rb, "fetch",
                          side_effect=_pages({HOME: (home, HOME)})), \
                patch.object(rb, "verify", return_value=None):
            verified, candidates = rb.resolve("acme.test")
        self.assertEqual(verified, [])
        self.assertIn(("ashby", "acme", ""), candidates)

    def test_no_links_empty(self):
        with patch.object(rb, "fetch",
                          return_value=("<html></html>", "u")):
            verified, candidates = rb.resolve("acme.test")
        self.assertEqual(verified, [])
        self.assertEqual(candidates, [])

    def test_workday_pattern_matched_but_not_verified(self):
        # workday slugs are discoverable from links but have no public
        # verify endpoint; they must show up as candidates only.
        home = ('<a href="https://acme.wd5.myworkdayjobs.com/en-US/x">'
                "careers</a>")
        with patch.object(rb, "fetch",
                          side_effect=_pages({HOME: (home, HOME)})):
            verified, candidates = rb.resolve("acme.test")
        self.assertEqual(verified, [])
        self.assertIn(("workday", "acme", ""), candidates)


if __name__ == "__main__":
    unittest.main()
