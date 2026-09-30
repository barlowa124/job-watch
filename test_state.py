#!/usr/bin/env python3
"""Tests for check_jobs.py main(): seen-state, dedup, closure, reposts.

The interesting behavior lives in main() rather than the probe helpers:
first_seen/last_seen bookkeeping, closure only when a board answered,
stale-entry pruning, and repost flags in the digest. These tests drive
main() with patched discovery and watchlist so no network is touched.

Run: python3 -m unittest test_state -v
"""

import json
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import check_jobs as cj


def _job(title, url, company="Acme", ats="greenhouse",
         location="Remote", body=""):
    return {"title": title, "url": url, "location": location,
            "body": body, "company": company, "ats": ats}


class MainHarness(unittest.TestCase):
    """Run main() against a tmp dir + controlled discovery."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.seen_path = root / "seen.json"
        self.seen = {}
        self.today = date.today().isoformat()

        # Controlled relevance regex; patched so the test does not depend
        # on the live watchlist's keyword list.
        self._patches = [
            patch.object(cj, "HERE", root),
            patch.object(cj, "SEEN_PATH", self.seen_path),
            patch.object(cj, "SEEN", self.seen),
            patch.object(cj, "WATCHLIST",
                         {"companies": [{"name": "Acme", "slugs": ["acme"]}],
                          "manual_check_urls": []}),
            patch.object(cj, "KEY_RE", re.compile(r"engineer", re.I)),
            patch.object(cj, "SEN_RE", re.compile(r"senior", re.I)),
            patch.object(cj, "LOC_RE", re.compile(r"remote", re.I)),
            patch.object(cj, "DOMAIN_RE", None),
            patch.object(cj, "notify", lambda *a, **k: None),
            # Aggregator stubs return [] so they contribute nothing.
            patch.object(cj, "zintellect", lambda: []),
            patch.object(cj, "adzuna", lambda: []),
            patch.object(cj, "serpapi", lambda: []),
            patch.object(cj, "altprotein", lambda: []),
            patch.object(cj, "eawork", lambda: []),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, jobs, argv=None):
        with patch.object(cj, "discover_company", return_value={
                "name": "Acme", "ats": "greenhouse", "slug": "acme",
                "jobs": jobs}), \
                patch.object(sys, "argv", argv or ["check_jobs.py", "--quiet"]):
            cj.main()
        return (Path(self.tmp.name) / f"digest-{self.today}.md").read_text()

    def test_new_job_marked_and_digested(self):
        digest = self.run_main([_job("ML Engineer", "https://b/1")])
        self.assertIn("[Acme] [ML Engineer](https://b/1)", digest)
        self.assertIn("New: 1", digest)
        self.assertEqual(self.seen["https://b/1"]["first_seen"], self.today)

    def test_second_run_not_new_and_last_seen_advances(self):
        jobs = [_job("ML Engineer", "https://b/1")]
        self.run_main(jobs)

        tomorrow = date.today() + timedelta(days=1)

        class FakeDate(date):
            @classmethod
            def today(cls):
                return tomorrow

        with patch.object(cj, "date", FakeDate):
            self.today = tomorrow.isoformat()
            digest = self.run_main(jobs)
        self.assertIn("New: 0", digest)
        self.assertEqual(self.seen["https://b/1"]["last_seen"],
                         tomorrow.isoformat())
        # first_seen preserved across runs
        self.assertNotEqual(self.seen["https://b/1"]["first_seen"],
                            tomorrow.isoformat())

    def test_closed_only_when_board_answered(self):
        url = "https://b/old"
        self.seen[url] = {"first_seen": self.today, "last_seen": self.today,
                          "title": "Old Role", "company": "Acme",
                          "source": "watchlist"}
        digest = self.run_main([_job("ML Engineer", "https://b/1")])
        self.assertIn("Closed since last check", digest)
        self.assertIn("Old Role", digest)

    def test_no_closure_when_board_did_not_answer(self):
        url = "https://b/old"
        self.seen[url] = {"first_seen": self.today, "last_seen": self.today,
                          "title": "Old Role", "company": "Other",
                          "source": "watchlist"}
        # discover_company still answers Acme only; "Other" was never
        # probed this run, so its missing job must NOT be closed.
        digest = self.run_main([_job("ML Engineer", "https://b/1")])
        self.assertNotIn("Old Role", digest)

    def test_stale_seen_entries_pruned(self):
        old = (date.today() - timedelta(days=cj.STALE_SEEN_DAYS + 5))
        url = "https://b/ancient"
        self.seen[url] = {"first_seen": old.isoformat(),
                          "last_seen": old.isoformat()}
        self.run_main([_job("ML Engineer", "https://b/1")])
        self.assertNotIn(url, self.seen)

    def test_recent_gone_entry_kept(self):
        recent = (date.today() - timedelta(days=3))
        url = "https://b/gone"
        self.seen[url] = {"first_seen": recent.isoformat(),
                          "last_seen": recent.isoformat()}
        self.run_main([_job("ML Engineer", "https://b/1")])
        self.assertIn(url, self.seen)

    def test_repost_flag_in_digest(self):
        closed_url = "https://b/old-ml"
        self.seen[closed_url] = {
            "first_seen": self.today, "last_seen": self.today,
            "title": "Machine Learning Engineer", "company": "Acme",
            "source": "watchlist"}
        digest = self.run_main(
            [_job("Machine Learning Engineer", "https://b/new-ml",
                  location="Remote")])
        self.assertIn("possible repost", digest)

    def test_state_written_atomically(self):
        self.run_main([_job("ML Engineer", "https://b/1")])
        on_disk = json.loads(self.seen_path.read_text())
        self.assertIn("https://b/1", on_disk)
        self.assertFalse((self.seen_path.with_suffix(".tmp")).exists())

    def test_probe_mode_lists_boards(self):
        out = []
        with patch.object(cj, "discover_company", return_value={
                "name": "Acme", "ats": "greenhouse", "slug": "acme",
                "jobs": []}), \
                patch.object(sys, "argv", ["check_jobs.py", "--probe"]), \
                patch("builtins.print", out.append):
            cj.main()
        self.assertTrue(any("Acme" in str(l) for l in out))


if __name__ == "__main__":
    unittest.main()
