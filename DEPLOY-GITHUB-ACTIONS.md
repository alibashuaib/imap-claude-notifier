# Deploy with GitHub Actions (no local install, browser only)

This runs the script on GitHub's servers on a schedule. You manage it entirely
through github.com in your browser — nothing installed on your PC.

## 1. Create a GitHub account (skip if you have one)
https://github.com/signup

## 2. Create a new repository
1. Click **+ → New repository** (top right)
2. Name it anything, e.g. `imap-claude-notifier`
3. Set it to **Public** (fine — your credentials live in encrypted Secrets,
   never in the code, and public repos get unlimited free Actions minutes)
4. Click **Create repository**

## 3. Upload the files
On the new repo's page:
1. Click **Add file → Upload files**
2. Drag in `imap_claude_notifier.py` and `requirements.txt`
3. Commit directly to the `main` branch

Then create the workflow file (GitHub can't upload folders via drag-and-drop,
so create it manually):
1. Click **Add file → Create new file**
2. In the filename box, type exactly: `.github/workflows/imap-notify.yml`
   (typing the slashes auto-creates the folders)
3. Paste in the contents of the `imap-notify.yml` file provided
4. Commit directly to `main`

## 4. Add your secrets
Go to **Settings → Secrets and variables → Actions → New repository secret**,
and add each of these one at a time (name exactly as shown, value is yours):

| Secret name | Value |
|---|---|
| `IMAP_HOST` | `imap.hostinger.com` (confirm in hPanel) |
| `IMAP_PORT` | `993` |
| `IMAP_USER` | your full email address |
| `IMAP_PASSWORD` | your email password |
| `IMAP_FOLDER` | `INBOX` |
| `ANTHROPIC_API_KEY` | from console.anthropic.com → Settings → API Keys |
| `CLAUDE_MODEL` | `claude-sonnet-5` |
| `TELEGRAM_BOT_TOKEN` | from @BotFather on Telegram |
| `TELEGRAM_CHAT_ID` | see step 5 |

**Getting your Telegram chat ID:**
1. Message **@BotFather** → `/newbot` → follow prompts → copy the token
2. Send your new bot any message (e.g. "hi")
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in your browser
4. Find `"chat":{"id":123456789,...}` — that number is `TELEGRAM_CHAT_ID`

## 5. Allow the workflow to save its progress file
Go to **Settings → Actions → General → Workflow permissions**, select
**"Read and write permissions"**, click **Save**.
(This lets it commit `state.json` back to the repo so it remembers which
emails it already notified you about.)

## 6. Run it
Go to the **Actions** tab → click **IMAP Claude Notifier** on the left →
click **Run workflow** (button on the right) → **Run workflow**.

Heads up: the first run will summarize your *entire* current inbox — if you
have hundreds of emails, expect a flood of Telegram messages. After that,
every run only covers new mail since the last check.

## 7. It's live
From here it runs automatically every 10 minutes, forever, with your PC
off, Claude closed, nothing installed anywhere. Check progress any time in
the **Actions** tab — green check = ran fine, red X = click in to see the
error (usually a wrong secret value).

## Adjusting the check frequency
Edit `.github/workflows/imap-notify.yml`, change the cron line, e.g.:
- Every 5 min: `*/5 * * * *`
- Every 30 min: `*/30 * * * *`
- Every hour: `0 * * * *`

Edit directly on github.com: open the file → pencil icon → change → commit.
