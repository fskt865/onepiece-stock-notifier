# One Piece Card Stock Notifier

Watches product pages and sends a push notification the moment an item flips
from out-of-stock to in-stock. Works for any retailer whose product page is
plain HTML (TCGPlayer listings, the official One Piece card game shop, most
LGS webstores, etc.).

Three ways to run it: **hosted on GitHub** (no server needed, recommended),
a local **web GUI**, or a headless CLI.

## GitHub-hosted (serverless)

A GitHub Actions workflow (`.github/workflows/check.yml`) runs the checker
about every 10–20 minutes (GitHub delays scheduled jobs) and a GitHub Pages
site gives a GUI usable from any device to see status and edit watch targets.

One-time setup for whoever will use it:

1. **Notifications** — install the ntfy app (iOS/Android), subscribe to a
   hard-to-guess topic name (topics are public, e.g. `onepiece-restock-x7k2p9`),
   then save that name as a repository **secret** called `NTFY_TOPIC`
   (repo → Settings → Secrets and variables → Actions). Optionally add a
   `DISCORD_WEBHOOK` secret too. Secrets keep the ping channel private even
   though the repo is public.
2. **Editing from the GUI** — the Pages site is view-only until you give it a
   token. Create a *fine-grained* personal access token (GitHub → Settings →
   Developer settings → Fine-grained tokens) scoped to **only this repo** with
   **Contents: Read and write** and **Actions: Read and write**, and paste it
   into the GUI's "Editing access" panel (stored only in that browser).
   The token owner needs push access to the repo, so add your coworker as a
   collaborator first.
3. Add watch targets in the GUI. "Run check now" triggers an immediate check;
   otherwise the schedule handles it. Current status is committed back to
   `state.json` after every run.

## Local alternatives

## Setup

```bash
cd stock-notifier
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Local web GUI

```bash
python app.py
```

Open **http://localhost:8080**. From there you can:

- **Add watch targets** — name, product URL, and the phrases that indicate
  sold-out vs. in-stock. Open the product page while it's out of stock and copy
  the exact wording (e.g. "Sold Out") into the out-of-stock field; put what an
  in-stock page shows (usually "Add to Cart") in the in-stock field.
  Out-of-stock phrases are checked first, since many pages contain a disabled
  "Add to Cart" button even when sold out. Matching is case-insensitive.
  New/edited targets are checked immediately.
- **Set notifications** — ntfy topic, Discord webhook, and/or a desktop popup —
  and send a test ping to confirm they work.
- **Tune the schedule** — check interval, optional re-ping if an item stays in
  stock, and a pause toggle.
- **See live status** — each target shows In stock / Out of stock / Unknown /
  Fetch failed, when it was last checked, and a countdown to the next sweep.
  "Check now" buttons force an immediate check.

The server binds to `127.0.0.1` (local only). To reach the GUI from another
machine on your network, change the last line of `app.py` to
`app.run(host="0.0.0.0", port=8080)` — but note there's no login, so only do
that on a trusted network.

Everything is stored in `config.json` (targets + settings) and
`webstate.json` (runtime status) next to the script. Notifications fire only
on the transition to in-stock, so you don't get spammed every cycle. If a page
redesign breaks the phrase markers, you get a one-time "unknown status"
warning instead of silent failure.

### Notification channels

- **ntfy (recommended, free, pings your phone):** install the ntfy app
  (iOS/Android), subscribe to a topic with a hard-to-guess name (topics are
  public, so use something like `onepiece-restock-x7k2p9`), and enter that
  same name in the GUI.
- **Discord:** in any server channel → Edit Channel → Integrations →
  Webhooks → New Webhook, and paste the URL into the GUI.
- **Desktop:** a `notify-send` popup on the machine running the server
  (Linux only).

### Headless CLI

The original CLI still works and shares `config.json` (edit it by hand or via
the GUI first — see `config.example.json` for the format):

```bash
python stock_notifier.py           # run forever
python stock_notifier.py --once    # single check, for cron
```

Cron example (CLI keeps its own `state.json` between runs):

```cron
*/10 * * * * cd /path/to/stock-notifier && .venv/bin/python stock_notifier.py --once >> notifier.log 2>&1
```

Don't run the CLI loop and the web server at the same time — they'd each ping
independently.

## Caveats

- Some big-box sites (Walmart, Target, sometimes Best Buy) serve bot-challenge
  pages to scripts. If a target always reports "Unknown", that retailer is
  blocking simple fetchers — prefer TCGPlayer or smaller card shops for those
  listings, or lengthen the interval.
- The machine running the server has to stay on for checks to happen.
