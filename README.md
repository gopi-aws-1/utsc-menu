# Harmony Commons — verified live menu signage

This replaces the old October 14 hardcoded menu display. The board only renders meals verified for **today's selected meal period** and fetched for the current meal. It marks updates older than 15 minutes as delayed, displays them with an explicit warning for up to 120 minutes within the same meal, and hides them thereafter. When the university source is unavailable or the selector cannot be verified, the board will **say the live menu is unavailable** instead of showing lunch during dinner.

## What is in the package

- `index.html` — LG webOS-compatible signage display. Fetches immediately and every 60 seconds, validates the date/meal/freshness and clears data at meal boundaries.
- `utsc_menu_server.py` — Playwright scraper and HTTP server. Opens the university page, explicitly selects today's date and the active meal, extracts station dishes, and produces `menu_data.json` (and `sync_status.json`), but only after verification.
- `requirements.txt` — Python dependency.
- `.github/workflows/update-menu.yml` — GitHub Actions cloud updater scheduled every 5 minutes (actual starts may be delayed by GitHub).
- `tests/` — Offline unit and browser tests using simulated menu HTML. These **do not** prove the production website has been successfully parsed.

## Verified live source extraction and important limitations

On October 15, the real MyDiningHub Dinner source was successfully extracted and published by GitHub Actions (81 raw recipe/variant rows across 11 stations). A non-publishing QA inspection of October 16 Breakfast retrieved the live source and validated ingredients and dietary highlights. The scraper expands source 'View more' sections and merges printed menu items with source-visible recipe details. Where published, calorie values, serving options, and short ingredient summaries are preserved; they are never fabricated. Variant servings such as 110 gram/118 gram retain their respective calorie values.

**Safety:** MyDiningHub's short ingredient text is not necessarily a full ingredients or allergen declaration. A missing dietary badge does not mean an item is safe for an allergy. Staff must verify dietary and allergen needs.

**Reliability:** GitHub Pages cannot run Python; GitHub Actions polls MyDiningHub on a *best-effort* five-minute schedule. GitHub's scheduling can be delayed or missed, so source changes cannot be guaranteed to appear instantaneously. For continuous operations, deploy the Python scraper on an always-on computer/server with dependable scheduling or obtain an official upstream feed/webhook. The frontend shows a visible delayed status (up to 120 minutes within the same meal) rather than mislabeling stale data as fresh.

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

GitHub Actions schedules are **best effort**, may start late, and may be disabled after prolonged inactivity on public repositories. This version shows verified freshness or an explicit delayed status instead of claiming zero downtime. For tighter real-time SLAs, use the always-on Python server or an equivalent managed worker instead of scheduled Actions.

## Client-demo checklist

1. Shortly before the demo, during a meal period, open [GitHub Actions](https://github.com/gopi-aws-1/utsc-menu/actions) and run **Sync Harmony Commons menu** via **Run workflow**.
2. Wait for the sync job and GitHub Pages deployment to finish. Verify `menu_data.json` contains **today's Toronto date**, the **correct meal period**, a recent `fetchedAt`, and the expected stations/dishes.
3. Confirm visible ingredients, dietary highlights and, when available, serving-specific calorie values against the live MyDiningHub recipe cards. Do not assume short ingredient summaries represent full allergen lists.
4. Open the LG kiosk URL, reload once, then leave it for a minute to verify automatic browser polling. A red/orange badge means delayed or unavailable, not confirmed real-time.
5. If an update is unavailable, use the official MyDiningHub source directly as a **clearly labeled fallback** instead of presenting historical data as live.

A separate **non-publishing QA inspection** on code pushes verifies the next day's Breakfast data but never changes public `menu_data.json`.

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