import test from "node:test";
import assert from "node:assert/strict";
import {checkAndDispatch} from "./src/index.js";

const now = Date.parse("2026-10-16T12:22:00Z");
const token = {GITHUB_ACTIONS_TOKEN:"unit-test-only-not-a-real-secret"};
const results = (runs, dispatchStatus=204) => {
  const calls = [];
  const http = async (url, options) => {
    calls.push({url, method:options.method || "GET", options});
    if ((options.method || "GET") === "POST")
      return {status:dispatchStatus, text:async()=>""};
    return {ok:true, status:200, json:async()=>({workflow_runs:runs})};
  };
  return {calls, http};
};
const run = (minute, status="completed", conclusion="success") => ({
  head_branch:"Movie-date", status, conclusion,
  created_at:new Date(now-minute*60000).toISOString()
});
test("skips when GitHub has run successfully recently", async()=>{
  const {calls,http}=results([run(5)]);
  assert.equal((await checkAndDispatch(token,http,now)).result,"recent");
  assert.equal(calls.length,1);
});
test("dispatches when GitHub misses the expected run",async()=>{
  const {calls,http}=results([run(17)]);
  assert.equal((await checkAndDispatch(token,http,now)).result,"dispatched");
  assert.equal(calls[1].method,"POST");
  assert.equal(JSON.parse(calls[1].options.body).ref,"Movie-date");
  assert.ok(calls[1].options.headers.Authorization.startsWith("Bearer "));
});
test("queues a recovery after a recent failed sync",async()=>{
  const {calls,http}=results([run(2,"completed","failure")]);
  assert.equal((await checkAndDispatch(token,http,now)).result,"dispatched");
  assert.equal(calls.length,2);
});
test("does not dispatch when an existing run is ongoing",async()=>{
  const {calls,http}=results([run(2,"in_progress",null)]);
  assert.equal((await checkAndDispatch(token,http,now)).result,"recent");
  assert.equal(calls.length,1);
});
test("public endpoint cannot dispatch or expose token",async()=>{
  const {default:app}=await import("./src/index.js");
  const response=await app.fetch();
  assert.equal(response.status,200);
  assert.ok(!(await response.text()).includes("unit-test-only"));
});
test("refuses to run without a secret",async()=>{
  await assert.rejects(checkAndDispatch({},()=>{},now),/secret/);
});
