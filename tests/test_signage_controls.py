"""Browser regression tests for LG-compatible menu controls (no external network)."""
import contextlib
import datetime
import functools
import http.server
import json
import pathlib
import shutil
import tempfile
import threading
import time
import unittest

from playwright.sync_api import sync_playwright

REPO = pathlib.Path(__file__).resolve().parents[1]

class SignageControlsTest(unittest.TestCase):
    def test_navigation_refresh_admin_and_after_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            shutil.copy(REPO / "index.html", base / "index.html")
            def fixture(name):
                now = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=23)
                return {
                    "schemaVersion": 2,
                    "dateLabel": "Tomorrow (source verified)",
                    "menuDate": "2099-01-01",
                    "mealPeriod": "Breakfast",
                    "fetchedAt": now.isoformat(),
                    "fetchedAtEpochMs": int(now.timestamp() * 1000),
                    "verifiedSource": True,
                    "stations": [{"name": "Station %d" % i, "items": [{"name": name, "cal": "100 Cal",
                        "ingredients": "source ingredient", "dietary": ["Vegetarian"]}], "accent": "#3b82f6"}
                        for i in range(1, 9)],
                }
            (base / "menu_data.json").write_text(json.dumps(fixture("Dinner-to-breakfast menu")), encoding="utf8")
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmp)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(timezone_id="America/Toronto")
                    context.route("https://github.com/**", lambda route: route.fulfill(status=200, body="Workflow page"))
                    page = context.new_page()
                    page.goto("http://127.0.0.1:%d/" % server.server_port)
                    page.locator(".station-card").first.wait_for(timeout=12000)
                    self.assertEqual(page.locator(".station-card").count(), 8)
                    self.assertIn("Last updated:", page.locator("#sync-status").inner_text())
                    self.assertEqual(page.locator("#sync-status .sync-light.active").count(), 1)
                    self.assertNotIn("Update delayed", page.locator("#sync-status").inner_text())
                    page.locator("#btn-page-1").click()
                    self.assertEqual(page.locator(".station-card").count(), 6)
                    page.locator("#btn-page-2").click()
                    self.assertEqual(page.locator(".station-card").count(), 2)
                    page.locator("#btn-page-all").click()
                    self.assertEqual(page.locator(".station-card").count(), 8)
                    # Speed up only the 15-second page-flip interval in Chromium.
                    page.evaluate("""() => {
                      var actualInterval = window.setInterval;
                      window.setInterval = function(fn, delay) {
                        return actualInterval(fn, delay === 15000 ? 300 : delay);
                      };
                    }""")
                    page.locator("#btn-rotate").click()
                    self.assertIn("ON", page.locator("#btn-rotate").inner_text())
                    page.wait_for_function("document.querySelectorAll('.station-card').length === 2", timeout=6000)
                    page.locator("#btn-rotate").click()
                    self.assertIn("OFF", page.locator("#btn-rotate").inner_text())
                    self.assertEqual(page.locator(".station-card").count(), 8)
                    (base / "menu_data.json").write_text(json.dumps(fixture("Newly published dish")), encoding="utf8")
                    page.locator("#btn-refresh").click()
                    page.get_by_text("Newly published dish").first.wait_for(timeout=12000)
                    self.assertFalse(page.locator("#btn-refresh").is_disabled())
                    self.assertEqual(page.locator("#sync-status .sync-light.active").count(), 1)
                    with page.expect_popup() as popup_info:
                        page.locator("#btn-admin-sync").click()
                    popup = popup_info.value
                    self.assertIn("github.com/gopi-aws-1/utsc-menu/actions", popup.url)
                    popup.close()
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()

if __name__ == "__main__":
    unittest.main()
