#!/usr/bin/env python3
"""Tests for check_prs.py: event collection, seen-key bookkeeping,
CI conclusion surfacing.

Run: python3 -m unittest test_check_prs -v
"""

import unittest
from unittest.mock import patch

import check_prs as cp


def _gh_map(pulls=None, issue_comments=None, review_comments=None,
            reviews=None, check_runs=None, pr_sha="abc"):
    """Route gh_api calls to canned payloads by URL shape."""
    def fake(path):
        if path.endswith("/check-runs"):
            return {"check_runs": check_runs or []}
        if path.endswith("/reviews"):
            return reviews or []
        if "/pulls/" in path and path.endswith("/comments"):
            return review_comments or []
        if "/issues/" in path and path.endswith("/comments"):
            return issue_comments or []
        if "/pulls/" in path:
            return {"head": {"sha": pr_sha}}
        raise AssertionError(f"unexpected gh_api path: {path}")
    return fake


class CheckPrTests(unittest.TestCase):

    def _run(self, seen, **kw):
        events = []
        with patch.object(cp, "gh_api", side_effect=_gh_map(**kw)):
            cp.check_pr("org/repo", 7, "pr:org/repo:7", seen, events)
        return events

    def test_new_comment_emitted_once(self):
        seen = {}
        kw = dict(issue_comments=[{"id": 1, "user": {"login": "al"},
                                   "body": "lgtm"}],
                  pr_sha="abc")
        events = self._run(seen, **kw)
        self.assertEqual(len(events), 1)
        self.assertIn("comment by al", events[0])
        # Second run with the same seen state emits nothing.
        self.assertEqual(self._run(seen, **kw), [])

    def test_commented_reviews_skipped(self):
        events = self._run({}, reviews=[
            {"id": 1, "state": "COMMENTED", "user": {"login": "al"},
             "body": "nit"},
            {"id": 2, "state": "APPROVED", "user": {"login": "bo"},
             "body": "ship"}])
        self.assertEqual(len(events), 1)
        self.assertIn("APPROVED", events[0])

    def test_ci_failure_surfaces_success_silent(self):
        seen = {}
        events = self._run(seen, check_runs=[
            {"name": "build", "conclusion": "failure", "status": "completed"},
            {"name": "lint", "conclusion": "success", "status": "completed"}])
        self.assertEqual(len(events), 1)
        self.assertIn("build -> failure", events[0])
        self.assertIn("lint=success", seen["pr:org/repo:7:checks"])

    def test_ci_same_conclusion_not_repeated(self):
        seen = {}
        kw = dict(check_runs=[
            {"name": "build", "conclusion": "failure",
             "status": "completed"}])
        self._run(seen, **kw)
        self.assertEqual(self._run(seen, **kw), [])

    def test_check_run_api_error_tolerated(self):
        def fake(path):
            if path.endswith("/check-runs"):
                raise RuntimeError("boom")
            if path.endswith("/comments") or path.endswith("/reviews"):
                return []
            if "/pulls/" in path:
                return {"head": {"sha": "abc"}}
            return []
        events = []
        with patch.object(cp, "gh_api", side_effect=fake):
            cp.check_pr("org/repo", 7, "k", {}, events)
        self.assertEqual(events, [])


class CheckIssueTests(unittest.TestCase):

    def test_issue_comment_seen_once(self):
        seen = {}
        cmts = [{"id": 9, "user": {"login": "al"}, "body": "hi"}]
        with patch.object(cp, "gh_api", return_value=cmts):
            ev = []
            cp.check_issue("org/repo", 3, "i:org/repo:3", seen, ev)
            self.assertEqual(len(ev), 1)
            ev2 = []
            cp.check_issue("org/repo", 3, "i:org/repo:3", seen, ev2)
            self.assertEqual(ev2, [])


if __name__ == "__main__":
    unittest.main()
