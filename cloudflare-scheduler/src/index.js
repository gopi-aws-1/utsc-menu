/**
 * Harmony Commons independent menu-sync scheduler.
 * Runs every 15 minutes on Cloudflare's cron scheduler.
 * GitHub's existing workflow performs the Playwright scrape and publishes menu_data.json.
 * Do not expose the GitHub token in the browser or in this repository.
 */
const DISPATCH_URL =
  "https://api.github.com/repos/gopi-aws-1/utsc-menu/actions/workflows/update-menu.yml/dispatches";

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(dispatch(env));
  },
  async fetch() {
    // Public health endpoint does NOT trigger GitHub actions or reveal secrets.
    return new Response(
      JSON.stringify({ service: "Harmony Commons scheduler", trigger: "Cloudflare cron", intervalMinutes: 15 }),
      { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } }
    );
  },
};

async function dispatch(env) {
  if (!env.GITHUB_TOKEN) {
    throw new Error("Missing GITHUB_TOKEN secret; set it with wrangler secret put GITHUB_TOKEN");
  }
  const response = await fetch(DISPATCH_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "harmony-commons-cloudflare-scheduler",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "Movie-date" }),
  });
  if (response.status !== 204) {
    const body = (await response.text()).slice(0, 500);
    throw new Error(`GitHub dispatch failed (HTTP ${response.status}): ${body}`);
  }
  console.log("Harmony Commons GitHub menu-sync workflow dispatched successfully");
}
