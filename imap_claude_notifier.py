#!/usr/bin/env python3
"""
IMAP -> Claude -> Telegram email notifier

Checks a mailbox (e.g. Hostinger) for new mail, summarizes/triages each
new email with Claude, and sends the summary to Telegram.

Designed to be run PERIODICALLY (Windows Task Scheduler, cron, or a VPS
timer) rather than as a 24/7 process. Each run:
  1. Connects via IMAP
  2. Finds messages newer than the last processed UID (stored in state.json)
  3. Sends each one to Claude for a short triage summary
  4. Sends the summary to your Telegram chat
  5. Saves the new highest UID so it won't re-notify next run

Nothing is deleted, moved, or marked read/unread in your mailbox --
this only reads.
"""

import os
import sys
import json
import ssl
import email
import imaplib
import logging
from email.header import decode_header
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------- Config ----------
load_dotenv()

IMAP_HOST = os.getenv("IMAP_HOST", "imap.hostinger.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")
IMAP_FOLDER = os.getenv("IMAP_FOLDER", "INBOX")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STATE_FILE = Path(__file__).parent / "state.json"
MAX_BODY_CHARS = 4000  # trim long emails before sending to Claude

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("imap_claude_notifier")


def require_env():
    missing = [
        name for name, val in [
            ("IMAP_USER", IMAP_USER),
            ("IMAP_PASSWORD", IMAP_PASSWORD),
            ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
        ] if not val
    ]
    if missing:
        log.error("Missing required .env values: %s", ", ".join(missing))
        sys.exit(1)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            log.warning("state.json corrupt, starting fresh")
    return {"last_uid": 0}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def decode_mime_words(s):
    if not s:
        return ""
    parts = decode_header(s)
    decoded = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded += text.decode(enc or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


def get_body(msg):
    """Best-effort plain text body extraction from an email.message.Message."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp:
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    continue
        return "(no readable body found)"
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            return msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            return "(could not decode body)"


def fetch_new_emails(last_uid):
    context = ssl.create_default_context()
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=context) as imap:
        imap.login(IMAP_USER, IMAP_PASSWORD)
        imap.select(IMAP_FOLDER)

        status, data = imap.uid("search", None, "ALL")
        if status != "OK":
            log.error("IMAP search failed: %s", status)
            return [], last_uid

        uids = [int(u) for u in data[0].split()] if data[0] else []
        new_uids = [u for u in uids if u > last_uid]

        emails = []
        max_uid = last_uid
        for uid in new_uids:
            status, msg_data = imap.uid("fetch", str(uid), "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject = decode_mime_words(msg.get("Subject"))
            sender = decode_mime_words(msg.get("From"))
            date = msg.get("Date", "")
            body = get_body(msg)[:MAX_BODY_CHARS]

            emails.append({
                "uid": uid,
                "subject": subject,
                "from": sender,
                "date": date,
                "body": body,
            })
            max_uid = max(max_uid, uid)

        return emails, max_uid


def summarize_with_claude(email_item):
    prompt = f"""You are triaging one email for a busy professional.

From: {email_item['from']}
Subject: {email_item['subject']}
Date: {email_item['date']}

Body:
{email_item['body']}

Reply in exactly this format, nothing else:
SUMMARY: <1-2 sentence summary of what this email is about>
URGENCY: <Low / Medium / High>
ACTION: <what, if anything, needs to be done -- or "None, informational">"""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(text_blocks).strip() or "(Claude returned no summary)"


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=15)
    if not resp.ok:
        log.error("Telegram send failed: %s - %s", resp.status_code, resp.text)


def main():
    require_env()
    state = load_state()
    last_uid = state.get("last_uid", 0)

    log.info("Checking %s for mail newer than UID %s", IMAP_USER, last_uid)
    try:
        emails, new_last_uid = fetch_new_emails(last_uid)
    except imaplib.IMAP4.error as e:
        log.error("IMAP error: %s", e)
        sys.exit(1)

    if not emails:
        log.info("No new emails.")
        return

    log.info("Found %d new email(s).", len(emails))
    for item in emails:
        try:
            summary = summarize_with_claude(item)
        except Exception as e:
            log.error("Claude summarization failed for UID %s: %s", item["uid"], e)
            summary = "SUMMARY: (Claude call failed)\nURGENCY: Unknown\nACTION: Check email manually"

        message = (
            f"\U0001F4E7 <b>New Email</b>\n"
            f"<b>From:</b> {item['from']}\n"
            f"<b>Subject:</b> {item['subject']}\n\n"
            f"{summary}"
        )
        send_telegram(message)
        log.info("Notified for UID %s: %s", item["uid"], item["subject"])

    state["last_uid"] = new_last_uid
    save_state(state)


if __name__ == "__main__":
    main()
