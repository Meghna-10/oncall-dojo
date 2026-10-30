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
let library = [], tab = "All";
async function loadScenarios() {
  library = await api("scenarios");
  $("nScen").textContent = library.length;
  const cats = ["All", ...new Set(library.map((s) => s.category))];
  $("tabs").innerHTML = cats.map((c) => {
    const n = c === "All" ? library.length : library.filter((s) => s.category === c).length;
    return `<button class="tab${c === tab ? " on" : ""}" data-cat="${esc(c)}">${esc(c === "All" ? "All scenarios" : c)} <span>${n}</span></button>`;
  }).join("");
  document.querySelectorAll(".tab").forEach((b) => (b.onclick = () => {
    tab = b.dataset.cat;
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("on", x === b));
    renderCards();
  }));
  renderCards(); renderFeatured();
  const stats = document.querySelector(".cc-stats");
  if ("IntersectionObserver" in window) {
    const o = new IntersectionObserver((es) => { if (es[0].isIntersecting) { countUp(); o.disconnect(); } });
    o.observe(stats);
  } else countUp();
}
// Category illustrations: lightweight CSS-3D / SVG, no WebGL per card.
const VISUALS = {
  "Database": `<div class="v v-db"><i class="disc"></i><i class="disc"></i><i class="disc"></i></div>`,
  "API & Application": `<div class="v v-api"><i class="core"></i><i class="orbit"><b></b><b></b><b></b></i></div>`,
  "Infrastructure & Cloud": `<div class="v v-rack"><div class="box"><i class="f front"><b></b><b></b><b></b><b></b></i><i class="f side"></i><i class="f top"></i></div></div>`,
  "Network & Security": `<div class="v v-net"><svg viewBox="0 0 120 90" aria-hidden="true">
      <path class="link" d="M20 70 L60 20 L100 70 L20 70 M60 20 L60 55"/>
      <path class="shield" d="M60 32 l16 6 v12 c0 10-7 16-16 20 c-9-4-16-10-16-20 v-12z"/>
      <circle cx="20" cy="70" r="5"/><circle cx="60" cy="20" r="5"/><circle cx="100" cy="70" r="5"/></svg></div>`,
  "Payments & Microservices": `<div class="v v-pay"><div class="term"><i class="screen"></i><i class="keys"></i></div><div class="cardchip"><i></i></div></div>`,
};
const SEV = { hard: "SEV-1", medium: "SEV-2", easy: "SEV-3" };

function cardHTML(s, i) {
  return `<article class="card" tabindex="0" role="button" data-id="${s.id}" data-diff="${s.difficulty}"
      aria-label="Start drill: ${esc(s.title)}" style="animation-delay:${Math.min(i, 12) * 40}ms">
    <div class="vis">${VISUALS[s.category] || ""}<span class="sev">${SEV[s.difficulty]}</span></div>
    <div class="card-body">
      <span class="cat">${esc(s.category)}</span>
      <div class="t">${esc(s.title)}</div>
      <div class="d">${esc(s.description)}</div>
      <div class="meta"><span class="diff ${s.difficulty}">${s.difficulty}</span><span class="dur">~${s.duration} min</span>
        <span class="go">Start drill →</span></div>
    </div>
  </article>`;
}

function renderFeatured() {
  const hard = library.filter((s) => s.difficulty === "hard");
  const day = Math.floor(Date.now() / 864e5);
  const f = hard[day % hard.length] || library[0];            // a different hard incident each day
  $("featured").innerHTML = `
    <div class="feat-art" aria-hidden="true">
      <div class="iso">${[0, 1, 2].map((k) => `<div class="box r${k}"><i class="f front"><b></b><b></b><b></b><b></b><b></b></i><i class="f side"></i><i class="f top"></i></div>`).join("")}
        <div class="beacon"></div></div>
    </div>
    <div class="feat-copy">
      <div class="feat-tags"><span class="sevtag">${SEV[f.difficulty]} · CRITICAL</span><span class="muted">Featured incident · ${esc(f.category)}</span></div>
      <h3>${esc(f.title)}</h3>
      <p>${esc(f.description)}</p>
      <div class="feat-meta"><span class="diff ${f.difficulty}">${f.difficulty}</span><span>~${f.duration} min</span></div>
      <button class="primary big" data-feat="${f.id}">Start simulation →</button>
    </div>`;
  $("featured").querySelector("[data-feat]").onclick = () => start(f.id);
}

