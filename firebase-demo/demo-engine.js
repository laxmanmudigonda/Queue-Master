/* Browser simulation for Firebase Hosting. The Python queue engine lives in app/. */
(() => {
  const storageKey = "queuemaster-firebase-demo-v1";
  const iso = () => new Date().toISOString();
  const read = () => {
    try {
      const data = JSON.parse(localStorage.getItem(storageKey) || "[]");
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  };
  let jobs = read();
  const save = () => localStorage.setItem(storageKey, JSON.stringify(jobs.slice(0, 50)));
  const failure = (message) => { throw new Error(message); };
  const event = (job, eventType) => job.events.push({ event_type: eventType, timestamp: iso() });

  function validate(type, payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) failure("Enter a JSON object for the payload.");
    if (type === "fibonacci" && Number.isInteger(payload.n) && payload.n >= 0 && payload.n <= 1000) return;
    if (type === "long_running" && typeof payload.seconds === "number" && payload.seconds >= 0 && payload.seconds <= 10) return;
    if (type === "document_processing" && typeof payload.text === "string" && payload.text.length <= 5000) return;
    if (type === "generate_report" && Array.isArray(payload.rows) && payload.rows.length <= 25 && payload.rows.every((row) => row && typeof row === "object" && !Array.isArray(row))) return;
    if (type === "simulated_failure" && Number.isInteger(payload.failures) && payload.failures >= 0 && payload.failures <= 2) return;
    failure("This browser demo accepts Fibonacci (n ≤ 1000), timed tasks (≤ 10 s), text analysis, CSV reports (≤ 25 rows), or retry simulations (≤ 2 failures).");
  }

  function result(job) {
    const p = job.payload;
    if (job.task_type === "fibonacci") {
      let a = 0n, b = 1n;
      for (let n = 0; n < p.n; n++) [a, b] = [b, a + b];
      return { value: a.toString(), n: p.n };
    }
    if (job.task_type === "long_running") return { slept_seconds: p.seconds };
    if (job.task_type === "document_processing") return {
      word_count: p.text.trim() ? p.text.trim().split(/\s+/).length : 0,
      character_count: p.text.length,
      line_count: p.text ? p.text.split(/\r\n|\n|\r/).length : 0,
      filename: p.filename || "document.txt",
    };
    if (job.task_type === "generate_report") {
      const fields = [...new Set(p.rows.flatMap((row) => Object.keys(row)))].sort();
      const cell = (value) => {
        let text = String(value ?? "");
        if (/^\s*[=+\-@]/.test(text)) text = "'" + text;
        return '"' + text.replaceAll('"', '""') + '"';
      };
      return { csv: [fields.map(cell).join(","), ...p.rows.map((row) => fields.map((key) => cell(row[key])).join(","))].join("\r\n") + "\r\n", rows: p.rows.length };
    }
    return { attempt: job.attempt_count };
  }

  function tick() {
    const current = Date.now();
    let running = jobs.filter((job) => job.status === "running").length;
    let changed = false;
    for (const job of jobs) {
      if (job.status === "running" && current >= job.finish_at) {
        const attempt = job.attempts.at(-1);
        attempt.duration = (current - Date.parse(attempt.started_at)) / 1000;
        attempt.completed_at = iso();
        if (job.task_type === "simulated_failure" && job.attempt_count <= job.payload.failures) {
          attempt.status = "failed";
          attempt.error_message = "Configured demonstration failure";
          job.error_message = attempt.error_message;
          if (job.attempt_count <= job.max_retries) {
            job.status = "retrying";
            job.scheduled_at = new Date(current + 1200).toISOString();
            event(job, "retrying");
          } else {
            job.status = "failed";
            job.completed_at = iso();
            event(job, "failed");
          }
        } else {
          attempt.status = "completed";
          job.status = "completed";
          job.result = result(job);
          job.error_message = null;
          job.completed_at = iso();
          event(job, "completed");
        }
        job.updated_at = iso();
        running--;
        changed = true;
      }
    }
    for (const job of [...jobs].reverse()) {
      if (running >= 2) break;
      if (!["pending", "retrying"].includes(job.status) || Date.parse(job.scheduled_at) > current) continue;
      job.status = "running";
      job.attempt_count++;
      job.started_at = iso();
      job.updated_at = iso();
      job.finish_at = current + Math.max(700, (job.task_type === "long_running" ? job.payload.seconds : 1.2) * 1000);
      job.attempts.push({ attempt_number: job.attempt_count, status: "running", started_at: iso(), duration: null, error_message: null });
      event(job, "claimed");
      running++;
      changed = true;
    }
    if (changed) save();
  }

  function publicJob(job) {
    const { attempts, events, finish_at, ...fields } = job;
    return fields;
  }

  window.QueueMasterDemo = {
    async request(path, options = {}) {
      tick();
      const method = options.method || "GET";
      const [route, query] = path.split("?");
      if (route === "/stats" && method === "GET") {
        const counts = Object.fromEntries(["pending", "running", "retrying", "completed", "failed", "cancelled"].map((status) => [status, jobs.filter((j) => j.status === status).length]));
        return { total_submitted: jobs.length, ...counts, active_workers: 2, retried_jobs: jobs.filter((j) => j.attempt_count > 1).length, average_execution_seconds: null, queue_depth: counts.pending + counts.retrying };
      }
      if (route === "/workers" && method === "GET") return [1, 2].map((n) => ({ id: `demo-worker-${n}`, hostname: `browser-worker-${n}`, status: jobs.some((j) => j.status === "running") ? "running" : "idle", active: true, last_heartbeat: iso() }));
      if (route === "/jobs" && method === "GET") {
        const args = new URLSearchParams(query || "");
        const filtered = jobs.filter((j) => !args.get("status") || j.status === args.get("status"));
        return { total: filtered.length, items: filtered.slice(Number(args.get("offset") || 0), Number(args.get("offset") || 0) + Number(args.get("limit") || 10)).map(publicJob) };
      }
      if (route === "/jobs" && method === "POST") {
        if (jobs.length >= 50) failure("This browser has reached its 50-job demo limit. Clear this site's storage to start over.");
        const input = JSON.parse(options.body || "{}");
        validate(input.task_type, input.payload);
        if (!Number.isInteger(input.max_retries) || input.max_retries < 0 || input.max_retries > 2) failure("Choose 0–2 retries for the demo.");
        if (input.scheduled_at && !Number.isFinite(Date.parse(input.scheduled_at))) failure("Invalid scheduled date.");
        const job = {
          id: crypto.randomUUID(), task_type: input.task_type, payload: input.payload,
          status: "pending", priority: { high: 0, normal: 1, low: 2 }[input.priority] ?? 1,
          result: null, error_message: null, max_retries: input.max_retries, attempt_count: 0,
          scheduled_at: input.scheduled_at || iso(), created_at: iso(), updated_at: iso(),
          started_at: null, completed_at: null, worker_id: null, attempts: [], events: [],
        };
        event(job, "submitted"); jobs.unshift(job); save(); tick();
        return { job_id: job.id, status: job.status, message: "Submitted to browser simulation" };
      }
      const match = route.match(/^\/jobs\/([^/]+)(?:\/(attempts|events|result|cancel|retry))?$/);
      if (match) {
        const job = jobs.find((entry) => entry.id === match[1]);
        if (!job) failure("Job not found in this browser.");
        if (match[2] === "attempts") return job.attempts;
        if (match[2] === "events") return job.events;
        if (match[2] === "result") return { job_id: job.id, result: job.result };
        if (match[2] === "cancel" && method === "POST" && ["pending", "retrying"].includes(job.status)) {
          job.status = "cancelled"; job.completed_at = iso(); event(job, "cancelled"); save(); return publicJob(job);
        }
        if (match[2] === "retry" && method === "POST" && job.status === "failed") {
          job.status = "pending"; job.scheduled_at = iso(); job.error_message = null;
          job.attempt_count = 0; job.attempts = []; event(job, "retried"); save(); tick(); return publicJob(job);
        }
        if (!match[2] && method === "GET") return publicJob(job);
      }
      failure("This action is unavailable in the browser demo.");
    },
  };
  setInterval(tick, 350);
})();
