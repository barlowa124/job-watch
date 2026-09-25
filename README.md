# job-watch

Watches the public job-board APIs of a company watchlist and reports new
postings. Built for tracking small numbers of targeted companies where a
general job aggregator misses the niche.

## What it does

- Probes Greenhouse, Lever, and Ashby public JSON APIs for each company
  in `watchlist.json`. Board slugs do not need to be exact: the script
  tries each candidate slug against all three ATS endpoints and keeps the
  first that answers. Run `--probe` to see what resolved.
- Deduplicates against `seen.json`. Each run reports only new postings.
- Flags seniority in titles and preferred-location matches, sorts
  attainable roles first.
- Tracks postings that disappeared since the last run, so closed roles
  do not sit silently in the backlog.
- Aggregators: ORISE/Zintellect fellowship catalog (no key needed),
  Adzuna (free tier) and SerpApi Google Jobs via env vars.
- Annotates each posting with domain-keyword hits found in the body and
  a level hint parsed from the text (`N+ yrs`, `PhD` vs `PhD preferred`).
- Optional macOS notification via `osascript`, plus `JOB_WATCH_WEBHOOK`
  for a generic JSON webhook (Slack, Discord, Zapier, etc.).

No third-party dependencies. Python 3.9+.

## Usage

```
python3 check_jobs.py            # digest of new postings
python3 check_jobs.py --all      # everything currently open
python3 check_jobs.py --probe    # which ATS answered per company
python3 check_jobs.py --quiet    # write digest file only
python3 check_jobs.py --since 2026-09-01   # postings first seen after a date
```

Discover boards for new companies:

```
python3 resolve_boards.py believermeats.com meatable.com
```

It fetches each domain's careers page, extracts ATS links
(Greenhouse/Lever/Ashby/Workable/SmartRecruiters/BambooHR/Workday), and
verifies candidates against the APIs. Paste verified slugs into
`watchlist.json`.

Output: `digest-YYYY-MM-DD.md`. State: `seen.json`.

## Configuration

`watchlist.json`:

| field | purpose |
|---|---|
| `companies` | name, candidate board `slugs`, optional pinned `ats` |
| `relevance_keywords` | title keywords that mark a posting relevant |
| `exclude_title_keywords` | title keywords that drop a posting (e.g. `finance`, `clinical`) |
| `seniority_flags` | title words that push a posting to the bottom |
| `preferred_locations` | location keywords to highlight |
| `adzuna_queries` / `serpapi_queries` / `zintellect_queries` | aggregator search terms |
| `domain_keywords` | body keywords counted per posting and shown in the digest |
| `manual_check_urls` | boards with no public API, listed at the digest bottom |

Optional env vars — export them, or drop them in
`~/.config/job-watch/env` (one `KEY=value` per line, loaded at startup
and by the launchd job):

```
ADZUNA_APP_ID=...        # developer.adzuna.com, free tier
ADZUNA_APP_KEY=...
SERPAPI_KEY=...          # serpapi.com, google_jobs engine
JOB_WATCH_NOTIFY=0       # disable macOS notification
JOB_WATCH_WEBHOOK=...    # POST digest summary as JSON
```

## Tests

```
python3 -m unittest test_check_jobs -v
```

Covers the ATS parsers, board discovery order, Zintellect mapping, and
the scoring and level heuristics. No network access required.

## Scheduled runs

A launchd plist for weekly Monday 9 AM runs is in
`deploy/com.user.jobwatch.plist`. A GitHub Actions workflow
(`.github/workflows/watch.yml`) does the same weekly run in CI and
commits `seen.json` plus the digest back to the repo, so it works with
the laptop off. Install launchd:

```
cp deploy/com.user.jobwatch.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.jobwatch.plist
```

## Notes

- This covers company boards directly, which is more complete for a
  targeted watchlist than scraping Indeed or LinkedIn. Neither has a
  public job-search API. Both block scraping. The aggregator integrations
  exist for the tail of the market.
- `seen.json` and digest files are committed: they are the CI state and
  a running log of what the watchlist produced.