function countUp() {
  const n = { total: library.length, cats: new Set(library.map((s) => s.category)).size };
  ["easy", "medium", "hard"].forEach((d) => (n[d] = library.filter((s) => s.difficulty === d).length));
  document.querySelectorAll("[data-count]").forEach((el) => {
    const target = n[el.dataset.count];
    if (calm) { el.textContent = target; return; }
    const t0 = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - t0) / 900);
      el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

function renderCards() {
  const q = $("search").value.trim().toLowerCase(), d = $("fDiff").value, dur = $("fDur").value;
  const shown = library.filter((s) => (tab === "All" || s.category === tab) && (!d || s.difficulty === d)
    && (!dur || String(s.duration) === dur)
    && (!q || (s.title + " " + s.description + " " + s.category).toLowerCase().includes(q)));
  $("count").textContent = `${shown.length} of ${library.length} incidents`;
  $("cards").innerHTML = shown.length ? shown.map(cardHTML).join("") : `<p class="muted">No incidents match these filters.</p>`;
  document.querySelectorAll("#cards .card").forEach((c) => {
    c.onclick = () => start(c.dataset.id);
    c.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); start(c.dataset.id); } };
    tilt(c, 9);
  });
}
["search", "fDiff", "fDur"].forEach((id) => $(id).addEventListener("input", renderCards));
$("randomBtn").onclick = () => start(null);
$("randomBtn2").onclick = () => start(null);
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
    spark($(svc + "-cP99"), h.p99, "#e3c48d");
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
    const rec = r.recovery;
    $("recovery").innerHTML = `
      <div class="rec-verdict ${rec.verified ? "yes" : "no"}">${rec.verified
        ? "✓ Recovery verified: every service has been healthy for the last 5 seconds."
        : "✗ Not verified: at least one service is still unhealthy, or the incident wasn't resolved."}</div>
      <div class="rec-grid">${rec.services.map((s) => `
        <div class="rec ${s.healthy ? "ok" : "bad"}"><b>${s.svc}</b>
          <span>error rate ${s.err_peak}% → <strong>${s.err_now}%</strong></span>
          <span>p99 ${s.p99_peak}ms → <strong>${s.p99_now}ms</strong></span></div>`).join("")}</div>`;
    $("board").classList.add("hidden");

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

// ---------- 3D motion (skipped when the user prefers reduced motion) ----------
const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
function tilt(el, max) {
  if (calm || !el) return;
  el.addEventListener("mousemove", (e) => {
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
    el.style.transform = `rotateY(${x * max}deg) rotateX(${-y * max}deg) translateZ(0)`;
  });
  el.addEventListener("mouseleave", () => (el.style.transform = ""));
}
document.querySelectorAll(".model").forEach((m) => tilt(m, 8));
const io = "IntersectionObserver" in window
  ? new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && e.target.classList.add("in")), { threshold: 0.12 })
  : null;
document.querySelectorAll("#landing .section").forEach((s) => {
  if (calm || !io) return;
  s.classList.add("reveal"); io.observe(s);
});

// ---------- Investigation board: evidence graph + AI hypotheses ----------
const GPOS = { gateway: [380, 70], orders: [265, 215], payments: [495, 215], db: [320, 365], cache: [440, 365] };
const GDIR = { gateway: 0, orders: -1, payments: 1, db: -1, cache: 1 };
const KIND = { log: "Log", deploy: "Deploy", config: "Config", cron: "Cron job" };
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

function drawGraph(ev) {
  const svg = $("graph"), parts = [];
  ev.deps.forEach(([a, b]) => {
    const [x1, y1] = GPOS[a], [x2, y2] = GPOS[b];
    parts.push(`<line class="g-dep" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`);
  });
  const per = {};
  ev.items.forEach((it) => {
    const i = (per[it.svc] = (per[it.svc] || 0) + 1) - 1;
    const [sx, sy] = GPOS[it.svc];
    const dir = GDIR[it.svc] || (i % 2 ? 1 : -1);
    const x = clamp(sx + dir * 230, 105, 655), y = clamp(sy - 30 + (GDIR[it.svc] ? i : Math.floor(i / 2)) * 46, 22, 420);
    const label = it.label.length > 34 ? it.label.slice(0, 33) + "…" : it.label;
    parts.push(`<line class="g-ev-link" x1="${sx}" y1="${sy}" x2="${x}" y2="${y}"/>`,
      `<g class="g-ev ${it.kind}"><title>${esc(it.label)}</title><rect x="${x - 100}" y="${y - 17}" width="200" height="34" rx="8"/>
        <text x="${x - 90}" y="${y - 3}" class="g-kind">${KIND[it.kind] || it.kind}</text>
        <text x="${x - 90}" y="${y + 11}">${esc(label)}</text></g>`);
  });
  ev.services.forEach((s) => {
    const [x, y] = GPOS[s.id];
    parts.push(`<g class="g-svc ${s.degraded ? "bad" : "ok"}"><circle cx="${x}" cy="${y}" r="34"/>
      <text x="${x}" y="${y - 2}" text-anchor="middle" class="g-name">${s.id}</text>
      <text x="${x}" y="${y + 14}" text-anchor="middle" class="g-stat">${s.err}% err</text></g>`);
  });
  if (!ev.items.length) parts.push(`<text x="380" y="425" text-anchor="middle" class="g-empty">No evidence yet. Read logs, check deploys and config diffs to fill the board.</text>`);
  svg.innerHTML = parts.join("");
}

