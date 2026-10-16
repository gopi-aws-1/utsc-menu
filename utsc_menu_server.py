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

# Displayed meal windows for Harmony Commons (confirm when operational hours change).
# Staff can override times through environment variables when dining hours change.
MEAL_WINDOWS = (
    ("Breakfast", os.getenv("BREAKFAST_START", "08:00"), os.getenv("BREAKFAST_END", "11:00")),
    ("Lunch", os.getenv("LUNCH_START", "11:00"), os.getenv("LUNCH_END", "16:30")),
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
  const result = [];
  const normalize = s => clean(s).toLowerCase();
  const push = (name, items) => {
    name = clean(name);
    if (!name || !items.length || result.some(x => normalize(x.name) === normalize(name))) return;
    result.push({name, items});
  };
  const parseRecipe = node => {
    const h = node.querySelector('h4');
    if (!h) return null;
    const name = clean(h.textContent);
    if (!name || name.length > 110) return null;
    const calorieText = clean(node.textContent);
    const match = calorieText.match(/(?:^|[^0-9])(\d{1,4})\s*(?:Calories|Cal|kcal)\b/i);
    return {name, cal: match ? match[1] + ' Cal' : ''};
  };
  const printed = document.querySelector('.print-menu-container .print-menu table');
  if (printed) {
    let name = '', items = [];
    for (const tr of printed.querySelectorAll('tbody > tr')) {
      const heading = tr.querySelector('td[data-focus-heading]');
      if (heading) { push(name, items); name=clean(heading.textContent); items=[]; }
      else if (name) for (const recipe of tr.querySelectorAll('[role="group"][aria-label="Recipe"]')) {
        const item=parseRecipe(recipe);
        if (item && !items.some(x=>normalize(x.name)===normalize(item.name))) items.push(item);
      }
    }
    push(name,items);
  }
  // Source's printable list has all dishes. Its visible cards contain optional
  // published ingredient *summaries* and dietary/marketing highlight labels.
  // Never infer absent ingredients or certifications.
  for (const section of document.querySelectorAll('section[data-scroll-section]')) {
    const h = section.querySelector('h3[data-focus-heading]');
    if (!h) continue;
    const stationName=clean(h.textContent);
    let station=result.find(x=>normalize(x.name)===normalize(stationName));
    if(!station){ station={name:stationName,items:[]}; result.push(station); }
    for (const card of section.querySelectorAll('li.row-span-2')) {
      const node=card.querySelector('[role="group"][aria-label="Recipe"]');
      if(!node)continue;
      const fromCard=parseRecipe(node);
      if(!fromCard)continue;
      let item=station.items.find(x=>normalize(x.name)===normalize(fromCard.name));
      if(!item){item=fromCard;station.items.push(item);} else if(!item.cal && fromCard.cal)item.cal=fromCard.cal;
      const ingredients = node.querySelector('p.mt-2xs.text-sm.text-type-secondary');
      if(ingredients){const summary=clean(ingredients.textContent);if(summary && summary.length<=550)item.ingredients=summary;}
      const labels=[];
      for (const li of card.querySelectorAll('div.border-t ul > li')) {
        const span=li.querySelector('span');
        if(!span)continue;
        const label=clean(span.textContent);
        if(label && label.length<=45 && !labels.includes(label))labels.push(label);
      }
      if(labels.length)item.dietary=labels;
      const servingButtons=[];
      for(const button of node.querySelectorAll('button[aria-pressed]')){
        const label=clean(button.textContent);
        if(/^(\d+(?:\.\d+)?)\s*(gram|grams|g|oz|ml|each)$/i.test(label)){
          servingButtons.push(label);
          if(button.getAttribute('aria-pressed')==='true')item.serving=label;
        }
      }
      if(servingButtons.length)item.servingOptions=servingButtons;
    }
  }
  return result.filter(x=>x.items.length);
}"""

def assert_today_in_source(frame, today: datetime, today_clicked: bool = False) -> None:
    """Verify the *selected* visible calendar heading, not today's hours card.

    Source evidence from the real Oct 14 MyDiningHub page:
    date heading: h2 "Wed, Oct 14" (inside aria-live="polite")
    print menu: "Daily Menu Dinner - Wed 10/14" (not rendered visibly)
    """
    iso = today.date().isoformat()
    exact_heading = f"{today.strftime('%a, %b')} {today.day}"
    headings = frame.locator('h2[class*="text-heading-4"]')
    for i in range(headings.count()):
        heading = headings.nth(i)
        if not heading.is_visible():
            continue
        if heading.inner_text().strip() == exact_heading:
            return
    # Alternative accessible calendar widgets with an actual selected date.
    dates = frame.locator('input[type="date"]')
    for i in range(min(4, dates.count())):
        date_el = dates.nth(i)
        if date_el.is_visible() and date_el.input_value() == iso:
            return
    raise RuntimeError(
        f"MyDiningHub selected date does not match {iso}; expected header '{exact_heading}'"
    )


def choose_today(frame) -> bool:
    """Site defaults to today. Validation uses the selected visible date heading."""
    return False


def source_meal_selected(frame, period: str) -> bool:
    """Check the website's meal dropdown AND the matching rendered menu title."""
    controls = frame.locator('button[data-testid="selectButton"]')
    matching_control = False
    for i in range(min(8, controls.count())):
        control = controls.nth(i)
        if not control.is_visible():
            continue
        label = re.sub(r"\s+", " ", control.inner_text()).strip()
        if re.fullmatch(r"Meal:\s*" + re.escape(period), label, flags=re.I):
            matching_control = True
            break
    if not matching_control:
        return False
    title = frame.locator('.print-menu-container h1')
    if not title.count():
        return False
    title_text = re.sub(r"\s+", " ", title.first.inner_text()).strip()
    return bool(re.match(r"Daily Menu\s+" + re.escape(period) + r"\s*-", title_text, re.I))


