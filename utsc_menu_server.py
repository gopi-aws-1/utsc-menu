#!/usr/bin/env python3
"""Harmony Commons menu synchronizer and digital-signage web server.

No demonstration dishes are served. A meal is published only when the source
page's date and selected meal period can be verified. Failure is visible through
sync_status.json and /api/health; old data is never relabeled as a new meal.

Local: python utsc_menu_server.py
One-shot (GitHub Actions): python utsc_menu_server.py --once
Diagnostics: python utsc_menu_server.py --once --debug
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, time as clocktime
import http.server
import json
import logging
import os
from pathlib import Path
import re
import socketserver
import threading
import time
from zoneinfo import ZoneInfo

TARGET_URL = os.getenv(
    "MENU_SOURCE_URL", "https://torontosc.mydininghub.ca/en/location/harmony-commons-dining-hall"
)
TORONTO = ZoneInfo("America/Toronto")
BASE_DIR = Path(__file__).resolve().parent
JSON_PATH = BASE_DIR / "menu_data.json"
STATUS_PATH = BASE_DIR / "sync_status.json"
SNAPSHOT_PATH = BASE_DIR / "live_menu_snapshot.png"
DEBUG_PATH = BASE_DIR / "menu_debug.html"
PORT = int(os.getenv("PORT", "8080"))
REFRESH_SECONDS = max(60, int(os.getenv("REFRESH_SECONDS", "120")))

# Published Harmony Commons meal window: https://www.utsc.utoronto.ca/food/harmony-commons-dining-hall
# Staff can adjust without touching the code if opening/meal schedules change.
MEAL_WINDOWS = (
    ("Breakfast", os.getenv("BREAKFAST_START", "08:00"), os.getenv("LUNCH_START", "11:00")),
    ("Lunch", os.getenv("LUNCH_START", "11:00"), os.getenv("DINNER_START", "16:30")),
    ("Dinner", os.getenv("DINNER_START", "16:30"), os.getenv("DINNER_END", "20:00")),
)
COLORS = ("#3b82f6", "#f59e0b", "#ef4444", "#10b981", "#8b5cf6", "#ec4899", "#06b6d4")
log = logging.getLogger("utsc-menu")
_update_lock = threading.Lock()


def now_toronto() -> datetime:
    return datetime.now(TORONTO)


def meal_period(now: datetime) -> str:
    local = now.astimezone(TORONTO).time()
    for name, start, end in MEAL_WINDOWS:
        if clocktime.fromisoformat(start) <= local < clocktime.fromisoformat(end):
            return name
    return "Closed"


def next_boundary(now: datetime) -> datetime:
    today = now.astimezone(TORONTO).date()
    values = {x for _, start, end in MEAL_WINDOWS for x in (start, end)}
    future = []
    for days in (0, 1):
        for value in values:
            dt = datetime.combine(today + timedelta(days=days), clocktime.fromisoformat(value), TORONTO)
            if dt > now:
                future.append(dt)
    return min(future)


def write_json_atomic(path: Path, data: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def read_json(path: Path) -> dict | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except (ValueError, OSError):
        return None


def public_status() -> dict:
    current = now_toronto()
    period = meal_period(current)
    data = read_json(JSON_PATH)
    status = read_json(STATUS_PATH) or {}
    valid = bool(data and data.get("stations") and data.get("mealPeriod") == period
                 and data.get("menuDate") == current.date().isoformat()
                 and data.get("verifiedSource") is True)
    age = None
    if valid:
        try:
            then = datetime.fromisoformat(data["fetchedAt"])
            age = int((current - then).total_seconds())
            valid = 0 <= age <= 900  # The display never silently serves a >15 min meal.
        except (KeyError, ValueError, TypeError):
            valid = False
    return {
        "status": "live" if valid else ("closed" if period == "Closed" else "unavailable"),
        "mealPeriod": period,
        "menuDate": current.date().isoformat(),
        "checkedAt": current.isoformat(),
        "lastSuccessfulFetch": (data or {}).get("fetchedAt"),
        "ageSeconds": age,
        "lastAttempt": status.get("lastAttempt"),
        "lastError": status.get("lastError"),
    }


def mark_attempt(success: bool, error: str = "", fetched_at: str | None = None) -> None:
    now = now_toronto().isoformat()
    last = read_json(STATUS_PATH) or {}
    write_json_atomic(STATUS_PATH, {
        "lastAttempt": now,
        "lastSuccessfulFetch": fetched_at if success else last.get("lastSuccessfulFetch"),
        "lastError": "" if success else error[:400],
        "success": success,
    })


# Source-page inspection is purposely specific about evidence. Clicking a tab and
# parsing an unrelated paragraph must NEVER produce a purportedly live menu.
MEAL_CONTROLS = "button, [role=tab], [role=button], select, a[href], input[type=radio], label"
EXTRACT_JS = r"""() => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const blacklist = /^(menu|nutrition|ingredients|allergens|all|locations|find food|view menu|filter|search|today)$/i;
  const candidates = Array.from(document.querySelectorAll(
    '[data-testid*="station" i], [class*="station" i], [class*="menu-category" i], ' +
    '[class*="menu-group" i], [class*="menugroup" i], [class*="category" i], [class*="menu" i], section, article'
  ));
  const output = [], seen = new Set();
  for (const card of candidates) {
    if (!visible(card)) continue;
    const heading = card.querySelector('h2,h3,h4,[class*="station-name" i],[class*="category-title" i]');
    if (!heading) continue;
    const name = clean(heading.innerText);
    if (!name || name.length > 55 || blacklist.test(name) || /^(breakfast|lunch|dinner)$/i.test(name)) continue;
    const elems = Array.from(card.querySelectorAll(
      '[class*="recipe" i], [class*="menu-item" i], [class*="food-item" i], ' +
      '[class*="product-name" i], li'
    )).filter(visible);
    const items = [], seenItems = new Set();
    for (const el of elems) {
      // Prefer the smallest item element; skip wrappers with multiple nested items.
      if (elems.some(child => child !== el && el.contains(child))) continue;
      let raw = clean(el.innerText);
      if (!raw || raw === name || raw.length > 220 || /^(show more|details|add to favorites)$/i.test(raw)) continue;
      const calories = raw.match(/\b\d{1,4}\s*(?:cal|kcal|calories)\b/i);
      const calorie = calories ? calories[0] : '';
      raw = clean(raw.replace(/\b\d{1,4}\s*(?:cal|kcal|calories)\b/ig, '').replace(/view (?:nutrition|details)/ig, ''));
      if (raw.length < 2 || raw.length > 100 || seenItems.has(raw.toLowerCase())) continue;
      seenItems.add(raw.toLowerCase());
      items.push({name:raw, cal:calorie});
    }
    if (!items.length) continue;
    const key = name.toLowerCase();
    if (!seen.has(key)) {seen.add(key); output.push({name,items});}
  }
  return output;
}"""


def assert_today_in_source(frame, today: datetime, today_clicked: bool = False) -> None:
    """Require corroboration of today's date from source calendar/date controls."""
    if today_clicked:
        return
    iso = today.date().isoformat()
    # React calendar widgets sometimes expose the selected date in a control.
    dates = frame.locator('input[type="date"]')
    if dates.count():
        for i in range(min(4, dates.count())):
            date_el = dates.nth(i)
            if date_el.is_visible():
                if date_el.input_value() != iso:
                    date_el.fill(iso)
                    date_el.dispatch_event("change")
                    frame.wait_for_timeout(900)
                if date_el.input_value() == iso:
                    return
    page_data = frame.evaluate("""() => {
      const inputs = [...document.querySelectorAll('[aria-selected="true"], [aria-current="date"], [data-selected="true"], [class*="selected" i]')];
      return inputs.filter(e => e.getClientRects().length).slice(0,80).map(e => ({text:(e.innerText||'').trim(),datetime:e.getAttribute('datetime'),date:e.getAttribute('data-date'),label:e.getAttribute('aria-label')}));
    }""")
    markers = (iso, today.strftime("%B %-d"), today.strftime("%b %-d"),
               today.strftime("%a, %b %-d"), today.strftime("%m/%d/%Y"))
    for obj in page_data:
        value = " ".join(str(x or "") for x in obj.values())
        if any(marker.lower() in value.lower() for marker in markers):
            return
    raise RuntimeError("Source did not confirm today's selected menu date (refusing to publish)")