async function openBoard() {
  $("board").classList.remove("hidden");
  $("boardClose").focus();
  try { drawGraph(await api("evidence")); } catch (e) {}
}
$("boardBtn").onclick = openBoard;
$("boardClose").onclick = () => $("board").classList.add("hidden");
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("board").classList.add("hidden"); });

$("hypBtn").onclick = async () => {
  $("hypBtn").disabled = true; $("hypBtn").textContent = "Nemotron 3 Super is weighing your evidence…";
  try {
    const r = await api("hypotheses", {});
    drawGraph(r.evidence);
    $("hypOut").innerHTML = r.hypotheses.map((h) => `
      <div class="hyp">
        <div class="hyp-top"><b>${esc(h.cause)}</b><span class="conf">${h.confidence}%</span></div>
        <div class="conf-bar"><i style="width:${h.confidence}%"></i></div>
        ${h.supports.length ? `<div class="hyp-l"><span class="ok-t">For</span> ${h.supports.map(esc).join(" · ")}</div>` : ""}
        ${h.against.length ? `<div class="hyp-l"><span class="no-t">Against</span> ${h.against.map(esc).join(" · ")}</div>` : ""}
        ${h.next_check ? `<div class="hyp-l"><span class="nx-t">Check next</span> <code>${esc(h.next_check)}</code></div>` : ""}
      </div>`).join("") + `<p class="radar-src">${r.source === "rule-fallback" ? "AI offline: ranked from your evidence by rules."
        : "Generated by Nemotron 3 Super from the evidence on the board. Verify before acting."}</p>`;
  } catch (e) {
    $("hypOut").innerHTML = `<p class="muted">Couldn't analyse right now. Try again.</p>`;
  } finally {
    $("hypBtn").disabled = false; $("hypBtn").textContent = "Analyse my evidence";
  }
};

// ---------- Change Risk Radar ----------
document.querySelectorAll(".chip").forEach((c) => (c.onclick = () => { $("radarIn").value = c.dataset.ex; $("radarIn").focus(); }));
$("radarForm").onsubmit = async (e) => {
  e.preventDefault();
  const change = $("radarIn").value.trim();
  if (change.length < 8) { $("radarIn").focus(); return; }
  $("radarBtn").disabled = true; $("radarBtn").textContent = "Analysing…";
  $("radarOut").innerHTML = `<div class="radar-empty"><div class="radar-ring"></div><p class="muted">Nemotron 3 Super is running a pre-mortem…</p></div>`;
  try {
    const r = await api("predict", { change });
    const preds = r.predictions.length ? r.predictions.map((p) => `
      <div class="pred">
        <div class="pred-top"><b>${esc(p.title)}</b><span class="diff ${p.difficulty}">${p.difficulty}</span></div>
        <p>${esc(p.why)}</p>
        ${p.early_signs.length ? `<small class="muted">Early warning signs</small><ul>${p.early_signs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        ${p.prevent ? `<div class="prevent"><b>Prevent:</b> ${esc(p.prevent)}</div>` : ""}
        <button class="ghost" data-drill="${p.scenario_id}" style="margin-top:10px">Practise this outage →</button>
      </div>`).join("") : `<p class="muted" style="margin-top:12px">No matching outage in the library. This change looks low-risk.</p>`;
    $("radarOut").innerHTML = `
      <div class="risk-head"><span class="risk ${r.risk}">${r.risk} risk</span></div>
      <div>${esc(r.summary)}</div>${preds}
      <div class="radar-src">${r.source === "keyword-fallback" ? "AI offline: matched by keywords against the incident library."
        : "AI estimate by Nemotron 3 Super. A prediction, not a guarantee."}</div>`;
    document.querySelectorAll("[data-drill]").forEach((b) => (b.onclick = () => start(b.dataset.drill)));
  } catch (err) {
    $("radarOut").innerHTML = `<p class="muted">Couldn't analyse that change. Please try again.</p>`;
  } finally {
    $("radarBtn").disabled = false; $("radarBtn").textContent = "Predict risks";
  }
};

loadScenarios();
