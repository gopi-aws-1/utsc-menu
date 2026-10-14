#!/usr/bin/env python3
"""
UTSC Harmony Commons Dining Hall — Real-Time Menu Proxy & Auto-Updater
======================================================================
Supports TWO deployment modes with the exact same script:

Mode A — Local Real-Time Proxy Server (runs on a laptop, desktop, or Raspberry Pi):
  python3 utsc_menu_server.py
  -> Starts a local HTTP server on port 8080 and automatically scrapes UTSC MyDiningHub
     every 15 minutes in the background.

Mode B — GitHub Actions Serverless Auto-Updater (100% hands-off in the cloud):
  python3 utsc_menu_server.py --once
  -> Scrapes the live UTSC Harmony Commons menu once, writes `menu_data.json` and
     `live_menu_snapshot.png`, and exits so GitHub Pages can publish the update.
"""

import argparse
import datetime
import http.server
import json
import os
import pathlib
import socket
import socketserver
import threading
import time
from zoneinfo import ZoneInfo

TARGET_URL = "https://torontosc.mydininghub.ca/en/location/harmony-commons-dining-hall"
PORT = int(os.environ.get("PORT", 8080))
REFRESH_INTERVAL_SECONDS = 900  # Refresh every 15 minutes in local server mode

BASE_DIR = pathlib.Path(__file__).resolve().parent
JSON_PATH = BASE_DIR / "menu_data.json"
SNAPSHOT_PATH = BASE_DIR / "live_menu_snapshot.png"
TORONTO_TZ = ZoneInfo("America/Toronto")

ACCENT_PALETTE = [
    "#3b82f6", "#f59e0b", "#ef4444", "#10b981", "#8b5cf6",
    "#ec4899", "#06b6d4", "#22c55e", "#eab308", "#14b8a6", "#f97316"
]


def get_active_meal_period(now_toronto: datetime.datetime) -> str:
    """Determines the active or upcoming meal period based on Toronto local time."""
    decimal_hour = now_toronto.hour + (now_toronto.minute / 60.0)
    if decimal_hour < 10.75:
        return "Breakfast"
    elif decimal_hour < 15.75:
        return "Lunch"
    else:
        return "Dinner"


def scrape_live_utsc_menu() -> bool:
    """Fetches the rendered menu and a 1920x1080 screenshot from UTSC MyDiningHub using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[!] Playwright is not installed. Run: pip install playwright && playwright install chromium")
        return False

    now_toronto = datetime.datetime.now(TORONTO_TZ)
    target_period = get_active_meal_period(now_toronto)
    print(f"[{now_toronto.strftime('%Y-%m-%d %H:%M:%S %Z')}] Scraping {TARGET_URL} (Target period: {target_period})...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                timezone_id="America/Toronto",
                locale="en-CA",
            )
            page = context.new_page()
            page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)

            # Give the client-side React/Elevate DXP menu widget time to finish rendering past "Loading..."
            page.wait_for_timeout(6000)

            # Save a full-HD screenshot for the zero-JS /snapshot route
            page.screenshot(path=str(SNAPSHOT_PATH), full_page=True)

            # Extract stations and menu items from the live rendered DOM
            extracted = page.evaluate(
                """() => {
                const stations = [];
                const seenStations = new Set();
                const ignoredTitles = new Set([
                    "harmony commons dining hall", "locations & menus", "my account",
                    "meal plans", "catering", "about us", "contact us"
                ]);

                const cards = Array.from(document.querySelectorAll(
                    'section, article, div[class*="station" i], div[class*="category" i], div[class*="menu" i]'
                ));

                cards.forEach(card => {
                    const titleEl = card.querySelector('h2, h3, h4');
                    if (!titleEl) return;
                    const stationName = titleEl.innerText.trim();
                    if (!stationName || stationName.length > 45) return;
                    if (ignoredTitles.has(stationName.toLowerCase()) || seenStations.has(stationName)) return;

                    const itemEls = Array.from(card.querySelectorAll(
                        'li, [class*="item" i], [class*="recipe" i], [class*="product" i]'
                    ));
                    const items = [];
                    const seenItems = new Set();

                    itemEls.forEach(el => {
                        const text = el.innerText.trim().replace(/\s+/g, ' ');
                        if (!text || text === stationName || seenItems.has(text)) return;
                        seenItems.add(text);

                        const calMatch = text.match(/(\d+\s*Cal)/i);
                        const cal = calMatch ? calMatch[1] : "";
                        const cleanName = cal ? text.replace(calMatch[0], "").trim() : text;

                        if (cleanName && cleanName.length > 1 && cleanName.length < 95) {
                            items.push({ name: cleanName, cal: cal });
                        }
                    });

                    if (items.length > 0) {
                        seenStations.add(stationName);
                        stations.push({ name: stationName, items: items });
                    }
                });
                return stations;
            }"""
            )

            browser.close()

            if extracted and len(extracted) > 0:
                for idx, st in enumerate(extracted):
                    st["accent"] = ACCENT_PALETTE[idx % len(ACCENT_PALETTE)]

                payload = {
                    "dateLabel": now_toronto.strftime("%a, %b %d, %Y • %I:%M %p") + f" ({target_period})",
                    "mealPeriod": target_period,
                    "locationName": "Harmony Commons Dining Hall",
                    "sourceUrl": TARGET_URL,
                    "stations": extracted,
                }
                JSON_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                print(f"[+] Saved {len(extracted)} dining stations to {JSON_PATH.name} and updated {SNAPSHOT_PATH.name}")
            else:
                print(f"[+] Updated {SNAPSHOT_PATH.name} (DOM selector returned 0 stations; keeping previous {JSON_PATH.name})")
            return True

    except Exception as exc:
        print(f"[!] Error scraping live menu: {exc}")
        return False


def background_sync_loop():
    """Periodically refreshes the menu in a background daemon thread."""
    while True:
        scrape_live_utsc_menu()
        time.sleep(REFRESH_INTERVAL_SECONDS)


class SignageRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def end_headers(self):
        # Prevent aggressive caching on LG webOS browser so menu updates appear automatically
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.path = "/utsc_harmony_commons_signage.html"
        elif self.path.startswith("/snapshot"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            snapshot_html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="900">
  <title>UTSC Harmony Commons — Snapshot View</title>
  <style>
    body { margin: 0; background: #0b1528; text-align: center; }
    img { max-width: 100%; height: auto; display: block; margin: 0 auto; }
  </style>
</head>
<body>
  <img src="live_menu_snapshot.png" alt="UTSC Harmony Commons Live Menu">
</body>
</html>"""
            self.wfile.write(snapshot_html.encode("utf-8"))
            return
        return super().do_GET()


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UTSC Harmony Commons Live Menu Proxy & Updater")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Scrape the live menu once, write menu_data.json & live_menu_snapshot.png, and exit (for GitHub Actions / cron).",
    )
    args = parser.parse_args()

    if args.once:
        scrape_live_utsc_menu()
    else:
        sync_thread = threading.Thread(target=background_sync_loop, daemon=True)
        sync_thread.start()

        local_ip = get_local_ip()
        print("=" * 74)
        print(" UTSC Harmony Commons Dining Hall — LG Screen Signage Server Running")
        print("=" * 74)
        print(f" 1. Interactive ES5 Signage Board: http://{local_ip}:{PORT}/")
        print(f" 2. Zero-JS PNG Snapshot View:     http://{local_ip}:{PORT}/snapshot")
        print("=" * 74)

        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("0.0.0.0", PORT), SignageRequestHandler) as httpd:
            httpd.serve_forever()