def choose_today(frame) -> bool:
    """If present, explicitly move a date-picker menu widget to today."""
    matcher = re.compile(r"^\s*today\s*$", re.I)
    for selector in ("button", "[role=button]", "a"):
        options = frame.locator(selector).filter(has_text=matcher)
        for i in range(min(options.count(), 10)):
            button = options.nth(i)
            try:
                if button.is_visible() and button.is_enabled():
                    button.click(timeout=3000)
                    frame.wait_for_timeout(650)
                    return True
            except Exception:
                pass
    return False


def choose_meal(frame, period: str) -> bool:
    """Confirm selection via active state or a changed menu, not merely a click."""
    matcher = re.compile(r"^\s*" + re.escape(period) + r"\s*$", re.I)

    def signature():
        try:
            return json.dumps(frame.evaluate(EXTRACT_JS), sort_keys=True)
        except Exception:
            return ""

    def control_selected(control):
        try:
            state = (control.get_attribute("aria-selected") or "").lower()
            pressed = (control.get_attribute("aria-pressed") or "").lower()
            data = (control.get_attribute("data-state") or "").lower()
            klass = (control.get_attribute("class") or "").lower()
            return (state == "true" or pressed == "true" or data in ("active", "selected", "checked")
                    or bool(re.search(r"(?:^|[\s_-])(selected|active|current)(?:$|[\s_-])", klass)))
        except Exception:
            return False

    for selector in ('[role="tab"]', 'button', '[role="button"]', 'label', 'a'):
        candidates = frame.locator(selector).filter(has_text=matcher)
        try:
            for i in range(min(candidates.count(), 12)):
                item = candidates.nth(i)
                if not item.is_visible() or not item.is_enabled():
                    continue
                before, before_url = signature(), frame.url
                item.click(timeout=3000)
                for _ in range(6):
                    frame.wait_for_timeout(700)
                    if control_selected(item) or frame.url != before_url or (before and signature() != before):
                        return True
        except Exception:
            continue
    sels = frame.locator("select")
    for i in range(min(sels.count(), 5)):
        sel = sels.nth(i)
        try:
            values = sel.locator("option").evaluate_all("els => els.map(e => ({value:e.value,text:e.textContent.trim()}))")
            match = next((o for o in values if matcher.match(o["text"])), None)
            if match:
                sel.select_option(value=match["value"])
                frame.wait_for_timeout(700)
                if sel.input_value() == match["value"]:
                    return True
        except Exception:
            continue
    return False


