const $ = (id) => document.getElementById(id);
const SID = (crypto.randomUUID && crypto.randomUUID()) || String(Math.random());
const SVCS = ["gateway", "orders", "payments", "db", "cache"];
let poll = null, seenChat = 0, history = [], hIdx = 0, ended = false;

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

// ---------- landing ----------
async function loadScenarios() {
  const list = await api("scenarios");
  $("cards").innerHTML = list.map((s) => `
    <div class="card" data-id="${s.id}">
      <div class="diff ${s.difficulty}">${s.difficulty}</div>
      <div class="t">${esc(s.title)}</div>
      <div style="color:var(--muted);font-size:12px">Root cause hidden until the review</div>
    </div>`).join("");
  document.querySelectorAll(".card").forEach((c) => (c.onclick = () => start(c.dataset.id)));
}
$("randomBtn").onclick = () => start(null);

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
  seenChat = 0; ended = false; mission = {}; renderMission();
  $("termOut").innerHTML = ""; $("chatLog").innerHTML = "";
  $("landing").classList.add("hidden"); $("review").classList.add("hidden");
  $("pagerText").textContent = s.scenario.page;
  $("pager").classList.remove("hidden");
  beep(); beepTimer = setInterval(beep, 900);
  $("incTitle").textContent = s.scenario.title;
  buildDash();
}

$("ackBtn").onclick = () => {
  clearInterval(beepTimer);
  $("pager").classList.add("hidden");
  $("incident").classList.remove("hidden");
  term("Connected to prod-bastion-01. You are on call.\nType 'help' to list commands, start with 'status'.", "ok");
  $("termIn").focus();
  clearInterval(poll); poll = setInterval(refresh, 1000); refresh();
};

function buildDash() {
  $("dash").innerHTML = SVCS.map((s) => `
    <div class="svc" id="svc-${s}">
      <div class="svc-name">${s}<i class="dot"></i></div>
      <div class="metric">error rate <b id="${s}-err"></b></div>
      <canvas id="${s}-cErr"></canvas>
      <div class="metric">p99 latency <b id="${s}-p99"></b></div>
      <canvas id="${s}-cP99"></canvas>
      <div class="metric">cpu / mem <b id="${s}-res"></b></div>
    </div>`).join("");
}

function spark(canvas, data, color) {
  const w = (canvas.width = canvas.clientWidth * 2), h = (canvas.height = 68);
  const ctx = canvas.getContext("2d"), max = Math.max(...data, 1e-9);
  ctx.beginPath();
  data.forEach((v, i) => {
    const x = (i / (data.length - 1 || 1)) * w, y = h - (v / max) * (h - 6) - 3;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.stroke();
  ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
  ctx.fillStyle = color + "22"; ctx.fill();
}

async function refresh() {
  let s;
  try { s = await api("state"); } catch (e) { return; }
  $("timer").textContent = mmss(s.elapsed);
  const pill = $("statusPill");
  if (s.resolved && !mission.fix) { mission.fix = true; renderMission(); }
  if (s.resolved) { pill.className = "pill ok"; pill.textContent = "RESOLVED"; }
  else if (s.healthy) { pill.className = "pill partial"; pill.textContent = "MITIGATED?"; }
  else { pill.className = "pill crit"; pill.textContent = "CRITICAL"; }
  $("aiMode").innerHTML = s.ai.online ? "AI: <b>Nemotron live</b>" : "AI: offline mode";

  for (const svc of SVCS) {
    const h = s.history[svc], last = (k) => h[k][h[k].length - 1];
    const bad = last("err") > 5 || last("p99") > 1500 || last("cpu") > 90 || last("mem") > 90;
    $("svc-" + svc).classList.toggle("bad", bad);
    $(svc + "-err").textContent = last("err") + "%";
    $(svc + "-p99").textContent = last("p99") + "ms";
    $(svc + "-res").textContent = `${last("cpu")}% / ${last("mem")}%`;
    spark($(svc + "-cErr"), h.err, bad ? "#ff4d5e" : "#3ddc84");
    spark($(svc + "-cP99"), h.p99, "#5aa9ff");
  }

  for (const m of s.chat.slice(seenChat)) addMsg(m);
  seenChat = s.chat.length;
}

function addMsg(m) {
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

// ---------- mission guide ----------
const STEPS = [
  ["look", "See what's broken", "Click Check all services. DEGRADED means that service has a problem."],
  ["logs", "Read the logs", "Open the logs of a red service and look for repeated WARN or ERROR lines."],
  ["change", "Find what changed", "Outages often follow a change. Check recent deploys, config changes and scheduled jobs."],
  ["team", "Update your team", "Type a short status update in the war room on the right."],
  ["fix", "Fix the cause", "Type the fix in the terminal, like rollback <service>. Use Hint if you're stuck."],
];
let mission = {};
function renderMission() {
  const next = STEPS.find(([k]) => !mission[k]);
  $("missionSteps").innerHTML = STEPS.map(([k, name], i) =>
    `<span class="step ${mission[k] ? "done" : next && next[0] === k ? "now" : ""}">${mission[k] ? "✓" : i + 1} ${name}</span>`).join("");
  $("missionText").textContent = next ? "Next: " + next[2] : "Fixed! Click End & review to see your score.";
}

$("chatForm").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("chatIn").value.trim(); $("chatIn").value = "";
  if (text) { await api("chat", { text }); mission.team = true; renderMission(); refresh(); }
};

$("hintBtn").onclick = async () => {
  $("hintBtn").disabled = true;
  try { await api("hint", {}); refresh(); } finally { $("hintBtn").disabled = false; }
};

// ---------- review ----------
function md(src) {
  return esc(src)
    .replace(/^## (.*)$/gm, "<h2>$1</h2>")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^[-*] (.*)$/gm, "• $1")
    .replace(/\n/g, "<br>");
}

$("endBtn").onclick = async () => {
  if (ended) return; ended = true;
  $("endBtn").textContent = "Nemotron Ultra is writing your review…";
  $("endBtn").disabled = true;
  clearInterval(poll);
  try {
    const r = await api("end", {});
    $("grade").textContent = r.grade;
    $("scoreLine").textContent = `${r.score}/100 · resolved in ${mmss(r.mttr)}`;
    $("breakdown").innerHTML = r.breakdown.length
      ? r.breakdown.map(([why, pts]) => `<li>${esc(why)} (${pts})</li>`).join("")
      : "<li>Flawless run.</li>";
    $("reviewText").innerHTML = md(r.review);
    const roles = { nano: "Stakeholder role-play", super: "Coach hints", ultra: "Post-incident review" };
    $("aiUsage").innerHTML = Object.entries(r.ai.usage).map(([tier, u]) => `
      <div><b>Nemotron ${tier[0].toUpperCase() + tier.slice(1)}</b>${roles[tier]}<br>
      ${u.calls} calls · ${u.tokens} tokens<br><span style="font-size:10px">${esc(r.ai.models[tier])}</span></div>`).join("");
    $("review").classList.remove("hidden");
  } finally {
    $("endBtn").textContent = "End & review"; $("endBtn").disabled = false;
  }
};

$("againBtn").onclick = () => {
  $("review").classList.add("hidden"); $("incident").classList.add("hidden");
  $("landing").classList.remove("hidden");
};

loadScenarios();
