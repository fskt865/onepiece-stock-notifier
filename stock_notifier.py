#!/usr/bin/env python3
"""Watch product pages and send a notification when an item comes back in stock.

Usage:
    python stock_notifier.py                # run forever, polling on an interval
    python stock_notifier.py --once         # single check (for cron)
    python stock_notifier.py -c my.json     # use an alternate config file

See config.example.json / README.md for configuration.
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

STATE_FILE = Path(__file__).with_name("state.json")


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def check_product(product):
    """Return 'in_stock', 'out_of_stock', or 'unknown' for one product entry."""
    resp = requests.get(product["url"], headers=DEFAULT_HEADERS, timeout=30)
    resp.raise_for_status()
    page = resp.text.lower()

    # Out-of-stock markers win: many pages contain "add to cart" in dead buttons.
    for marker in product.get("out_of_stock_text", []):
        if marker.lower() in page:
            return "out_of_stock"
    for marker in product.get("in_stock_text", []):
        if marker.lower() in page:
            return "in_stock"
    return "unknown"


def notify(config, product, status_note=""):
    title = "In stock!"
    body = f"{product['name']} is available\n{product['url']}"
    if status_note:
        body += f"\n({status_note})"

    notifiers = config.get("notifications", {})
    sent = []

    # Env vars override config so secrets can stay out of a public repo (CI).
    topic = os.environ.get("NTFY_TOPIC") or notifiers.get("ntfy_topic")
    if topic:
        try:
            requests.post(
                f"https://ntfy.sh/{topic}",
                data=body.encode(),
                headers={
                    "Title": title,
                    "Priority": "high",
                    "Tags": "shopping_cart,bell",
                    "Click": product["url"],
                },
                timeout=30,
            ).raise_for_status()
            sent.append("ntfy")
        except requests.RequestException as e:
            log(f"  ntfy notification failed: {e}")

    webhook = os.environ.get("DISCORD_WEBHOOK") or notifiers.get("discord_webhook")
    if webhook:
        try:
            requests.post(
                webhook,
                json={"content": f"**{title}** {body}"},
                timeout=30,
            ).raise_for_status()
            sent.append("discord")
        except requests.RequestException as e:
            log(f"  Discord notification failed: {e}")

    if notifiers.get("desktop", False):
        try:
            subprocess.run(
                ["notify-send", "-u", "critical", title, body],
                check=False,
                timeout=10,
            )
            sent.append("desktop")
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"  desktop notification failed: {e}")

    log(f"  notified via: {', '.join(sent) if sent else 'NOTHING (no notifiers configured!)'}")
    return sent


def run_checks(config, state):
    renotify_after = config.get("renotify_minutes", 0) * 60
    for product in config["products"]:
        name = product["name"]
        prev = state.get(name, {})
        try:
            status = check_product(product)
        except requests.RequestException as e:
            log(f"{name}: fetch failed ({e})")
            continue

        log(f"{name}: {status}")
        now = time.time()

        if status == "unknown":
            # Page layout changed or bot-blocked; tell someone once so it gets fixed.
            if prev.get("status") != "unknown":
                notify(config, product,
                       "warning: couldn't determine stock status - check the page markers")
        elif status == "in_stock":
            first_time = prev.get("status") != "in_stock"
            stale = renotify_after and now - prev.get("notified_at", 0) > renotify_after
            if first_time or stale:
                notify(config, product)
                state[name] = {"status": status, "notified_at": now, "checked_at": now}
                save_state(state)
                continue

        state[name] = {"status": status, "notified_at": prev.get("notified_at", 0),
                       "checked_at": now}
        save_state(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-c", "--config", default=str(Path(__file__).with_name("config.json")))
    parser.add_argument("--once", action="store_true", help="run one check and exit (for cron)")
    args = parser.parse_args()

    try:
        config = json.loads(Path(args.config).read_text())
    except FileNotFoundError:
        sys.exit(f"Config not found: {args.config}\n"
                 f"Copy config.example.json to config.json and edit it.")

    state = load_state()

    if args.once:
        run_checks(config, state)
        return

    interval = config.get("check_interval_minutes", 10) * 60
    log(f"Watching {len(config['products'])} product(s), every {interval // 60} min. Ctrl+C to stop.")
    while True:
        run_checks(config, state)
        # Jitter so requests don't land at machine-perfect intervals.
        time.sleep(interval + random.uniform(0, interval * 0.1))


if __name__ == "__main__":
    main()