def pull_from_playwright(debug: bool = False) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright missing. Install dependencies in requirements.txt") from exc

    started = now_toronto()
    period = meal_period(started)
    if period == "Closed":
        return {"closed": True}
    with sync_playwright() as p:
        options = {"headless": True}
        # Works with 'playwright install chromium' and with Linux system Chromium.
        executable = os.getenv("CHROMIUM_PATH")
        if executable:
            options["executable_path"] = executable
        browser = p.chromium.launch(**options)
        try:
            context = browser.new_context(
                viewport={"width": 1600, "height": 1000},
                timezone_id="America/Toronto", locale="en-CA",
                service_workers="block",
            )
            page = context.new_page()
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            frames = [page.main_frame] + [f for f in page.frames if f != page.main_frame]
            errors = []
            for frame in frames:
                try:
                    today_clicked = choose_today(frame)
                    assert_today_in_source(frame, started, today_clicked)
                    if not choose_meal(frame, period):
                        errors.append("No verifiable active '" + period + "' selector in a frame")
                        continue
                    stations = frame.evaluate(EXTRACT_JS)
                    total = sum(len(s["items"]) for s in stations)
                    if not stations or total < 2:
                        errors.append(f"Menu '{period}' selector found, but no reliable food items ({total})")
                        continue
                    # Don't publish data if the meal changed during a long scrape.
                    completed = now_toronto()
                    if completed.date() != started.date() or meal_period(completed) != period:
                        raise RuntimeError("Meal changed during fetch; retry next cycle")
                    for n, station in enumerate(stations):
                        station["accent"] = COLORS[n % len(COLORS)]
                    page.screenshot(path=str(SNAPSHOT_PATH), full_page=True)
                    return {
                        "schemaVersion": 2,
                        "dateLabel": completed.strftime("%a, %b %d, %Y"),
                        "menuDate": completed.date().isoformat(),
                        "mealPeriod": period,
                        "fetchedAt": completed.isoformat(),
                        "verifiedSource": True,
                        "locationName": "Harmony Commons Dining Hall",
                        "sourceUrl": TARGET_URL,
                        "stations": stations,
                    }
                except Exception as exc:
                    errors.append(f"Frame {frame.url[:130]}: {str(exc)[:180]}")
            if debug:
                DEBUG_PATH.write_text(page.content(), encoding="utf-8")
                diagnostics = []
                for n, frame in enumerate(frames):
                    try:
                        (BASE_DIR / f"menu_debug_frame_{n}.html").write_text(frame.content(), encoding="utf-8")
                        diagnostics.append({"frame":n,"url":frame.url,
                            "controls":frame.locator("button,[role=tab],select,input[type=date]").all_inner_texts()[:120]})
                    except Exception as exc:
                        diagnostics.append({"frame":n,"error":str(exc)})
                write_json_atomic(BASE_DIR / "menu_debug_diagnostics.json", {"frames": diagnostics, "errors": errors})
                try:
                    page.screenshot(path=str(BASE_DIR / "menu_debug.png"), full_page=True)
                except Exception:
                    pass
            raise RuntimeError("; ".join(errors[:5]) or "No rendered menu located")
        finally:
            browser.close()


