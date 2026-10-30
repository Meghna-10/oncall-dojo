const $ = (id) => document.getElementById(id);
const SID = (crypto.randomUUID && crypto.randomUUID()) || String(Math.random());
const SVCS = ["gateway", "orders", "payments", "db", "cache"];
let poll = null, seenChat = 0, history = [], hIdx = 0, ended = false, updates = 0, lastHistory = null;

async function api(path, body) {
  const r = await fetch("/api/" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-Session": SID },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 404 && path !== "scenarios") { sessionLost(); throw new Error("session lost"); }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// the server restarted (e.g. a free host waking from sleep): say so instead of going silent
function sessionLost() {
  clearInterval(poll);
  if (!$("incident").classList.contains("hidden")) {
    term("!! This drill was lost because the server restarted. Click '← New drill' to start again.", "err");
    $("endBtn").textContent = "← New drill";
    $("endBtn").onclick = () => location.reload();
  }
}
window.addEventListener("unhandledrejection", (e) => {
  if (String(e.reason).includes("session lost")) e.preventDefault();
});

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const mmss = (s) => String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
const show = (id) => ["landing", "incident", "review"].forEach((x) => $(x).classList.toggle("hidden", x !== id));

// ---------- landing ----------
const CARD_INFO = {
  slow_query: ["🐢", "Checkout requests are timing out and customers can't pay."],
  memory_leak: ["💥", "The payments service keeps crashing and restarting."],
  bad_config: ["⏱️", "Every payment fails, but the payments service looks healthy."],
  cache_stampede: ["🌊", "Every page is slow and the database is overloaded."],
};
async function loadScenarios() {
  const list = await api("scenarios");
  $("cards").innerHTML = list.map((s) => {
    const [ic, d] = CARD_INFO[s.id] || ["🚨", ""];
    return `<div class="card" data-id="${s.id}">
      <div class="ic">${ic}</div>
      <div class="t">${esc(s.title)}</div>
      <div class="d">${esc(d)}</div>
      <div class="meta"><span class="diff ${s.difficulty}">${s.difficulty}</span><span class="go">Start drill →</span></div>
    </div>`;
  }).join("");
  document.querySelectorAll(".card").forEach((c) => (c.onclick = () => start(c.dataset.id)));
}
$("randomBtn").onclick = () => start(null);
document.querySelectorAll("[data-scroll]").forEach((b) =>
  (b.onclick = () => $(b.dataset.scroll).scrollIntoView({ behavior: "smooth" })));

// ---------- pager sound ----------
let audio, beepTimer;
function beep() {
  try {
    audio = audio || new AudioContext();
    const o = audio.createOscillator(), g = audio.createGain();
    o.frequency.value = 880; o.type = "square"; g.gain.value = 0.05;
    o.connect(g); g.connect(audio.destination); o.start(); o.stop(audio.currentTime + 0.18);
  } catch (e) {}
}

// ---------- incident ----------
async function start(id) {
  const s = await api("incident", { scenario: id });
  seenChat = 0; ended = false; updates = 0; mission = {}; lastHistory = null;
  $("termOut").innerHTML = ""; $("chatLog").innerHTML = "";
  $("coachBody").className = "coach-body idle";
  $("coachBody").textContent = "Stuck? Ask for a hint. The coach knows the root cause but will only point you in the right direction. Each hint costs 5 points.";
  $("kUpd").textContent = "0";
  $("pagerText").textContent = s.scenario.page;
  $("pager").classList.remove("hidden");
  beep(); beepTimer = setInterval(beep, 900);
  $("incTitle").textContent = s.scenario.title;
  buildDash(); renderMission();
}

$("ackBtn").onclick = () => {
  clearInterval(beepTimer);
  $("pager").classList.add("hidden");
  show("incident");
  term("Connected to prod-bastion-01. You are on call.\nUse the buttons above, or type 'help' to see every command.", "ok");
  $("termIn").focus();
  clearInterval(poll); poll = setInterval(refresh, 1000); refresh();
};

function buildDash() {
  $("dash").innerHTML = SVCS.map((s) => `
    <div class="svc" id="svc-${s}">
      <div class="svc-name">${s}<span class="state" id="${s}-state">OK</span></div>
      <div class="metric">error rate <b id="${s}-err"></b></div>
      <canvas id="${s}-cErr"></canvas>
      <div class="metric">p99 latency <b id="${s}-p99"></b></div>
      <canvas id="${s}-cP99"></canvas>
      <div class="metric">cpu / mem <b id="${s}-res"></b></div>
    </div>`).join("");
}

function spark(canvas, data, color, fill = true) {
  const w = (canvas.width = canvas.clientWidth * 2), h = (canvas.height = canvas.clientHeight * 2);
  const ctx = canvas.getContext("2d"), max = Math.max(...data, 1e-9);
  ctx.beginPath();
  data.forEach((v, i) => {
    const x = (i / (data.length - 1 || 1)) * w, y = h - (v / max) * (h - 6) - 3;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.stroke();
  if (!fill) return;
  ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
  ctx.fillStyle = color + "22"; ctx.fill();
}

const isBad = (h) => {
  const last = (k) => h[k][h[k].length - 1];
  return last("err") > 5 || last("p99") > 1500 || last("cpu") > 90 || last("mem") > 90;
};

async function refresh() {
  let s;
  try { s = await api("state"); } catch (e) { return; }
  lastHistory = s.history;
  $("timer").textContent = mmss(s.elapsed);
  const pill = $("statusPill");
  if (s.resolved) { pill.className = "pill ok"; pill.textContent = "RESOLVED"; }
  else if (s.healthy) { pill.className = "pill partial"; pill.textContent = "MITIGATED?"; }
  else { pill.className = "pill crit"; pill.textContent = "CRITICAL"; }
  if (s.resolved && !mission.fix) { mission.fix = true; renderMission(); }
  $("aiMode").innerHTML = s.ai.online ? "AI: <b>Nemotron live</b> on Nebius" : "AI: offline mode";

  let bad = 0;
  for (const svc of SVCS) {
    const h = s.history[svc], last = (k) => h[k][h[k].length - 1];
    const b = isBad(h); bad += b;
    $("svc-" + svc).classList.toggle("bad", b);
    $(svc + "-state").textContent = b ? "DEGRADED" : "OK";
    $(svc + "-err").textContent = last("err") + "%";
    $(svc + "-p99").textContent = last("p99") + "ms";
    $(svc + "-res").textContent = `${last("cpu")}% / ${last("mem")}%`;
    spark($(svc + "-cErr"), h.err, b ? "#ff5468" : "#3ddc84");
    spark($(svc + "-cP99"), h.p99, "#5aa9ff");
  }
  const g = s.history.gateway, gl = (k) => g[k][g[k].length - 1];
  $("kErr").textContent = gl("err") + "%";
  $("kErr").className = gl("err") > 5 ? "red" : "";
  $("kP99").textContent = gl("p99") >= 1000 ? (gl("p99") / 1000).toFixed(1) + "s" : gl("p99") + "ms";
  $("kP99").className = gl("p99") > 1500 ? "amber" : "";
  $("kBad").textContent = `${bad} / 5`;
  $("kBad").className = bad ? "red" : "";

  for (const m of s.chat.slice(seenChat)) addMsg(m);
  seenChat = s.chat.length;
}

function addMsg(m) {
  if (m.kind === "hint") {                     // coach hints live in the coach panel
    const body = $("coachBody");
    if (body.classList.contains("idle")) { body.className = "coach-body"; body.innerHTML = ""; }
    body.insertAdjacentHTML("beforeend", `<div class="h">${esc(m.text)}</div>`);
    return;
  }
  const d = document.createElement("div");
  d.className = "msg " + m.kind;
  d.innerHTML = `<div class="who">${esc(m.who)}<span>T+${mmss(m.t)}</span></div>${esc(m.text)}`;
  $("chatLog").appendChild(d);
  $("chatLog").scrollTop = 1e9;
  if (m.kind === "msg") beep();
}

function term(text, cls) {
  const d = document.createElement("div");
  if (cls) d.className = cls;
  d.textContent = text;
  $("termOut").appendChild(d);
  $("termOut").scrollTop = 1e9;
}

$("termIn").addEventListener("keydown", async (e) => {
  if (e.key === "ArrowUp" && history.length) { hIdx = Math.max(0, hIdx - 1); e.target.value = history[hIdx]; return; }
  if (e.key === "ArrowDown") { hIdx = Math.min(history.length, hIdx + 1); e.target.value = history[hIdx] || ""; return; }
  if (e.key !== "Enter") return;
  const cmd = e.target.value.trim(); e.target.value = "";
  if (cmd) runCmd(cmd);
});

async function runCmd(cmd) {
  history.push(cmd); hIdx = history.length;
  if (cmd === "clear") { $("termOut").innerHTML = ""; return; }
  term("oncall@prod:~$ " + cmd, "cmd");
  const r = await api("cmd", { cmd });
  term(r.output, r.output.includes("!!") || r.output.startsWith("dojo:") ? "err" : "");
  const head = cmd.split(" ")[0];
  if (head === "status") mission.look = true;
  if (["logs", "grep", "metrics"].includes(head)) mission.logs = true;
  if (["deploys", "config", "crontab"].includes(head)) mission.change = true;
  renderMission();
  refresh();
}
document.querySelectorAll(".quick button").forEach((b) => (b.onclick = () => runCmd(b.dataset.cmd)));

$("chatForm").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("chatIn").value.trim(); $("chatIn").value = "";
  if (!text) return;
  await api("chat", { text });
  updates += 1; $("kUpd").textContent = updates;
  mission.team = true; renderMission(); refresh();
};

$("hintBtn").onclick = async () => {
  $("hintBtn").disabled = true; $("hintBtn").textContent = "Thinking…";
  try { await api("hint", {}); refresh(); }
  finally { $("hintBtn").disabled = false; $("hintBtn").textContent = "💡 Get a hint"; }
};

// ---------- mission guide ----------
const STEPS = [
  ["look", "See what's broken", "Click “Check all services”. DEGRADED means that service has a problem."],
  ["logs", "Read the logs", "Open the logs of a red service and look for repeated WARN or ERROR lines."],
  ["change", "Find what changed", "Outages often follow a change. Check recent deploys, config changes and scheduled jobs."],
  ["team", "Update your team", "Post a short status update in the war room on the right."],
  ["fix", "Fix the cause", "Type the fix in the terminal, e.g. rollback <service>. Use the AI coach if you're stuck."],
];
let mission = {};
function renderMission() {
  const next = STEPS.find(([k]) => !mission[k]);
  $("missionSteps").innerHTML = STEPS.map(([k, name], i) =>
    `<li class="step ${mission[k] ? "done" : next && next[0] === k ? "now" : ""}"><i>${mission[k] ? "✓" : i + 1}</i>${name}</li>`).join("");
  $("missionText").className = "next" + (mission.fix ? " ok" : "");
  $("missionText").textContent = mission.fix ? "✅ Resolved! Click “End & review” to see your report."
    : next ? "👉 Next: " + next[2] : "";
}

// ---------- report ----------
function md(src) {
  return esc(src)
    .replace(/^#{2,3} (.*)$/gm, "<h2>$1</h2>")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^[-*] (.*)$/gm, "• $1")
    .replace(/\n/g, "<br>")
    .replace(/(<br>)+(<h2>)/g, "$2").replace(/(<\/h2>)(<br>)+/g, "$1");
}

$("endBtn").onclick = async () => {
  if (ended) return; ended = true;
  $("endBtn").textContent = "Nemotron Ultra is writing your report…";
  $("endBtn").disabled = true;
  clearInterval(poll);
  try {
    const r = await api("end", {});
    show("review"); window.scrollTo(0, 0);
    $("repTitle").textContent = r.title;
    $("repSub").textContent = r.score >= 85 ? "Great job. Here's how your incident response went."
      : "Here's what happened and how to do better next time.";
    $("grade").textContent = r.grade;
    $("ring").style.setProperty("--p", r.score);
    $("scoreLine").textContent = `${r.score} / 100`;
    $("sMttr").textContent = mmss(r.mttr);
    $("sCmds").textContent = r.commands.length;
    $("sHints").textContent = r.hints;
    $("sHarm").textContent = r.harmful.length;
    $("sHarm").className = r.harmful.length ? "red" : "";

    $("breakdown").innerHTML = r.breakdown.length
      ? r.breakdown.map(([why, pts]) => `<li><div class="row"><span>${esc(why)}</span><b class="red">${pts}</b></div>
          <div class="bar"><i style="width:${Math.min(100, Math.abs(pts) * 2.5)}%"></i></div></li>`).join("")
      : `<li><div class="row"><span>Flawless run, no deductions</span><b>0</b></div><div class="bar good"><i style="width:100%"></i></div></li>`;

    const harmful = new Set(r.harmful.map((h) => h.cmd));
    $("timeline").innerHTML = r.commands.length ? r.commands.map((c) => {
      const cls = harmful.has(c.cmd) ? "harm" : /^(rollback|config (set|rollback)|cache warm|db add-index)/.test(c.cmd) ? "fix" : "";
      return `<li class="${cls}"><time>T+${mmss(c.t)}</time><code>${esc(c.cmd)}</code></li>`;
    }).join("") : `<li><time>T+00:00</time>No commands were run.</li>`;

    spark($("repChart"), (r.history || lastHistory).gateway.err, "#ff5468");
    $("reviewText").innerHTML = md(r.review);

    const roles = { nano: "Manager & support role-play", super: "Coach hints", ultra: "This report" };
    const maxTok = Math.max(1, ...Object.values(r.ai.usage).map((u) => u.tokens));
    $("aiUsage").innerHTML = Object.entries(r.ai.usage).map(([tier, u]) => `
      <div><b>Nemotron 3 ${tier[0].toUpperCase() + tier.slice(1)}</b>${roles[tier]}
      <div class="bar"><i style="width:${(u.tokens / maxTok) * 100}%"></i></div>
      ${u.calls} calls · ${u.tokens} tokens</div>`).join("");
  } finally {
    $("endBtn").textContent = "End & review"; $("endBtn").disabled = false;
  }
};

$("againBtn").onclick = () => { show("landing"); window.scrollTo(0, 0); };

loadScenarios();
