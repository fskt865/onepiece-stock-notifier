#!/usr/bin/env python3
"""Desktop app for the stock notifier (packaged into a windowed Windows .exe).

First run: a step-by-step GUI wizard. Its first choice is WHERE watching runs:

- "In the cloud" (recommended): GitHub's servers do the checking around the
  clock, so this computer can be off. The app then acts as a status window
  for the cloud watcher and a shortcut to its web control panel.
- "On this computer": the app runs the checker itself while it's open, with
  a local control panel at http://127.0.0.1:8080.

Either way, push notifications reach the phone via ntfy.
"""

import json
import secrets
import socket
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import requests

import stock_notifier as core

CONFIG_FILE = core.app_dir() / "config.json"
PORT = 8080
PANEL_URL = f"http://127.0.0.1:{PORT}"
SITE_URL = "https://fskt865.github.io/onepiece-stock-notifier/"
RAW_BASE = "https://raw.githubusercontent.com/fskt865/onepiece-stock-notifier/main"

# A --windowed build has no stdout/stderr; keep the watcher's prints in a file.
if sys.stdout is None or sys.stderr is None:
    _logf = open(core.app_dir() / "notifier.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _logf
    sys.stderr = sys.stderr or _logf

import tkinter as tk
from tkinter import messagebox, ttk

FONT_H = ("Segoe UI", 15, "bold")
FONT_S = ("Segoe UI", 11, "bold")
FONT_B = ("Segoe UI", 10)

STATUS_LABELS = {
    "in_stock": "In stock!", "out_of_stock": "Out of stock", "unknown": "Unknown",
    "error": "Fetch failed", "not_checked": "Not checked yet",
    "watching": "Watching for launches",
}


def bundled_default_targets():
    """The curated watch targets shipped inside the executable."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    try:
        return json.loads((base / "config.json").read_text())["products"]
    except (OSError, json.JSONDecodeError, KeyError):
        return []


def ago(ts):
    if not ts:
        return ""
    s = max(0, int(datetime.now().timestamp() - ts))
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    return f"{s // 3600}h ago"


class SetupWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Card Stock Notifier - Setup")
        self.geometry("640x580")
        self.minsize(640, 580)

        self.mode = tk.StringVar(value="cloud")
        self.suggested_topic = f"cards-{secrets.token_hex(4)}"
        self.topic = tk.StringVar(value=self.suggested_topic)
        self.webhook = tk.StringVar()
        self.desktop_popups = tk.BooleanVar(value=True)
        self.use_defaults = tk.BooleanVar(value=True)
        self.interval = tk.StringVar(value="10")

        self.body = ttk.Frame(self, padding=(28, 24))
        self.body.pack(fill="both", expand=True)
        nav = ttk.Frame(self, padding=(28, 0, 28, 20))
        nav.pack(fill="x")
        self.back_btn = ttk.Button(nav, text="< Back", command=self.back)
        self.back_btn.pack(side="left")
        self.next_btn = ttk.Button(nav, text="Next >", command=self.forward)
        self.next_btn.pack(side="right")

        self.idx = 0
        self.rebuild_steps()
        self.render()

    def rebuild_steps(self):
        if self.mode.get() == "cloud":
            self.steps = [self.step_mode, self.step_cloud]
        else:
            self.steps = [self.step_mode, self.step_phone, self.step_extras,
                          self.step_watch, self.step_review]

    # -- layout helpers -----------------------------------------------------
    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def h(self, text):
        ttk.Label(self.body, text=text, font=FONT_H).pack(anchor="w", pady=(0, 10))

    def p(self, text, pady=3):
        ttk.Label(self.body, text=text, font=FONT_B, wraplength=570,
                  justify="left").pack(anchor="w", pady=pady)

    def render(self):
        self.clear()
        self.steps[self.idx]()
        self.back_btn.state(["!disabled"] if self.idx else ["disabled"])
        self.next_btn.config(
            text="Finish" if self.idx == len(self.steps) - 1 else "Next >")

    # -- steps --------------------------------------------------------------
    def step_mode(self):
        self.h("Welcome!")
        self.p("This watches card shops for One Piece and Pokemon restocks and "
               "new launches, and pings your phone the moment something "
               "happens. First choice: where should the watching run?")
        box = ttk.Frame(self.body)
        box.pack(anchor="w", pady=14, fill="x")
        ttk.Radiobutton(
            box, variable=self.mode, value="cloud",
            text="In the cloud  (recommended)").pack(anchor="w")
        self.p("      GitHub's servers check around the clock - your computer "
               "can be off. It's already set up and running.", 1)
        ttk.Radiobutton(
            box, variable=self.mode, value="local",
            text="On this computer").pack(anchor="w", pady=(10, 0))
        self.p("      Checks only run while this app is open. Good as a "
               "second watcher or if you want everything local.", 1)

    def step_cloud(self):
        self.h("You're covered - nothing runs on this PC")
        self.p("The cloud watcher already checks all the stores every "
               "10-20 minutes, day and night, and it keeps doing that with "
               "your computer off.")
        self.p("")
        self.p("To get the pings on your phone:", 2)
        self.p("   1.  Install the free 'ntfy' app (App Store / Google Play).", 1)
        self.p("   2.  In the app, tap  +  and subscribe to the team's topic "
               "name. Ask Noah for it if you don't have it.", 1)
        self.p("")
        self.p("Click Finish to open the control panel website, where you can "
               "see live status and edit what's watched (the PDF guide covers "
               "the one-time editing token). This app will just show a status "
               "window whenever you open it.")

    def step_phone(self):
        self.h("Step 1 - Pings on your phone")
        self.p("The free ntfy app delivers the push notifications:")
        self.p("   1.  Install 'ntfy' from the App Store or Google Play.", 1)
        self.p("   2.  In the app, tap  +  (Subscribe to topic).", 1)
        self.p("   3.  Type the topic name below into the app - then leave it "
               "as is here.", 1)
        row = ttk.Frame(self.body)
        row.pack(anchor="w", pady=12, fill="x")
        ttk.Label(row, text="Topic name:", font=FONT_S).pack(side="left")
        ttk.Entry(row, textvariable=self.topic, width=32,
                  font=FONT_B).pack(side="left", padx=8)
        self.p("A random name was made up for you - topic names are public, so "
               "a guessable one (like 'onepiece') would let strangers see or "
               "fake your alerts.")
        self.p("Leave the box empty to skip phone notifications.")

    def step_extras(self):
        self.h("Step 2 - Other notifications (optional)")
        self.p("Discord: in any server channel, Edit Channel > Integrations > "
               "Webhooks > New Webhook, then paste the URL here:")
        ttk.Entry(self.body, textvariable=self.webhook, width=60,
                  font=FONT_B).pack(anchor="w", pady=(4, 14))
        ttk.Checkbutton(self.body, text="Also show popups on this computer",
                        variable=self.desktop_popups).pack(anchor="w")
        self.p("Popups only appear while the app is running.")

    def step_watch(self):
        self.h("Step 3 - What to watch")
        ttk.Checkbutton(
            self.body,
            text="Start with the curated One Piece & Pokemon watches",
            variable=self.use_defaults).pack(anchor="w", pady=(0, 4))
        n = len(bundled_default_targets())
        self.p(f"That's {n} launch watches: official Bandai product news, "
               "Premium Bandai (US & Singapore), LA Sports Cards "
               "(Burbank/Glendale), Hot Topic, Newegg and Macy's.")
        self.p("You can also watch specific products (any store page plus its "
               "'Sold Out' / 'Add to Cart' wording) - add those in the control "
               "panel afterwards.")
        row = ttk.Frame(self.body)
        row.pack(anchor="w", pady=14)
        ttk.Label(row, text="Check every", font=FONT_B).pack(side="left")
        ttk.Spinbox(row, from_=5, to=120, textvariable=self.interval,
                    width=5).pack(side="left", padx=6)
        ttk.Label(row, text="minutes (5 is the polite minimum)",
                  font=FONT_B).pack(side="left")

    def step_review(self):
        self.h("Step 4 - Test it")
        topic = self.topic.get().strip()
        self.p(f"Phone (ntfy topic):  {topic or 'skipped'}", 2)
        self.p(f"Discord:  {'yes' if self.webhook.get().strip() else 'skipped'}", 2)
        self.p(f"Popups on this PC:  {'yes' if self.desktop_popups.get() else 'no'}", 2)
        n = len(bundled_default_targets()) if self.use_defaults.get() else 0
        self.p(f"Watches to start with:  {n}", 2)
        self.p(f"Check every:  {self.interval.get()} minutes", 2)
        ttk.Button(self.body, text="Send test notification",
                   command=self.send_test).pack(anchor="w", pady=(16, 6))
        self.test_label = ttk.Label(self.body, text="", font=FONT_B,
                                    wraplength=570, justify="left")
        self.test_label.pack(anchor="w")
        self.p("")
        self.p("Click Finish to save and start watching - the control panel "
               "will open in your browser.")

    # -- actions ------------------------------------------------------------
    def build_config(self):
        return {
            "check_interval_minutes": max(5, int(self.interval.get() or 10)),
            "renotify_minutes": 120,
            "paused": False,
            "notifications": {
                "ntfy_topic": self.topic.get().strip(),
                "discord_webhook": self.webhook.get().strip(),
                "desktop": bool(self.desktop_popups.get()),
            },
            "products": bundled_default_targets() if self.use_defaults.get() else [],
        }

    def send_test(self):
        self.test_label.config(text="Sending...")
        config = self.build_config()

        def run():
            # Link somewhere that works from a phone, not localhost.
            sent = core.notify(config, {
                "name": "Test - the stock notifier can reach you",
                "url": SITE_URL,
            })
            msg = (f"Sent via: {', '.join(sent)} - check your phone!" if sent
                   else "Nothing was sent - check the topic/webhook, or go "
                        "Back and fix it.")
            self.after(0, lambda: self.test_label.config(text=msg))
        threading.Thread(target=run, daemon=True).start()

    def validate(self):
        step = self.steps[self.idx]
        if step == self.step_extras:
            hook = self.webhook.get().strip()
            if hook and not hook.startswith("https://"):
                messagebox.showwarning(
                    "Discord webhook",
                    "That doesn't look like a webhook URL (it should start "
                    "with https://). Clear it or paste the full URL.")
                return False
        if step == self.step_watch:
            try:
                if int(self.interval.get()) < 5:
                    raise ValueError
            except (TypeError, ValueError):
                messagebox.showwarning(
                    "Interval", "Enter a number of minutes, 5 or more.")
                return False
        return True

    def forward(self):
        if not self.validate():
            return
        if self.steps[self.idx] == self.step_mode:
            self.rebuild_steps()
        if self.idx == len(self.steps) - 1:
            self.finish()
            return
        self.idx += 1
        self.render()

    def save_config_file(self, config):
        try:
            CONFIG_FILE.write_text(json.dumps(config, indent=2))
            return True
        except OSError as e:
            messagebox.showerror(
                "Can't save here",
                "Settings couldn't be saved next to the app "
                f"({e}).\n\nMove the app into a normal folder you own - "
                "like Documents or Desktop - and run it again.")
            return False

    def finish(self):
        if self.mode.get() == "cloud":
            if self.save_config_file({"mode": "cloud"}):
                self.destroy()
            return
        config = self.build_config()
        if not (config["notifications"]["ntfy_topic"]
                or config["notifications"]["discord_webhook"]
                or config["notifications"]["desktop"]):
            if not messagebox.askyesno(
                    "No notifications",
                    "No notification method is set, so nothing will ping you. "
                    "Save anyway?"):
                return
        if self.save_config_file(config):
            self.destroy()

    def back(self):
        if self.idx:
            self.idx -= 1
            self.render()


class StatusWindow(tk.Tk):
    """Shared frame: a summary line, a target list, and action buttons."""

    def __init__(self, note):
        super().__init__()
        self.title("Card Stock Notifier")
        self.geometry("700x460")

        top = ttk.Frame(self, padding=(14, 12))
        top.pack(fill="x")
        self.summary = ttk.Label(top, text="Loading...", font=FONT_S)
        self.summary.pack(side="left")
        self.buttons = ttk.Frame(top)
        self.buttons.pack(side="right")

        self.tree = ttk.Treeview(self, columns=("status", "checked"),
                                 show="tree headings")
        self.tree.heading("#0", text="Watch target")
        self.tree.heading("status", text="Status")
        self.tree.heading("checked", text="Checked")
        self.tree.column("#0", width=390)
        self.tree.column("status", width=170)
        self.tree.column("checked", width=90)
        self.tree.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        bottom = ttk.Frame(self, padding=(14, 0, 14, 10))
        bottom.pack(fill="x")
        ttk.Label(bottom, text=note, font=FONT_B, wraplength=540,
                  justify="left").pack(side="left")
        ttk.Button(bottom, text="Redo setup",
                   command=self.redo_setup).pack(side="right")

    def redo_setup(self):
        if not messagebox.askyesno(
                "Redo setup", "Erase the saved settings and run the setup "
                "wizard again the next time the app opens?"):
            return
        try:
            CONFIG_FILE.unlink()
        except OSError:
            pass
        messagebox.showinfo("Redo setup",
                            "Done - close and reopen the app to set it up again.")

    def populate(self, rows, summary):
        self.tree.delete(*self.tree.get_children())
        for name, status, checked in rows:
            self.tree.insert("", "end", text=name, values=(status, checked))
        self.summary.config(text=summary)


class CloudWindow(StatusWindow):
    """Read-only view of the GitHub-hosted watcher."""

    def __init__(self, open_panel=False):
        super().__init__(
            "Watching runs in GitHub's cloud - this computer can be off. "
            "This window just shows status; edit targets in the control panel.")
        ttk.Button(self.buttons, text="Open control panel",
                   command=lambda: webbrowser.open(SITE_URL)).pack(side="right")
        if open_panel:
            self.after(1200, lambda: webbrowser.open(SITE_URL))
        self.after(300, self.refresh)

    def refresh(self):
        def fetch():
            try:
                cfg = requests.get(f"{RAW_BASE}/config.json", timeout=15).json()
                st = requests.get(f"{RAW_BASE}/state.json", timeout=15).json()
            except (requests.RequestException, ValueError):
                self.after(0, lambda: self.summary.config(
                    text="Can't reach GitHub right now - retrying soon"))
                return
            rows = []
            for product in cfg.get("products", []):
                entry = st.get(product["name"], {})
                status = STATUS_LABELS.get(entry.get("status", "not_checked"),
                                           entry.get("status", ""))
                count = entry.get("item_count")
                if count:
                    status += f" ({count})"
                rows.append((product["name"], status,
                             ago(entry.get("checked_at"))))
            n = len(rows)
            self.after(0, lambda: self.populate(
                rows, f"{n} cloud watch target{'s' if n != 1 else ''} - "
                      "checks every 10-20 min, phone pings via ntfy"))
        threading.Thread(target=fetch, daemon=True).start()
        self.after(60000, self.refresh)


class LocalWindow(StatusWindow):
    """Front for the locally running watcher + control panel."""

    def __init__(self, webapp, open_panel=False):
        super().__init__(
            "Watching continues while this window is open. Add or edit "
            "targets in the control panel.")
        self.webapp = webapp
        ttk.Button(self.buttons, text="Check all now",
                   command=self.check_now).pack(side="right", padx=(6, 0))
        ttk.Button(self.buttons, text="Open control panel",
                   command=lambda: webbrowser.open(PANEL_URL)).pack(side="right")
        if open_panel:
            self.after(1500, lambda: webbrowser.open(PANEL_URL))
        self.after(1000, self.refresh)

    def check_now(self):
        self.webapp.request_check()
        self.summary.config(text="Checking everything now...")

    def refresh(self):
        try:
            config = self.webapp.load_config()
            state = self.webapp.load_state()
            rows = []
            for product in config["products"]:
                entry = state.get(product["id"], {})
                status = STATUS_LABELS.get(entry.get("status", "not_checked"),
                                           entry.get("status", ""))
                count = entry.get("item_count")
                if count:
                    status += f" ({count})"
                rows.append((product["name"], status,
                             ago(entry.get("last_checked"))))
            n = len(rows)
            self.populate(rows, f"{n} watch target{'s' if n != 1 else ''} - "
                                f"checking every "
                                f"{config.get('check_interval_minutes', 10)} min")
        except Exception as e:
            self.summary.config(text=f"Status unavailable ({e})")
        self.after(5000, self.refresh)


def port_in_use():
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", PORT))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def selftest():
    """Sanity checks that don't need a display - verifies a packaged build."""
    print(f"app dir:          {core.app_dir()}")
    targets = bundled_default_targets()
    print(f"bundled targets:  {len(targets)}")
    assert targets, "bundled config.json missing from the package"
    import app as webapp
    tmpl = Path(webapp.TEMPLATE_DIR) / "index.html"
    print(f"template found:   {tmpl.exists()} ({tmpl})")
    assert tmpl.exists(), "templates/index.html missing from the package"
    with webapp.app.test_client() as client:
        code = client.get("/").status_code
        print(f"GET / renders:    HTTP {code}")
        assert code == 200
        code = client.get("/api/state").status_code
        print(f"GET /api/state:   HTTP {code}")
        assert code == 200
    # HTTPS from inside the package (catches a missing certifi bundle).
    code = requests.get("https://ntfy.sh/", timeout=20).status_code
    print(f"HTTPS works:      HTTP {code}")
    assert code == 200
    print("selftest OK")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return

    first_run = not CONFIG_FILE.exists()
    if first_run:
        wizard = SetupWizard()
        wizard.mainloop()
        if not CONFIG_FILE.exists():  # window closed without finishing
            return

    try:
        config = json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        config = {}

    if config.get("mode") == "cloud":
        CloudWindow(open_panel=first_run).mainloop()
        return

    if port_in_use():
        root = tk.Tk()
        root.withdraw()
        webbrowser.open(PANEL_URL)
        messagebox.showinfo(
            "Card Stock Notifier",
            "It looks like the notifier is already running - opening its "
            "control panel instead.")
        return

    import app as webapp  # imported late so it picks up the wizard's config

    threading.Thread(target=webapp.watcher_loop, daemon=True).start()
    threading.Thread(
        target=lambda: webapp.app.run(host="127.0.0.1", port=PORT),
        daemon=True).start()

    LocalWindow(webapp, open_panel=first_run).mainloop()


if __name__ == "__main__":
    main()