def sync_once(debug: bool = False) -> bool:
    if not _update_lock.acquire(blocking=False):
        return False
    try:
        if meal_period(now_toronto()) == "Closed":
            mark_attempt(True)
            log.info("Outside meal windows; display will show Closed")
            return True
        try:
            payload = pull_from_playwright(debug)
            if payload.get("closed"):
                return True
            write_json_atomic(JSON_PATH, payload)
            mark_attempt(True, fetched_at=payload["fetchedAt"])
            log.info("Published %s: %s stations, %s dishes", payload["mealPeriod"],
                     len(payload["stations"]), sum(len(s["items"]) for s in payload["stations"]))
            return True
        except Exception as exc:
            message = str(exc)
            log.error("Fetch unsuccessful: %s", message)
            mark_attempt(False, error=message)
            return False
    finally:
        _update_lock.release()


def refresh_forever(debug: bool = False) -> None:
    """Resync on interval and immediately after each meal boundary."""
    previous_period = None
    last_attempt = 0.0
    while True:
        current = now_toronto()
        period = meal_period(current)
        if period != previous_period or time.monotonic() - last_attempt >= REFRESH_SECONDS:
            previous_period = period
            last_attempt = time.monotonic()
            sync_once(debug=debug)
        # Wake close to boundaries even if the regular refresh is relatively slow.
        remaining = (next_boundary(current) - current).total_seconds()
        time.sleep(max(0.4, min(15, remaining + 0.2)))


class MenuHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def send_json(self, obj, code=200):
        output = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(output)))
        self.end_headers()
        self.wfile.write(output)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/api/health", "/api/status"):
            return self.send_json(public_status())
        if path == "/api/menu":
            status = public_status()
            data = read_json(JSON_PATH)
            if status["status"] != "live":
                return self.send_json({"status": status, "stations": []}, 503)
            return self.send_json({**data, "status": status})
        if path == "/":
            self.path = "/index.html"
        elif path == "/snapshot":
            # Snapshot must be viewed as an audit image, not a guaranteed current menu.
            self.send_response(302)
            self.send_header("Location", "/live_menu_snapshot.png")
            self.end_headers()
            return
        elif path not in ("/index.html", "/menu_data.json", "/sync_status.json", "/live_menu_snapshot.png"):
            self.send_error(404, "Unknown path")
            return
        return super().do_GET()


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    parser = argparse.ArgumentParser(description="UTSC live menu synchronizer")
    parser.add_argument("--once", action="store_true", help="Fetch once for GitHub Pages workflow")
    parser.add_argument("--debug", action="store_true", help="Save debug HTML/screenshot if source structure is unrecognized")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.once:
        return 0 if sync_once(debug=args.debug) else 1
    thread = threading.Thread(target=refresh_forever, kwargs={"debug": args.debug}, daemon=True)
    thread.start()
    log.info("Signage on http://0.0.0.0:%s/; status on /api/health", PORT)
    with ThreadingServer(("0.0.0.0", PORT), MenuHandler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())