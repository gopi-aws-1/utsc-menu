# Harmony Commons — independent 15-minute menu scheduler

This Cloudflare Worker runs **every 15 minutes** (UTC minutes 03, 18, 33 and 48) and triggers the existing GitHub Actions workflow that retrieves the latest verified menu from MyDiningHub. The website remains on GitHub Pages.

## One-time setup

1. Sign up for or log in to a Cloudflare account at https://dash.cloudflare.com/ (Workers free plan is sufficient for this small scheduler, subject to Cloudflare limits).
2. Create a **GitHub fine-grained personal access token** at https://github.com/settings/personal-access-tokens/new . Select the account that owns `gopi-aws-1/utsc-menu`, restrict repository access to **only** `utsc-menu`, and set **Actions: Read and write**. Choose a reasonable expiration date and rotate before expiry. Never paste the token into GitHub code or ChatGPT.
3. Install Node.js and run:
   ```bash
   cd cloudflare-scheduler
   npx wrangler login
   npx wrangler secret put GITHUB_TOKEN
   npx wrangler deploy
   ```
   When prompted for the secret, paste the token **in your own terminal**. The token is stored as a Cloudflare Worker secret, not in source control.
4. In Cloudflare Dashboard > Workers & Pages > harmony-commons-menu-scheduler > Settings > Triggers, verify the cron is `3,18,33,48 * * * *`. Cloudflare cron changes may take a few minutes to become active.
5. Check the Cloudflare Worker logs after a scheduled execution and verify the GitHub Actions workflow was triggered with event `workflow_dispatch`: https://github.com/gopi-aws-1/utsc-menu/actions/workflows/update-menu.yml .
6. Verify the site's footer shows a recent source retrieval time and the correct meal period. GitHub Pages deployment and scraping add latency after each trigger.

## Operational notes

- The existing GitHub-native scheduled workflows remain in place as backup. This can cause additional redundant runs; the workflow's concurrency group queues them instead of running in parallel. If GitHub Actions queue time grows, reduce the native cron frequency after verifying Cloudflare works.
- **Cloudflare triggers every 15 minutes**, but does not guarantee menu publication exactly every 15 minutes: GitHub runner availability, MyDiningHub response, extraction, and Pages deployment can delay it.
- GitHub tokens expire; rotate the secret with `npx wrangler secret put GITHUB_TOKEN` before expiration. If token is invalid or missing, Cloudflare logs will show an HTTP error and no GitHub workflow will start.
- The Worker's public HTTP URL is informational only. It cannot trigger a sync, which prevents unauthenticated visitors from spending your GitHub Actions quota.
- To disable this scheduler, remove the Cloudflare cron trigger or delete the Worker.
- Cloudflare's cron times use **UTC**, but a 15-minute interval applies in Toronto throughout the year.