def choose_meal(frame, period: str) -> bool:
    """Use the site's actual custom listbox, rather than unrelated hours links."""
    if source_meal_selected(frame, period):
        return True
    controls = frame.locator('button[data-testid="selectButton"]')
    for i in range(min(8, controls.count())):
        control = controls.nth(i)
        if not control.is_visible() or 'Meal:' not in control.inner_text():
            continue
        control.click(timeout=5000)
        # DXP uses a custom accessible listbox opened by the 'Meal:' button.
        options = frame.get_by_role('option', name=re.compile(r"^\s*" + re.escape(period) + r"\s*$", re.I))
        if options.count():
            options.first.click(timeout=5000)
        else:
            # Support alternative implementations that expose the option as text.
            menu = frame.locator('[role="listbox"]')
            if not menu.count():
                return False
            match = menu.get_by_text(period, exact=True)
            if not match.count():
                return False
            match.first.click(timeout=5000)
        for _ in range(15):
            frame.wait_for_timeout(500)
            if source_meal_selected(frame, period):
                return True
        return False
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
                        errors.append("MyDiningHub did not verify the selected '" + period + "' menu")
                        continue
                    # The meal picker may asynchronously replace the date/recipes.
                    assert_today_in_source(frame, started)
                    # Make all available recipe cards visible so ingredient
                    # summaries and source dietary highlights can be captured.
                    # The print table still supplies the complete dish inventory.
                    for _ in range(40):
                        more = frame.locator('button[aria-label^="View more"]')
                        if not more.count():
                            break
                        try:
                            more.first.click(timeout=2500)
                            frame.wait_for_timeout(180)
                        except Exception as exc:
                            log.warning("Unable to expand additional menu cards: %s", exc)
                            break
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
                        "fetchedAtEpochMs": int(completed.timestamp() * 1000),
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