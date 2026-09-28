#!/usr/bin/env python3
"""Watch Apple Mail for employer replies to job applications.

Queries Mail.app over AppleScript for recent messages in the inbox and junk
mailbox, matches them against a local watchlist of employer sender domains and
reply keywords, deduplicates against seen_replies.json, and reports new hits:

- employer-domain mail whose body declines candidacy   -> tier REJECTION
- employer-domain mail that is not an auto-confirmation -> tier REPLY
- employer-domain mail that is an auto-confirmation    -> tier CONFIRMATION
- reply-ish subject from an unknown non-bulk sender    -> tier REPLY

Message bodies are fetched only for employer-domain senders (rare), because
ATS platforms reuse identical subjects for confirmations and rejections —
subject alone cannot distinguish them.

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

# Bodies are fetched in a separate targeted pass: only employer-domain
# messages need them (rare), and per-message content reads are the slow part.
BODY_SCRIPT = """
tell application "Mail"
    set out to ""
    repeat with mb in {inbox, junk mailbox}
        try
            repeat with mid in {%s}
                try
                    set m to first message of mb whose id is (mid as integer)
                    set b to content of m
                    if (count of b) > 4000 then set b to text 1 thru 4000 of b
                    set AppleScript's text item delimiters to {return, linefeed, tab}
                    set bItems to text items of b
                    set AppleScript's text item delimiters to " "
                    set bFlat to bItems as string
                    set out to out & (mid as string) & tab & bFlat & linefeed
                end try
            end repeat
        end try
    end repeat
    return out
end tell
"""

DEFAULT_REJECTION_KEYWORDS = [
    "not move forward",
    "not to move forward",
    "not be moving forward",
    "will not be moving forward",
    "won't be moving forward",
    "no longer under consideration",
    "decided not to proceed",
    "not an ideal fit",
    "isn't an ideal fit",
    "is not an ideal fit",
    "not selected to move forward",
    "unable to move forward with your",
    "pursue other candidates",
    "other candidates whose",
    "decided to move forward with other",
    "not to move forward with your candidacy",
    "regret to inform",
]


def load_config():
    path = CONFIG if os.path.exists(CONFIG) else EXAMPLE_CONFIG
    with open(path) as f:
        cfg = json.load(f)
    return {
        "employer": [s.lower() for s in cfg.get("employer_senders", [])],
        "bulk": [s.lower() for s in cfg.get("bulk_ignore_senders", [])],
        "reply_kw": [s.lower() for s in cfg.get("reply_keywords", [])],
        "confirm_kw": [s.lower() for s in cfg.get("confirmation_keywords", [])],
        "reject_kw": [
            s.lower()
            for s in cfg.get("rejection_keywords", DEFAULT_REJECTION_KEYWORDS)
        ],
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


def _run_osascript(script, timeout=240):
    out = subprocess.run(
        ["osascript", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "osascript failed")
    return out.stdout


def fetch_messages(hours):
    msgs = []
    for line in _run_osascript(APPLESCRIPT % hours).splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        msgs.append(
            {
                "id": parts[0].strip(),
                "date": parts[1].strip(),
                "sender": parts[2].strip(),
                "subject": "\t".join(parts[3:]).strip(),
                "body": "",
            }
        )
    return msgs


def fetch_bodies(msgs, employer_domains):
    """Fill msg['body'] for employer-domain messages via a targeted id lookup."""
    ids = []
    for m in msgs:
        hay = m["sender"].lower()
        if any(d in hay for d in employer_domains):
            ids.append(m["id"])
    if not ids:
        return
    id_list = ", ".join(str(int(i)) for i in ids)
    try:
        out = _run_osascript(BODY_SCRIPT % id_list)
    except Exception:
        return
    bodies = {}
    for line in out.splitlines():
        mid, _, body = line.partition("\t")
        bodies[mid.strip()] = body.strip()
    for m in msgs:
        if m["id"] in bodies:
            m["body"] = bodies[m["id"]]


def sender_addr(sender):
    m = re.search(r"<([^>]+)>", sender)
    return (m.group(1) if m else sender).lower()


def classify(msg, cfg):
    addr = sender_addr(msg["sender"])
    subj = msg["subject"].lower()
    hay = addr + " " + msg["sender"].lower()

    body = msg.get("body", "").lower()

    is_employer = any(d in hay for d in cfg["employer"])
    is_bulk = any(d in hay for d in cfg["bulk"])
    if is_bulk:
        return None
    is_confirm = any(k in subj for k in cfg["confirm_kw"]) or any(
        k in body for k in cfg["confirm_kw"]
    )
    is_rejection = any(k in body for k in cfg["reject_kw"])
    is_replyish = any(k in subj for k in cfg["reply_kw"])

    if is_employer:
        if is_rejection:
            return "REJECTION"
        # Employer mail with no fetched body can't be told from a rejection
        # that reuses a confirmation subject; flag it rather than guess.
        if not body:
            return "REPLY"
        return "CONFIRMATION" if is_confirm else "REPLY"
    if is_replyish and not is_confirm and not is_rejection:
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
    fetch_bodies(msgs, cfg["employer"])

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

    actionable = [m for m in new if m["tier"] in ("REPLY", "REJECTION")]
    if actionable:
        first = actionable[0]
        notify(
            f"Job {first['tier'].lower()}: {first['sender'][:40]}",
            f"{first['subject']} (+{len(actionable)-1} more)"
            if len(actionable) > 1
            else first["subject"],
        )
    save_seen(seen)
    if not quiet:
        n_rej = sum(1 for m in new if m["tier"] == "REJECTION")
        n_rep = sum(1 for m in new if m["tier"] == "REPLY")
        print(
            f"checked {len(msgs)} messages, {len(new)} new, "
            f"{n_rep} replies, {n_rej} rejections"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
