const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");
const test = require("node:test");

function load(storage = new Map()) {
  const context = {
    window: {},
    crypto: webcrypto,
    localStorage: {
      getItem: (key) => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
    },
    setInterval: () => 0,
    Date,
    URLSearchParams,
  };
  vm.runInNewContext(fs.readFileSync("firebase-demo/demo-engine.js", "utf8"), context);
  return context.window.QueueMasterDemo.request;
}

test("submit, complete, inspect and persist a job locally", async () => {
  const storage = new Map();
  const request = load(storage);
  const submitted = await request("/jobs", {
    method: "POST",
    body: JSON.stringify({ task_type: "fibonacci", payload: { n: 25 }, max_retries: 2 }),
  });
  await new Promise((resolve) => setTimeout(resolve, 1300));
  const job = await request(`/jobs/${submitted.job_id}`);
  assert.equal(job.status, "completed");
  assert.equal(job.result.value, "75025");
  assert.equal((await request("/stats")).completed, 1);
  assert.equal((await load(storage)(`/jobs/${submitted.job_id}`)).status, "completed");
});

test("cancel scheduled jobs and reject tasks outside the demo limits", async () => {
  const request = load();
  const created = await request("/jobs", {
    method: "POST",
    body: JSON.stringify({
      task_type: "long_running", payload: { seconds: 3 }, max_retries: 2,
      scheduled_at: new Date(Date.now() + 60000).toISOString(),
    }),
  });
  assert.equal((await request(`/jobs/${created.job_id}`)).status, "pending");
  assert.equal((await request(`/jobs/${created.job_id}/cancel`, { method: "POST" })).status, "cancelled");
  await assert.rejects(
    request("/jobs", {
      method: "POST",
      body: JSON.stringify({ task_type: "long_running", payload: { seconds: 300 }, max_retries: 2 }),
    }),
    /browser demo accepts/,
  );
});
