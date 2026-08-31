#!/usr/bin/env python3
"""Web GUI for the stock notifier.

Run:
    python app.py            # then open http://localhost:8080

The background watcher polls every product on the configured interval and
notifies on the out-of-stock -> in-stock transition, exactly like the CLI.
Configuration is shared with the CLI (config.json); runtime status lives in
webstate.json.
"""

import json
import threading
import time
import uuid
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request

import stock_notifier as core

BASE = Path(__file__).parent
CONFIG_FILE = BASE / "config.json"
STATE_FILE = BASE / "webstate.json"

DEFAULT_CONFIG = {
    "check_interval_minutes": 10,
    "renotify_minutes": 120,
    "paused": False,
    "notifications": {"ntfy_topic": "", "discord_webhook": "", "desktop": False},
    "products": [],
}

app = Flask(__name__)
lock = threading.RLock()
check_requested = threading.Event()  # manual "check now"
requested_ids = set()                # empty set while flagged = check everything
next_check_at = 0.0


def load_config():
    with lock:
        try:
            config = json.loads(CONFIG_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            config = {}
        changed = not CONFIG_FILE.exists()
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = json.loads(json.dumps(value))
                changed = True
        for product in config["products"]:
            if "id" not in product:
                product["id"] = uuid.uuid4().hex[:8]
                changed = True
        if changed:
            save_config(config)
        return config


def save_config(config):
    with lock:
        CONFIG_FILE.write_text(json.dumps(config, indent=2))


def load_state():
    with lock:
        try:
            return json.loads(STATE_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}


def save_state(state):
    with lock:
        STATE_FILE.write_text(json.dumps(state, indent=2))


def run_check(product, config):
    """Check one product, update state, and notify on the right transitions."""
    if product.get("type") == "new_items":
        # Launch watches run in the GitHub Actions checker; the local app skips them.
        return
    try:
        status = core.check_product(product)
        error = None
    except requests.RequestException as exc:
        status, error = "error", core.sanitize_error(exc, product)

    with lock:
        state = load_state()
        prev = state.get(product["id"], {})
        now = time.time()
        entry = {
            "status": status,
            "error": error,
            "last_checked": now,
            "notified_at": prev.get("notified_at", 0),
        }

        renotify_after = config.get("renotify_minutes", 0) * 60
        if status == "in_stock":
            first_time = prev.get("status") != "in_stock"
            stale = renotify_after and now - entry["notified_at"] > renotify_after
            if first_time or stale:
                core.notify(config, product)
                entry["notified_at"] = now
        elif status == "unknown" and prev.get("status") not in ("unknown", None):
            core.notify(config, product,
                        "warning: couldn't determine stock status - check the page markers")

        state[product["id"]] = entry
        save_state(state)


def watcher_loop():
    global next_check_at
    next_check_at = time.time() + 5  # first sweep shortly after startup
    while True:
        check_requested.wait(timeout=1)
        config = load_config()
        now = time.time()

        if check_requested.is_set():
            with lock:
                ids = set(requested_ids)
                requested_ids.clear()
            check_requested.clear()
            targets = [p for p in config["products"] if not ids or p["id"] in ids]
        elif not config.get("paused") and now >= next_check_at:
            targets = config["products"]
            interval = config.get("check_interval_minutes", 10) * 60
            next_check_at = now + interval
        else:
            continue

        for product in targets:
            run_check(product, config)


def parse_phrases(value):
    if isinstance(value, list):
        return [p.strip() for p in value if p.strip()]
    return [p.strip() for p in str(value).split(",") if p.strip()]


def product_from_request(body, product_id=None):
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    if not name or not url:
        return None, "Name and URL are required."
    if not url.startswith(("http://", "https://")):
        return None, "URL must start with http:// or https://"
    return {
        "id": product_id or uuid.uuid4().hex[:8],
        "name": name,
        "url": url,
        "in_stock_text": parse_phrases(body.get("in_stock_text", [])),
        "out_of_stock_text": parse_phrases(body.get("out_of_stock_text", [])),
    }, None


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    config = load_config()
    state = load_state()
    products = []
    for product in config["products"]:
        entry = state.get(product["id"], {})
        products.append({**product,
                         "status": entry.get("status", "not_checked"),
                         "error": entry.get("error"),
                         "last_checked": entry.get("last_checked"),
                         "notified_at": entry.get("notified_at")})
    return jsonify({
        "products": products,
        "settings": {
            "check_interval_minutes": config["check_interval_minutes"],
            "renotify_minutes": config["renotify_minutes"],
            "paused": config["paused"],
            "notifications": config["notifications"],
        },
        "next_check_at": None if config["paused"] else next_check_at,
        "now": time.time(),
    })


@app.post("/api/products")
def api_add_product():
    product, err = product_from_request(request.get_json(force=True))
    if err:
        return jsonify({"error": err}), 400
    config = load_config()
    config["products"].append(product)
    save_config(config)
    request_check(product["id"])
    return jsonify(product), 201


@app.put("/api/products/<product_id>")
def api_update_product(product_id):
    updated, err = product_from_request(request.get_json(force=True), product_id)
    if err:
        return jsonify({"error": err}), 400
    config = load_config()
    for i, product in enumerate(config["products"]):
        if product["id"] == product_id:
            config["products"][i] = updated
            save_config(config)
            request_check(product_id)
            return jsonify(updated)
    return jsonify({"error": "No such product"}), 404


@app.delete("/api/products/<product_id>")
def api_delete_product(product_id):
    config = load_config()
    before = len(config["products"])
    config["products"] = [p for p in config["products"] if p["id"] != product_id]
    if len(config["products"]) == before:
        return jsonify({"error": "No such product"}), 404
    save_config(config)
    with lock:
        state = load_state()
        state.pop(product_id, None)
        save_state(state)
    return jsonify({"ok": True})


@app.post("/api/settings")
def api_settings():
    body = request.get_json(force=True)
    config = load_config()
    for key in ("check_interval_minutes", "renotify_minutes"):
        if key in body:
            try:
                config[key] = max(1, int(body[key])) if key != "renotify_minutes" \
                    else max(0, int(body[key]))
            except (TypeError, ValueError):
                return jsonify({"error": f"{key} must be a number"}), 400
    if "paused" in body:
        config["paused"] = bool(body["paused"])
    if "notifications" in body:
        n = body["notifications"]
        config["notifications"] = {
            "ntfy_topic": (n.get("ntfy_topic") or "").strip(),
            "discord_webhook": (n.get("discord_webhook") or "").strip(),
            "desktop": bool(n.get("desktop")),
        }
    save_config(config)
    return jsonify({"ok": True})


def request_check(product_id=None):
    with lock:
        if product_id:
            requested_ids.add(product_id)
        else:
            requested_ids.clear()  # empty = all products
    check_requested.set()


@app.post("/api/check")
@app.post("/api/check/<product_id>")
def api_check(product_id=None):
    request_check(product_id)
    return jsonify({"ok": True})


@app.post("/api/test-notification")
def api_test_notification():
    config = load_config()
    sent = core.notify(config, {
        "name": "Test notification - the stock notifier can reach you",
        "url": request.host_url,
    })
    if not sent:
        return jsonify({"error": "No notification channel worked. "
                                 "Set an ntfy topic or Discord webhook and save first."}), 400
    return jsonify({"sent": sent})


if __name__ == "__main__":
    threading.Thread(target=watcher_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=8080)
