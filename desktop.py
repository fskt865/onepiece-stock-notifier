#!/usr/bin/env python3
"""Desktop launcher for the stock notifier (packaged into a Windows .exe).

First run: an interactive setup wizard asks for everything that's needed.
Every run: starts the background watcher and opens the control panel in the
default browser (http://127.0.0.1:8080). Keep the window open to keep
watching; close it to stop.
"""

import json
import secrets
import sys
import threading
import time
import webbrowser
from pathlib import Path

import stock_notifier as core

CONFIG_FILE = core.app_dir() / "config.json"
PORT = 8080


def bundled_default_targets():
    """The curated watch targets shipped inside the executable."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    try:
        return json.loads((base / "config.json").read_text())["products"]
    except (OSError, json.JSONDecodeError, KeyError):
        return []


def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"  {prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def ask_yn(prompt, default=True):
    answer = ask(prompt + (" (Y/n)" if default else " (y/N)"))
    if not answer:
        return default
    return answer.lower().startswith("y")


def wizard():
    print("""
==========================================================
  Card Stock Notifier - first-time setup
==========================================================

This app watches card shops for restocks and new product
launches, and pings your phone when something happens.
A few questions and you're done - you can change all of
this later in the control panel it opens.
""")

    print("STEP 1 - Phone notifications (ntfy, free)")
    print("  1. Install the 'ntfy' app from the App Store / Google Play.")
    print("  2. In the app tap '+ Subscribe to topic'.")
    suggested = f"cards-{secrets.token_hex(4)}"
    print(f"  3. Enter this topic name (made up for you): {suggested}")
    print("     (topics are public, so a random name keeps strangers out)")
    topic = ask("Type the topic you subscribed to, or 'skip'", suggested)
    if topic.lower() == "skip":
        topic = ""

    print("\nSTEP 2 - Discord (optional)")
    print("  In any server channel: Edit Channel > Integrations > Webhooks.")
    webhook = ask("Paste a webhook URL, or press Enter to skip")
    if webhook and not webhook.startswith("https://"):
        print("  That doesn't look like a URL - skipping Discord.")
        webhook = ""

    print("\nSTEP 3 - Desktop popups")
    desktop = ask_yn("Also show a popup on this computer when something hits?",
                     default=True)

    print("\nSTEP 4 - What to watch")
    defaults = bundled_default_targets()
    products = []
    if defaults and ask_yn(
            f"Start with the {len(defaults)} curated One Piece / Pokemon "
            f"watches (official Bandai launches, Premium Bandai US+SG, "
            f"LA Sports Cards, Hot Topic, Newegg, Macy's)?", default=True):
        products = defaults
    print("  You can add specific products (any store page + its 'Sold Out' /")
    print("  'Add to Cart' wording) in the control panel that opens next.")

    print("\nSTEP 5 - How often to check")
    while True:
        try:
            interval = int(ask("Minutes between checks", "10"))
            if interval >= 5:
                break
            print("  5 minutes is the polite minimum - stores may block faster polling.")
        except ValueError:
            print("  Enter a number.")

    config = {
        "check_interval_minutes": interval,
        "renotify_minutes": 120,
        "paused": False,
        "notifications": {"ntfy_topic": topic, "discord_webhook": webhook,
                          "desktop": desktop},
        "products": products,
    }
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    print(f"\nSaved settings to {CONFIG_FILE}")

    if topic or webhook or desktop:
        print("Sending a test notification...")
        sent = core.notify(config, {
            "name": "Setup complete - the stock notifier can reach you",
            "url": f"http://127.0.0.1:{PORT}",
        })
        if sent:
            print(f"Test sent via: {', '.join(sent)}. Check your phone!")
        else:
            print("Test failed - you can fix notification settings in the control panel.")
    else:
        print("WARNING: no notification channel set - you won't be pinged.")
        print("Set one in the control panel (Notifications section).")


def main():
    first_run = not CONFIG_FILE.exists()
    if first_run:
        wizard()

    import app as webapp  # imported late so it picks up the wizard's config

    threading.Thread(target=webapp.watcher_loop, daemon=True).start()

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    threading.Thread(target=open_browser, daemon=True).start()

    print(f"""
==========================================================
  Watching. Control panel: http://127.0.0.1:{PORT}
  (opening in your browser now)

  Keep this window open - closing it stops the watcher.
==========================================================
""")
    try:
        webapp.app.run(host="127.0.0.1", port=PORT)
    except OSError as e:
        print(f"\nCouldn't start on port {PORT} ({e}).")
        print("Is another copy already running? Close it and try again.")
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
