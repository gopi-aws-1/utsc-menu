## Scheduling reliability (October 16, 2026)

**GitHub-native schedules are best-effort and have previously missed multiple expected 10-minute runs.** The updater now runs independently from time-consuming display QA tests, retries MyDiningHub extraction up to three times, and republishes only verified data/status. The native cron still targets every 10 minutes.

**Independent free backup is prepared but NOT ACTIVE until deployed to your Cloudflare account.** Full setup is at [backup-scheduler/README.md](backup-scheduler/README.md). The Cloudflare Worker checks GitHub Actions every 10 minutes, offset from the native schedule, and requests a fresh workflow run only when a recent successful/active run is missing. A narrowly scoped GitHub token must be stored as a private Cloudflare Worker Secret, never in the public repository.

The independent scheduler is not a zero-downtime guarantee: GitHub runners, MyDiningHub, and Pages deployment can still fail or run late. Always check the source retrieval timestamp during important demonstrations.
# Harmony Commons — verified live menu signage

This replaces the old hardcoded menu. During operating hours, the updater selects the active meal; outside operating hours, it extracts whichever date and meal MyDiningHub is currently displaying (including tomorrow's menu). The board keeps a previously verified menu visible for up to 36 hours and prominently marks updates older than 15 minutes as delayed. It never represents historical food as freshly fetched.

## What is in the package

- `index.html` — Legacy LG webOS-compatible signage. Checks `menu_data.json` every minute, shows the MyDiningHub menu even outside service hours, and includes functional pagination, rotation, Refresh Menu, and an admin sync shortcut.
- `utsc_menu_server.py` — Playwright scraper, local HTTP server, station and nutrition extraction; follows the source's selected meal/date after hours.
- `requirements.txt` — Python dependency.
- `.github/workflows/update-menu.yml` — GitHub Actions updater targeted every 10 minutes at minutes 07, 17, 27, 37, 47, 57 (Toronto and UTC hours shift together; GitHub cron uses UTC). Runs are best-effort and can be delayed.
- `tests/` — Offline unit and browser tests using simulated menu HTML. These **do not** prove the production website has been successfully parsed.

## Verified live source extraction and important limitations

On October 15, the real MyDiningHub Dinner source was successfully extracted and published by GitHub Actions (81 raw recipe/variant rows across 11 stations). A non-publishing QA inspection of October 16 Breakfast retrieved the live source and validated ingredients and dietary highlights. The scraper expands source 'View more' sections and merges printed menu items with source-visible recipe details. Where published, calorie values, serving options, and short ingredient summaries are preserved; they are never fabricated. Variant servings such as 110 gram/118 gram retain their respective calorie values.

**Safety:** MyDiningHub's short ingredient text is not necessarily a full ingredients or allergen declaration. A missing dietary badge does not mean an item is safe for an allergy. Staff must verify dietary and allergen needs.

**Reliability:** GitHub Pages cannot run Python; GitHub Actions attempts to poll MyDiningHub on a *best-effort* 10-minute schedule. GitHub's scheduling can be delayed or missed, so source changes cannot be guaranteed to appear instantaneously. For continuous operations, deploy the Python scraper on an always-on computer/server with dependable scheduling or obtain an official upstream feed/webhook. The frontend clearly labels delayed menus (retained for up to 36 hours) rather than mislabeling them as fresh. A meal shown outside operating hours is the source-selected offering, not necessarily currently served.

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

## Free GitHub Pages refresh controls

- **Refresh Menu** (public LG button) fetches the latest `menu_data.json` already published in GitHub Pages, bypassing the browser cache. It **cannot** run Playwright or force a MyDiningHub scrape from a public browser.
- **Run Source Sync (Admin)** opens your GitHub Actions workflow page. An authorized GitHub user must select **Run workflow**, choose the `Movie-date` branch, and confirm. Wait until the workflow and Pages deployment succeed, then press **Refresh Menu** (or wait up to 60 seconds for automatic rechecking).
- Never put a GitHub token in public HTML or JavaScript.
- **All Stations**, **Page 1**, **Page 2**, and **Auto-Flip** work locally. Page 2 and Auto-Flip are unavailable when the source has six or fewer stations.

### Set the schedule to 10 or 15 minutes

The workflow resides at `.github/workflows/update-menu.yml` on the default `Movie-date` branch. Under the `schedule` section, use one of:

```yaml
# 10-minute target (currently configured)
schedule:
  - cron: '7,17,27,37,47,57 * * * *'
```

```yaml
# 15-minute target (alternative)
schedule:
  - cron: '7,22,37,52 * * * *'
```

Commit the workflow change to the default branch. GitHub Actions schedules operate in UTC, can start late, and sometimes drop runs; the stated interval is not a service guarantee.
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
- The browser checks every 60 seconds; posted service hours are informational only and never hide a verified source-selected menu.
- Meals are never permanently baked into `index.html`. Old meals in `menu_data.json` cannot pass the frontend's current-day/current-period/age checks.
- To run tests locally: `python -m pip install pytest`, `python -m pytest -q tests`. Chromium is needed for Playwright browser tests.
- For food safety, the menu and calorie details are informational and must still be confirmed by dining staff before being treated as allergen advice.
## Update timestamp and activity light

The sign shows **Last updated: [Toronto time] ET** from the verified source retrieval timestamp, alongside a subtle pulsing green dot when the browser successfully reads the published JSON. This dot indicates the **site's automatic polling is functioning** (the browser checks every minute); it does **not** mean the upstream source has just changed. The source's selected menu/date remain in the footer. The light stops pulsing on fetch failure or when data is unavailable. This replaces the distracting delayed-update banner without making the timestamp misleading.
