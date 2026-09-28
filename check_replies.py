#!/usr/bin/env python3
"""Watch Apple Mail for employer replies to job applications.

Queries Mail.app over AppleScript for recent messages in the inbox and junk
mailbox, matches them against a local watchlist of employer sender domains and
reply keywords, deduplicates against seen_replies.json, and reports new hits:

- employer-domain mail that is not an auto-confirmation -> tier REPLY
- employer-domain mail that is an auto-confirmation   -> tier CONFIRMATION
- reply-ish subject from an unknown non-bulk sender   -> tier REPLY

New items are appended to replies.log and shown as a macOS notification.
State: seen_replies.json. Config: reply_watchlist.json (falls back to
reply_watchlist.example.json). Run `python3 check_replies.py` to check now,
`--quiet` to suppress stdout, `--hours N` to change the lookback window.
"""

import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "reply_watchlist.json")
EXAMPLE_CONFIG = os.path.join(HERE, "reply_watchlist.example.json")
SEEN = os.path.join(HERE, "seen_replies.json")
LOG = os.path.join(HERE, "replies.log")

LOOKBACK_HOURS = 72

APPLESCRIPT = """
tell application "Mail"
    set out to ""
    set cutoff to (current date) - %d * hours
    repeat with mb in {inbox, junk mailbox}
        try
            set msgs to (messages of mb whose date received > cutoff)
            repeat with m in msgs
                set out to out & (id of m as string) & tab & ¬
                    (date received of m as string) & tab & ¬
                    (sender of m) & tab & (subject of m) & linefeed
            end repeat
        end try
    end repeat
    return out
end tell
"""


def load_config():
    path = CONFIG if os.path.exists(CONFIG) else EXAMPLE_CONFIG
    with open(path) as f:
        cfg = json.load(f)
    return {
        "employer": [s.lower() for s in cfg.get("employer_senders", [])],
        "bulk": [s.lower() for s in cfg.get("bulk_ignore_senders", [])],
        "reply_kw": [s.lower() for s in cfg.get("reply_keywords", [])],
        "confirm_kw": [s.lower() for s in cfg.get("confirmation_keywords", [])],
    }


def load_seen():
    try:
        with open(SEEN) as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_seen(seen):
    tmp = SEEN + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sorted(seen)[-5000:], f)
    os.replace(tmp, SEEN)


def fetch_messages(hours):
    script = APPLESCRIPT % hours
    out = subprocess.run(
        ["osascript", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "osascript failed")
    msgs = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        msgs.append(
            {
                "id": parts[0].strip(),
                "date": parts[1].strip(),
                "sender": parts[2].strip(),
                "subject": "\t".join(parts[3:]).strip(),
            }
        )
    return msgs


def sender_addr(sender):
    m = re.search(r"<([^>]+)>", sender)
    return (m.group(1) if m else sender).lower()


def classify(msg, cfg):
    addr = sender_addr(msg["sender"])
    subj = msg["subject"].lower()
    hay = addr + " " + msg["sender"].lower()

    is_employer = any(d in hay for d in cfg["employer"])
    is_bulk = any(d in hay for d in cfg["bulk"])
    is_confirm = any(k in subj for k in cfg["confirm_kw"])
    is_replyish = any(k in subj for k in cfg["reply_kw"])

    if is_employer:
        return "CONFIRMATION" if is_confirm else "REPLY"
    if is_replyish and not is_bulk and not is_confirm:
        return "REPLY"
    return None


def notify(title, body):
    if os.environ.get("JOB_REPLY_NOTIFY", "1") == "0":
        return
    safe_t = title.replace('"', "'")[:80]
    safe_b = body.replace('"', "'")[:180]
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "{safe_b}" with title "{safe_t}"',
        ],
        capture_output=True,
    )


def main():
    args = sys.argv[1:]
    quiet = "--quiet" in args
    hours = LOOKBACK_HOURS
    if "--hours" in args:
        hours = int(args[args.index("--hours") + 1])

    cfg = load_config()
    seen = load_seen()
    try:
        msgs = fetch_messages(hours)
    except Exception as exc:
        print(f"mail query failed: {exc}", file=sys.stderr)
        return 1

    new = []
    for m in msgs:
        if not m["id"] or m["id"] in seen:
            continue
        seen.add(m["id"])
        tier = classify(m, cfg)
        if tier:
            m["tier"] = tier
            new.append(m)

    stamp = time.strftime("%Y-%m-%d %H:%M")
    with open(LOG, "a") as f:
        for m in new:
            line = f"{stamp}  [{m['tier']}]  {m['date']}  {m['sender']}  |  {m['subject']}"
            f.write(line + "\n")
            if not quiet:
                print(line)

    replies = [m for m in new if m["tier"] == "REPLY"]
    if replies:
        first = replies[0]
        notify(
            f"Job reply: {first['sender'][:40]}",
            f"{first['subject']} (+{len(replies)-1} more)" if len(replies) > 1 else first["subject"],
        )
    save_seen(seen)
    if not quiet:
        print(f"checked {len(msgs)} messages, {len(new)} new, {len(replies)} replies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
