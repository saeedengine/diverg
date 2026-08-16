# BTC 5-Minute RSI Divergence Monitor → Telegram

Checks BTC/USD every 5 minutes for a regular RSI divergence (price/RSI moving
in opposite directions at a swing point), filtered to only fire when the RSI
involved is overbought (>70) or oversold (<30), and sends you a Telegram
message when one is found. Runs for free on GitHub Actions — nothing needs
to stay on at your end.

No external Python packages are required (uses only the standard library),
and the price data comes from Kraken's public API (no account/key needed).

## 1. Create your Telegram bot

1. In Telegram, open a chat with **@BotFather**.
2. Send `/newbot` and follow the prompts (pick any name/username).
3. BotFather replies with a token that looks like `123456789:AAExample-Token`.
   Copy it — this is your `TELEGRAM_BOT_TOKEN`.

## 2. Get your chat ID

1. Open a chat with the bot you just created and send it any message (e.g. "hi").
2. In your browser, visit (replacing `<TOKEN>`):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Find `"chat":{"id":123456789, ...}` in the response — that number is your
   `TELEGRAM_CHAT_ID`.

## 3. Create the GitHub repo

1. Create a new **public** repository on GitHub (public keeps Actions minutes
   completely free — running every 5 minutes uses more minutes than the
   private-repo free tier allows). Your bot token stays safe either way,
   since it's stored as a GitHub Secret, never in the code.
2. Upload these files, keeping the folder structure:
   - `btc_divergence_monitor.py`
   - `state.json`
   - `.github/workflows/monitor.yml`

## 4. Add your secrets

In the repo: **Settings → Secrets and variables → Actions → New repository secret**

- `TELEGRAM_BOT_TOKEN` = the token from step 1
- `TELEGRAM_CHAT_ID` = the ID from step 2

## 5. Turn it on

Go to the **Actions** tab, enable workflows if prompted, open "BTC RSI
Divergence Monitor", and click **Run workflow** to fire a manual test run.
Check the run logs — it should print either "No new divergence signal this
run" or confirm it sent an alert. After that it runs automatically every 5
minutes on its own.

## Notes / tuning

- `PIVOT_LOOKBACK` (default 3) controls how many bars on each side confirm a
  swing pivot — higher = fewer, more reliable signals but more delay; lower =
  faster but noisier.
- `RSI_PERIOD`, `OVERBOUGHT` (70), and `OVERSOLD` (30) are all constants near
  the top of `btc_divergence_monitor.py`.
- GitHub's schedule isn't millisecond-precise — during high load on GitHub's
  infra, a run can be delayed by a few minutes. Not an issue for this kind of
  monitoring, but worth knowing.
- The workflow commits `state.json` back to the repo every run (that's how it
  avoids re-sending the same alert, and also keeps the repo "active" so
  GitHub doesn't auto-disable the schedule after 60 days of no commits).
- This tool only sends you information — it doesn't place trades. Treat any
  alert as something to verify yourself before acting on it.
