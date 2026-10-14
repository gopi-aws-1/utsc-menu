# Harmony Commons — verified live menu signage

This replaces the old October 14 hardcoded menu display. The board only renders meals verified for **today's selected meal period** and fetched within the previous 15 minutes. When the university source is unavailable or the selector cannot be verified, the board will **say the live menu is unavailable** instead of showing lunch during dinner.

## What is in the package

- `index.html` — LG webOS-compatible signage display. Fetches immediately and every 60 seconds, validates the date/meal/freshness and clears data at meal boundaries.
- `utsc_menu_server.py` — Playwright scraper and HTTP server. Opens the university page, explicitly selects today's date and the active meal, extracts station dishes, and produces `menu_data.json` (and `sync_status.json`), but only after verification.
- `requirements.txt` — Python dependency.
- `.github/workflows/update-menu.yml` — GitHub Actions cloud updater scheduled every 5 minutes (actual starts may be delayed by GitHub).
- `tests/` — Offline unit and browser tests using simulated menu HTML. These **do not** prove the production website has been successfully parsed.

## IMPORTANT: Production source compatibility not yet verified

The exact MyDiningHub page is inaccessible from the development environment, so **this release is not yet confirmed to retrieve the live UTSC menu**. It will not invent success: if the actual site's selectors/layout differ from the extraction strategy, it will display an explicit unavailable warning. To finish validation, run the scraper from a machine or GitHub Actions that can reach the live MyDiningHub site. On a failure use `--debug` and check the output / Actions artifacts; the selectors can then be refined to the real site.

## Local (same Wi-Fi as displays)

1. Install Python 3.10+.
2. In the folder that contains the files, run:

   ```bash
   python -m pip install -r requirements.txt
   python -m playwright install chromium
   python utsc_menu_server.py --debug
   ```

3. Open `http://localhost:8080/` on the machine. To access from another screen on the same network, use the computer's LAN address: `http://<computer-LAN-IP>:8080/`.
4. Open `http://localhost:8080/api/health`. `status` must be `live` during meal service. `unavailable` means *do not trust a previously fetched menu*; check the terminal error and `menu_debug_diagnostics.json` / `menu_debug_frame_*.html` if present.
5. The computer must remain on, running Python, and able to access MyDiningHub. To run on a public network, use a supported secure hosting setup rather than directly exposing the local computer.

To perform one manual source sync:

```bash
python utsc_menu_server.py --once --debug
```

## GitHub Pages (public URL and hands-off scheduled updates)

1. Upload all files, including the hidden `.github/workflows/update-menu.yml` path, to the **root** of your GitHub repository.
2. Under GitHub repository **Settings → Actions → General**, set workflow permissions to **Read and write**. The workflow needs write access to commit `menu_data.json` / `sync_status.json`.
3. Under **Settings → Pages**, select **Deploy from a branch**, the default branch, and the **/ (root)** directory.
4. In the repository's **Actions** tab, open **Sync Harmony Commons menu** and click **Run workflow** (during meal hours).
5. Confirm the run completed successfully, and check the generated `menu_data.json`: `verifiedSource` must equal `true`, `menuDate` must be today's Toronto date, `mealPeriod` must match the current meal, and `fetchedAt` must be recent. Open the GitHub Pages URL after publication.
6. If the workflow failed, download **mydininghub-debug** from the failed Actions run and inspect the extracted controls/frame HTML. This is how to adjust the live-source selectors. Do **not** replace it with fake menu data.

GitHub Actions schedules are **best effort**, may start late, and may be disabled after prolonged inactivity on public repositories. This version is truthful about freshness instead of guaranteeing zero downtime. For tighter real-time SLAs, use the always-on Python server or an equivalent managed worker instead of scheduled Actions.

## Hours / meal periods

The initial schedule is based on the published UTSC Harmony Commons page:

| Toronto local time | Status |
|---|---|
| Before 8:00 AM | Closed |
| 8:00–11:00 AM | Breakfast |
| 11:00 AM–4:30 PM | Lunch |
| 4:30–8:00 PM | Dinner |
| From 8:00 PM | Closed |

The old HTML used different hours. Please confirm the current operating schedule with the dining team. For local Python hosting, override the four time values with `BREAKFAST_START`, `LUNCH_START`, `DINNER_START`, and `DINNER_END` environment variables (HH:MM 24-hour time). **For the static GitHub Pages version, also change `MEAL_TIMES` and the header subtitle in `index.html`** to the same schedule. These must remain consistent.

## Notes

- The `GET /api/menu` and `GET /api/health` endpoints work only in local-server mode; on GitHub Pages the frontend instead reads `menu_data.json` directly.
- The menu is **not** the raw `live_menu_snapshot.png`. The PNG is a source-site audit screenshot, not the designed sign.
- The browser checks every 60 seconds; status updates immediately when the clock crosses a meal boundary, with a periodic clock safety check every 10 seconds.
- Meals are never permanently baked into `index.html`. Old meals in `menu_data.json` cannot pass the frontend's current-day/current-period/age checks.
- To run tests locally: `python -m pip install pytest`, `python -m pytest -q tests`. Chromium is needed for Playwright browser tests.
- For food safety, the menu and calorie details are informational and must still be confirmed by dining staff before being treated as allergen advice.