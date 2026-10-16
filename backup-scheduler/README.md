# Harmony Commons live menu — independent backup scheduler

GitHub's own `schedule` can be delayed or dropped, even with correct cron settings. The public GitHub Pages display and Playwright scraper remain in the original repository.

## What this free backup does

A **Cloudflare Worker Cron Trigger** runs at :02, :12, :22, :32, :42, :52 UTC, offset five minutes from the native GitHub Actions schedule at :07, :17, :27, :37, :47, :57. It checks for a recent successfully started or ongoing run. If a recent run is missing, it calls GitHub's `workflow_dispatch` API using an encrypted secret.

No Chromium is run in Cloudflare; Playwright continues to run on GitHub Actions. There is **no change to the site's URL**.

Cloudflare Workers Free includes Cron Triggers, subject to its current free limits. With 144 triggers a day, this small HTTP-only Worker fits the published free tier, assuming normal usage. GitHub Actions on public repositories is free using standard GitHub-hosted runners.

## One-time setup — user must complete this in their own accounts

1. Create/sign in to a **Cloudflare** account at <https://dash.cloudflare.com/>; choose **Workers Free**, not Paid.
2. In GitHub, visit <https://github.com/settings/personal-access-tokens/new>. Create a **fine-grained token** named e.g. `Harmony menu scheduler`. Repository access: **Only select repositories → gopi-aws-1/utsc-menu**. Repository permissions: **Actions → Read and write** (needed to dispatch workflows); keep all unnecessary permissions at None / default. Choose a sensible expiry and plan to rotate it. **Never paste the token into ChatGPT, into GitHub source code, or into a public URL.**
3. On your computer, open a terminal in the `backup-scheduler` folder and run `npm install`, then `npx wrangler login` and `npx wrangler deploy`. The Worker and its Cron Trigger are deployed to Cloudflare. You can instead create the Worker in the Cloudflare dashboard and paste the JavaScript source, then add the scheduled trigger there.
4. Under Cloudflare **Workers & Pages → harmony-commons-menu-backup → Settings → Variables and Secrets**, add a **Secret** (not plain variable) called `GITHUB_ACTIONS_TOKEN` with the fine-grained token from step 2. Save/deploy. Alternatively from the terminal run `npx wrangler secret put GITHUB_ACTIONS_TOKEN` and enter the value privately.
5. In Cloudflare Worker **Triggers**, verify the cron is `2,12,22,32,42,52 * * * *`. After the first 10–20 minutes, inspect Worker logs and GitHub [Actions history](https://github.com/gopi-aws-1/utsc-menu/actions) for a `workflow_dispatch` run when the native schedule misses.

**Keep this token secret.** If leaked, revoke it in GitHub immediately. An expiring token must be replaced in Cloudflare when it expires.

## Behavior and limitations

- If a successful GitHub sync began within the last eight minutes, the backup does nothing.
- If no recent successful sync exists (or the latest sync failed), it triggers GitHub Actions. GitHub's concurrency group avoids simultaneous publishing.
- The backup Worker cannot guarantee that MyDiningHub serves valid data, that GitHub runner capacity is available, or that publishing will never fail; it removes the **single scheduling dependency** and normally offers roughly a 10–15-minute target.
- The GitHub dashboard's **Run workflow** button remains a manual fallback.
- For a sustained service-level guarantee, you need an official MyDiningHub API/webhook or a dedicated managed always-on updater.

## Tests

From this folder: `npm test` (uses Node.js 20+).

## References

- <https://developers.cloudflare.com/workers/configuration/cron-triggers/>
- <https://developers.cloudflare.com/workers/configuration/secrets/>
- <https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event>
