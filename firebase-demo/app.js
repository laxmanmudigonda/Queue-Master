const $ = (selector) => document.querySelector(selector);
const keyStore = "queuemaster-api-key";
const state = { key: "browser-demo", demo: true, offset: 0, limit: 10, total: 0, jobs: [], busy: false };
const examples = {
  fibonacci: { n: 25 }, long_running: { seconds: 3 },
  document_processing: { text: "QueueMaster processes work asynchronously.\nEvery attempt is recorded.", filename: "sample.txt" },
  generate_report: { rows: [{ name: "Asha", score: 90 }, { name: "Ravi", score: 85 }] },
  simulated_failure: { failures: 2 }, idempotent_counter: { name: "demo" },
};
function notify(message, error = false) {
  const box = $("#notice"); box.textContent = message; box.className = `notice${error ? " error" : ""}`; box.hidden = false;
  clearTimeout(notify.timeout); notify.timeout = setTimeout(() => { box.hidden = true; }, 9000);
}
async function api(path, options = {}) {
  if (window.QueueMasterDemo) return window.QueueMasterDemo.request(path, options);
  if (!state.key) { showAccess(); throw new Error("Connect with your local API key first."); }
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    cache: "no-store",
    headers: { "X-API-Key": state.key, ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
  });
  let data;
  try { data = await response.json(); } catch { throw new Error(`Server returned HTTP ${response.status}.`); }
  if (!response.ok) throw new Error(data.error?.message || data.detail || `HTTP ${response.status}`);
  return data;
}
function time(value) { return value ? new Date(value).toLocaleString() : "—"; }
function shortId(value) { return value ? value.slice(0, 8) : "—"; }
function label(value) { return value.replaceAll("_", " "); }
function el(tag, className, value) { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; }
function statusBadge(value) { return el("span", `badge ${value}`, label(value)); }
function setConnection(online, message) {
  const node = $("#connection"); node.textContent = `${online ? "●" : "○"} ${message}`;
  node.style.color = online ? "#4f9378" : "#c46d57";
}
function showAccess() {
  $("#access-panel").hidden = false;
  $("#access-panel").classList.add("need-key");
  document.body.classList.add("needs-access");
  $("#api-key").focus();
}
function hideAccess() {
  $("#access-panel").hidden = true;
  $("#access-panel").classList.remove("need-key");
  document.body.classList.remove("needs-access");
}
function setView(view) {
  if (!(["overview", "jobs", "workers", "submit"].includes(view))) view = "overview";
  document.body.dataset.view = view;
  $(".crumb strong").textContent = view === "submit" ? "New job" : view[0].toUpperCase() + view.slice(1);
  for (const link of document.querySelectorAll(".nav-link")) {
    const selected = link.getAttribute("href") === `#${view}`;
    link.classList.toggle("active", selected);
    if (selected) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  window.scrollTo({ top: 0, behavior: "instant" });
}
function renderJobs(data) {
  state.jobs = data.items; state.total = data.total;
  $("#job-count").textContent = `(${data.total})`;
  $("#page-label").textContent = data.total ? `Showing ${state.offset + 1}–${state.offset + data.items.length} of ${data.total}` : "No jobs found";
  $("#previous").disabled = state.offset === 0; $("#next").disabled = state.offset + state.limit >= data.total;
  const body = $("#job-rows"); body.replaceChildren();
  if (!data.items.length) { const row = el("tr"); const cell = el("td", "empty", "No jobs match this filter."); cell.colSpan = 5; row.append(cell); body.append(row); return; }
  for (const job of data.items) {
    const row = el("tr"), name = el("td"), task = el("strong", "task-name", label(job.task_type));
    name.append(task, el("span", "mono", shortId(job.id)));
    const status = el("td"); status.append(statusBadge(job.status));
    const open = el("button", "btn quiet", "View details ↗"); open.type = "button"; open.addEventListener("click", () => showJob(job.id));
    const action = el("td"); action.append(open);
    row.append(name, status, el("td", "", String(job.attempt_count)), el("td", "", time(job.created_at)), action);
    body.append(row);
  }
}
function renderWorkers(workers) {
  const list = $("#worker-list"); list.replaceChildren();
  if (!workers.length) { list.append(el("p", "empty", "No workers registered yet.")); return; }
  for (const worker of workers.slice(0, 8)) {
    const row = el("div", "worker"), info = el("div", "worker-info"), detail = el("small", "", `${shortId(worker.id)} · Last seen ${time(worker.last_heartbeat)}`);
    info.append(el("strong", "", worker.hostname), detail);
    row.append(el("span", "worker-avatar", "⌘"), info, statusBadge(worker.active ? worker.status : "stopped")); list.append(row);
  }
}
async function refresh() {
  if (!state.key || state.busy) return;
  state.busy = true;
  try {
    const filter = $("#status-filter").value;
    const [stats, jobs, workers] = await Promise.all([
      api("/stats"), api(`/jobs?limit=${state.limit}&offset=${state.offset}${filter ? `&status=${encodeURIComponent(filter)}` : ""}`), api("/workers"),
    ]);
    $("#total").textContent = stats.total_submitted; $("#completed").textContent = stats.completed;
    $("#in-progress").textContent = stats.running + stats.pending + stats.retrying;
    $("#active-workers").textContent = stats.active_workers;
    renderJobs(jobs); renderWorkers(workers);
    setConnection(true, "System online");
  } catch (error) {
    setConnection(false, "Connection unavailable");
    if (/Invalid API key/i.test(error.message)) {
      state.key = ""; sessionStorage.removeItem(keyStore); showAccess();
      $("#access-error").textContent = "That key was rejected. Copy the value after API_KEY= from your local .env file.";
      $("#access-error").hidden = false;
    } else notify(error.message, true);
  }
  finally { state.busy = false; }
}
function addDetail(container, name, value) { const item = el("div", "detail-item"); item.append(el("small", "", name), el("span", "", String(value ?? "—"))); container.append(item); }
function section(container, heading) { const block = el("div", "detail-section"); block.append(el("h3", "", heading)); container.append(block); return block; }
async function showJob(id) {
  try {
    const [job, attempts, events] = await Promise.all([api(`/jobs/${id}`), api(`/jobs/${id}/attempts`), api(`/jobs/${id}/events`)]);
    $("#detail-title").textContent = label(job.task_type);
    const target = $("#detail-content"); target.replaceChildren();
    const grid = el("div", "detail-grid");
    for (const [name, value] of [["ID",job.id],["Status",label(job.status)],["Attempts",job.attempt_count],["Priority",["high","normal","low"][job.priority] ?? job.priority],["Created",time(job.created_at)],["Scheduled",time(job.scheduled_at)]]) addDetail(grid,name,value);
    target.append(grid);
    for (const [name,value] of [["Payload",job.payload],["Result",job.result]]) {
      if (value !== null && value !== undefined) section(target,name).append(el("pre", "", JSON.stringify(value,null,2)));
    }
    if (job.error_message) section(target,"Latest error").append(el("p", "", job.error_message));
    const history = section(target,`Attempts (${attempts.length})`);
    history.append(...attempts.map((attempt) => el("div", "history-item", `#${attempt.attempt_number} · ${attempt.status} · ${time(attempt.started_at)}${attempt.error_message ? ` · ${attempt.error_message}` : ""}`)));
    const eventBox = section(target,`Events (${events.length})`);
    eventBox.append(...events.map((event) => el("div", "history-item", `${label(event.event_type)} · ${time(event.timestamp)}`)));
    const buttons = el("div", "detail-buttons");
    if (["pending","retrying"].includes(job.status)) buttons.append(actionButton("Cancel job", `/jobs/${id}/cancel`));
    if (job.status === "failed") buttons.append(actionButton("Retry job", `/jobs/${id}/retry`));
    target.append(buttons); $("#detail").showModal();
  } catch (error) { notify(error.message,true); }
}
function actionButton(text, path) {
  const button = el("button", "btn primary", text); button.type = "button";
  button.addEventListener("click", async () => {
    if (!window.confirm(`${text}?`)) return;
    try { await api(path,{ method:"POST" }); $("#detail").close(); notify(`${text} requested.`); await refresh(); }
    catch (error) { notify(error.message,true); }
  }); return button;
}
for (const link of document.querySelectorAll('a[href^="#"]')) link.addEventListener("click", (event) => {
  const view = link.getAttribute("href").slice(1);
  if (!["overview","jobs","workers","submit"].includes(view)) return;
  event.preventDefault(); history.replaceState(null,"",`#${view}`); setView(view);
});
window.addEventListener("hashchange", () => setView(location.hash.slice(1)));
$("#refresh").addEventListener("click",refresh); $("#reload-jobs").addEventListener("click",refresh);
$("#status-filter").addEventListener("change", () => { state.offset = 0; refresh(); });
$("#previous").addEventListener("click", () => { state.offset = Math.max(0,state.offset-state.limit); refresh(); });
$("#next").addEventListener("click", () => { state.offset += state.limit; refresh(); });
$("#task-type").addEventListener("change", () => { $("#payload").value = JSON.stringify(examples[$("#task-type").value],null,2); });
$("#job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.key) { showAccess(); return; }
  try {
    const payload = JSON.parse($("#payload").value);
    const request = { task_type:$("#task-type").value,payload,priority:$("#priority").value,max_retries:Number($("#max-retries").value) };
    const scheduled = $("#scheduled-at").value;
    if (scheduled) { const date = new Date(scheduled); if (Number.isNaN(date.valueOf())) throw new Error("Enter a valid schedule date."); request.scheduled_at = date.toISOString(); }
    const result = await api("/jobs", { method:"POST",body:JSON.stringify(request) });
    notify(`Job ${shortId(result.job_id)} submitted successfully.`); state.offset = 0; $("#status-filter").value = ""; await refresh(); await showJob(result.job_id);
  } catch (error) { notify(error instanceof SyntaxError ? "Payload must be valid JSON." : error.message,true); }
});
$("#close-detail").addEventListener("click", () => $("#detail").close());
$("#detail").addEventListener("click", (event) => { if (event.target === $("#detail")) $("#detail").close(); });
setView(location.hash.slice(1));
hideAccess();
$("#settings-toggle").textContent = "ⓘ Browser demo";
$("#settings-toggle").addEventListener("click", () => notify("This is a browser simulation. Your jobs are saved on this device; the GitHub repository contains the real backend."));
$("#task-type option[value='idempotent_counter']").remove();
$("#max-retries").value = "2";
$("#max-retries").max = "2";
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 2000);
