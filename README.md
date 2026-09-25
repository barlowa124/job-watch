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
- Optional aggregators: Adzuna (free tier) and SerpApi Google Jobs,
  activated by environment variables.
- Optional macOS notification via `osascript` when new relevant postings
  appear.

No third-party dependencies. Python 3.9+.

## Usage

```
python3 check_jobs.py            # digest of new postings
python3 check_jobs.py --all      # everything currently open
python3 check_jobs.py --probe    # which ATS answered per company
python3 check_jobs.py --quiet    # write digest file only
```

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
| `adzuna_queries` / `serpapi_queries` | aggregator search terms |
| `manual_check_urls` | boards with no public API, listed at the digest bottom |

Optional env vars:

```
export ADZUNA_APP_ID=...   # developer.adzuna.com, free tier
export ADZUNA_APP_KEY=...
export SERPAPI_KEY=...     # serpapi.com, google_jobs engine
export JOB_WATCH_NOTIFY=0  # disable macOS notification
```

## Scheduled runs

A launchd plist for weekly Monday 9 AM runs is in
`deploy/com.user.jobwatch.plist`. Install:

```
cp deploy/com.user.jobwatch.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.jobwatch.plist
```

## Notes

- This covers company boards directly, which is more complete for a
  targeted watchlist than scraping Indeed or LinkedIn. Neither has a
  public job-search API; both block scraping. The aggregator integrations
  exist for the tail of the market.
- `seen.json` and digest files are local state and gitignored.
