// Independent, no-cost backup scheduler for the Harmony Commons menu.
// Deploy as a Cloudflare Worker with a Cron Trigger and one encrypted secret.
// NO credential is stored in this repository or exposed to public users.
// This schedules GitHub Actions; it cannot run Python/Playwright itself.

const REPO = "gopi-aws-1/utsc-menu";
const WORKFLOW = "update-menu.yml";
const BRANCH = "Movie-date";
const CHECK_URL =
  "https://api.github.com/repos/" + REPO + "/actions/workflows/" +
  WORKFLOW + "/runs?per_page=12";
const DISPATCH_URL =
  "https://api.github.com/repos/" + REPO + "/actions/workflows/" +
  WORKFLOW + "/dispatches";
const RECENT_RUN_MS = 8 * 60 * 1000;

function headers(token) {
  const h = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "HarmonyCommonsMenuWatchdog/1.0"
  };
  if (token) h.Authorization = "Bearer " + token;
  return h;
}

export async function checkAndDispatch(env, http = fetch, currentTime = Date.now()) {
  if (!env || !env.GITHUB_ACTIONS_TOKEN) {
    throw new Error("GITHUB_ACTIONS_TOKEN is not configured as a Worker secret");
  }
  let recent = false;
  let inspectionProblem = "";
  try {
    const res = await http(CHECK_URL, {headers: headers()});
    if (!res.ok) throw new Error("GitHub run listing returned HTTP " + res.status);
    const payload = await res.json();
    if (!Array.isArray(payload.workflow_runs)) throw new Error("Malformed workflow list");
    recent = payload.workflow_runs.some((run) => {
      if (run.head_branch !== BRANCH) return false;
      const when = Date.parse(run.created_at || "");
      if (!Number.isFinite(when) || when > currentTime + 60000) return false;
      if (currentTime - when >= RECENT_RUN_MS) return false;
      return run.status !== "completed" || run.conclusion === "success";
    });
  } catch (error) {
    // A failure to inspect runs should not silently stop the watchdog.
    inspectionProblem = String(error);
  }
  if (recent) {
    console.log("Harmony Commons: recent successful or ongoing sync; no dispatch needed");
    return {result:"recent", recent:true};
  }
  const res = await http(DISPATCH_URL, {
    method: "POST",
    headers: {...headers(env.GITHUB_ACTIONS_TOKEN), "Content-Type": "application/json"},
    body: JSON.stringify({ref:BRANCH})
  });
  if (res.status !== 204) {
    const detail = (await res.text()).slice(0, 300);
    throw new Error("GitHub dispatch failed with HTTP " + res.status + ": " + detail);
  }
  console.log("Harmony Commons: dispatched missing sync", inspectionProblem ? "(run listing unavailable)" : "");
  return {result:"dispatched", recent:false};
}

export default {
  // Nobody can trigger or read credentials through the public HTTP endpoint.
  async fetch() {
    return new Response("Harmony Commons scheduler configured. Runs via cron only.", {
      status: 200, headers: {"Content-Type":"text/plain; charset=utf-8"}
    });
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(checkAndDispatch(env));
  }
};
