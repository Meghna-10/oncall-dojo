"""OnCall Dojo API server."""
from __future__ import annotations

import json
import random
import re
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import llm
from sim import SCENARIOS, Incident

app = FastAPI(title="OnCall Dojo")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

sessions: dict[str, Incident] = {}
next_ping: dict[str, float] = {}
lock = threading.Lock()

PERSONAS = {
    "manager": ("Priya (Eng Manager)",
                "You are Priya, an engineering manager during a live production outage. "
                "You are stressed, the CEO is asking you for updates. Write ONE short Slack "
                "message (max 25 words) to the on-call engineer. Push for an ETA and a status "
                "update. Never suggest technical fixes. No emojis, no quotes."),
    "customer": ("Support: Rahul",
                 "You are Rahul from customer support during a production outage. Relay ONE "
                 "short, slightly frantic message (max 25 words) about what angry customers "
                 "are reporting, based on the symptoms. Never suggest fixes. No quotes."),
}

FALLBACK_PINGS = {
    "manager": ["Any update? CEO is asking in #exec.", "What's the ETA? I need something to tell people.",
                "Is this the deploy from this morning? Please post a status update.",
                "It's been a while. Do we need to escalate?"],
    "customer": ["Twitter is blowing up, people say checkout is broken.",
                 "A big merchant just called, they're losing sales every minute.",
                 "Got 140 tickets in 10 minutes. What should I tell customers?"],
}


def _incident(sid: str | None) -> Incident:
    inc = sessions.get(sid or "")
    if not inc:
        raise HTTPException(404, "no active incident - start one first")
    return inc


def _say(inc: Incident, who: str, text: str, kind: str = "msg"):
    inc.chat.append({"t": round(inc.elapsed), "who": who, "text": text, "kind": kind})


def _stakeholder_ping(inc: Incident, role: str, reply_to: str | None = None):
    name, system = PERSONAS[role]
    sc = inc.scenario
    ctx = (f"Outage: {sc.title}. Pager: {sc.page}. Minutes since page: {inc.elapsed / 60:.1f}. "
           f"Engineer has sent {inc.status_updates} status update(s). "
           f"Incident status: {'RESOLVED - alerts have cleared, be relieved and ask for a summary' if inc.resolution == 'full' else 'still ongoing'}.")
    if reply_to:
        ctx += (f"\nThe on-call engineer (not you) just posted: \"{reply_to}\". "
                f"Write {name}'s reply to them, in {name}'s own voice.")
    was_resolved = inc.resolution == "full"
    text = llm.chat("nano", system, ctx, max_tokens=80, fallback=random.choice(FALLBACK_PINGS[role]))
    if inc.resolution == "full" and not was_resolved:
        return  # written while the outage was live; posting "ETA?" after RESOLVED reads wrong
    text = re.sub(r"\s*\*?\(\d+ words?\)\*?\s*$", "", text.strip()).strip('"')  # drop "(24 words)"
    # the model sometimes signs its own line: "Priya:", "Priya (Engineering Manager) ..."
    first = re.escape(name.split()[0].rstrip(":"))
    text = re.sub(rf"^{first}\b\s*(\([^)]*\))?\s*:?\s*", "", text, flags=re.I).strip()
    with lock:
        _say(inc, name, text)


class StartReq(BaseModel):
    scenario: str | None = None


class CmdReq(BaseModel):
    cmd: str


class ChatReq(BaseModel):
    text: str


@app.get("/api/scenarios")
def scenarios():
    # card data only: the root cause, fixes and clues never leave the server before the review
    return [{"id": s.id, "title": s.title, "difficulty": s.difficulty, "category": s.category,
             "icon": s.icon, "description": s.description, "duration": s.duration}
            for s in SCENARIOS.values()]


@app.post("/api/incident")
def start(req: StartReq, x_session: str = Header(...)):
    sc = SCENARIOS.get(req.scenario or "") or random.choice(list(SCENARIOS.values()))
    inc = Incident(sc)
    sessions[x_session] = inc
    next_ping[x_session] = time.time() + 25
    _say(inc, "PagerDuty", sc.page, kind="page")
    threading.Thread(target=_stakeholder_ping, args=(inc, "manager"), daemon=True).start()
    return inc.snapshot()


@app.get("/api/state")
def state(x_session: str = Header(...)):
    inc = _incident(x_session)
    now = time.time()
    if inc.resolution != "full" and now >= next_ping.get(x_session, now + 1):
        next_ping[x_session] = now + random.uniform(35, 55)
        role = random.choice(["manager", "customer"])
        threading.Thread(target=_stakeholder_ping, args=(inc, role), daemon=True).start()
    snap = inc.snapshot()
    snap["ai"] = llm.usage_report()
    return snap


@app.post("/api/cmd")
def cmd(req: CmdReq, x_session: str = Header(...)):
    inc = _incident(x_session)
    was_resolved = inc.resolution == "full"
    out = inc.run(req.cmd[:300])
    if inc.resolution == "full" and not was_resolved:
        _say(inc, "PagerDuty", "RESOLVED: all alerts cleared", kind="resolved")
    return {"output": out}


@app.post("/api/chat")
def chat(req: ChatReq, x_session: str = Header(...)):
    inc = _incident(x_session)
    text = req.text.strip()[:400]
    if not text:
        return {}
    inc.status_updates += 1
    _say(inc, "You", text, kind="me")
    threading.Thread(target=_stakeholder_ping, args=(inc, "manager", text), daemon=True).start()
    return {}


@app.post("/api/hint")
def hint(x_session: str = Header(...)):
    inc = _incident(x_session)
    inc.hints_used += 1
    recent = "\n".join(c["cmd"] for c in inc.commands[-12:]) or "(none yet)"
    system = ("You are a calm senior SRE coaching a junior engineer through a live incident "
              "simulation. You know the hidden root cause. Give ONE Socratic hint (max 40 words) "
              "that nudges the next investigation step based on what they have already tried. "
              "NEVER reveal the root cause, name the specific mechanism (e.g. 'missing index', "
              "'memory leak', 'timeout value'), or give the fix command. Point to WHERE to look, "
              "not WHAT they will find.")
    user = (f"Hidden root cause: {inc.scenario.root_cause}\nPager: {inc.scenario.page}\n"
            f"Commands tried so far:\n{recent}\n"
            "Available tools: status, logs <svc>, grep, metrics, deploys, config diff, crontab.")
    text = llm.chat("super", system, user, max_tokens=120, fallback=inc.scenario.hint)
    _say(inc, "Coach (Nemotron Super)", text, kind="hint")
    return {"hint": text}


@app.post("/api/end")
def end(x_session: str = Header(...)):
    inc = _incident(x_session)
    sc = inc.score()
    timeline = "\n".join(f"T+{c['t']}s  $ {c['cmd']}" for c in inc.commands) or "(no commands)"
    msgs = "\n".join(f"T+{m['t']}s {m['who']}: {m['text']}" for m in inc.chat if m["kind"] == "me")
    system = ("You are a principal SRE writing a blameless post-incident review of a TRAINING "
              "drill for the engineer who handled it. Be specific, kind, and direct. Use markdown "
              "with exactly these sections: ## Summary, ## Root cause, ## Timeline highlights, "
              "## What went well, ## What to improve, ## Drill next time. Max 300 words. "
              "Refer to commands by their exact text.")
    user = (f"Scenario: {inc.scenario.title}\nTrue root cause: {inc.scenario.root_cause}\n"
            f"Resolved: {inc.resolution == 'full'} (partial fix used: {inc.resolution == 'partial'})\n"
            f"Time to resolve: {sc['mttr']}s\nHints used: {inc.hints_used}\n"
            f"Harmful actions: {json.dumps(inc.harmful_actions)}\n"
            f"Command timeline:\n{timeline}\n"
            f"Status updates sent to stakeholders:\n{msgs or '(none)'}\n"
            f"Score {sc['score']}/100: {sc['breakdown']}")
    fallback = (f"## Summary\n{inc.scenario.title} - {'resolved' if inc.resolution == 'full' else 'not resolved'} "
                f"in {sc['mttr']}s.\n\n## Root cause\n{inc.scenario.root_cause}\n\n"
                "## What to improve\n" + ("\n".join(f"- {b[0]}" for b in sc["breakdown"]) or "- Nothing - clean run!")
                + "\n\n_(offline mode: set NEBIUS_API_KEY for a full Nemotron Ultra review)_")
    # Ultra reasons before it writes; 900 tokens cut reviews off mid-sentence
    review = llm.chat("ultra", system, user, max_tokens=2500, fallback=fallback)
    return {**sc, "review": review, "root_cause": inc.scenario.root_cause, "ai": llm.usage_report(),
            "title": inc.scenario.title, "commands": inc.commands,
            "harmful": inc.harmful_actions, "hints": inc.hints_used,
            "updates": inc.status_updates, "history": inc.history, "recovery": inc.recovery(),
            "analyses": inc.analyses_used}


@app.get("/api/evidence")
def evidence(x_session: str = Header(...)):
    return _incident(x_session).evidence()


def _rule_hypotheses(ev: dict) -> list:
    """Offline fallback: one hypothesis per discovered change, ranked by how many degraded services it touches."""
    bad = {s["id"] for s in ev["services"] if s["degraded"]}
    hyps = []
    for it in ev["items"]:
        if it["kind"] in ("deploy", "config", "cron"):
            hyps.append({"cause": f"{it['label']} caused the {it['svc']} degradation",
                         "confidence": 60 if it["svc"] in bad else 30,
                         "supports": [it["label"]], "against": [] if it["svc"] in bad else [f"{it['svc']} looks healthy"],
                         "next_check": f"logs {it['svc']}"})
    if not hyps:
        hyps.append({"cause": "Not enough evidence yet", "confidence": 0, "supports": [],
                     "against": [], "next_check": "deploys"})
    return sorted(hyps, key=lambda h: -h["confidence"])[:3]


@app.post("/api/hypotheses")
def hypotheses(x_session: str = Header(...)):
    """Multi-hypothesis analysis of the evidence the trainee has gathered so far."""
    inc = _incident(x_session)
    inc.analyses_used += 1
    ev = inc.evidence()
    bad = ", ".join(f"{s['id']} (err {s['err']}%, p99 {s['p99']}ms, cpu {s['cpu']}%, mem {s['mem']}%)"
                    for s in ev["services"] if s["degraded"]) or "none"
    found = "\n".join(f"- [{i['kind']}] {i['svc']}: {i['label']}" for i in ev["items"]) or "- (nothing gathered yet)"
    system = ("You are a senior SRE helping a trainee reason about a live incident. From ONLY the evidence "
              "listed, propose 2 or 3 competing root-cause hypotheses. For each give a confidence 0-100 "
              "(they need not sum to 100), the evidence that supports it, any evidence against it, and ONE "
              "terminal command that would confirm or refute it (commands: status, logs <svc>, metrics <svc>, "
              "deploys, config diff <svc>, crontab, grep <text>). Never tell them the fix. If the evidence is "
              "thin, say so with low confidence and suggest what to gather. Keep every text field under 20 "
              "words and next_check to a single command. Answer JSON only: "
              '{"hypotheses":[{"cause":"","confidence":0,"supports":[""],"against":[""],"next_check":""}]}')
    user = f"Pager: {inc.scenario.page}\nDegraded services: {bad}\nEvidence gathered:\n{found}"
    raw = llm.chat("super", system, user, max_tokens=1600, fallback="")
    source = "nemotron-3-super"
    # parse every complete hypothesis object, so a reply cut off mid-way still yields the finished ones
    found_objs, dec = [], json.JSONDecoder()
    for m in re.finditer(r'\{\s*"cause"', raw):
        try:
            obj, _ = dec.raw_decode(raw[m.start():])
            found_objs.append(obj)
        except ValueError:
            continue
    try:
        hyps = [{"cause": str(h.get("cause", ""))[:200], "confidence": max(0, min(100, int(h.get("confidence", 0)))),
                 "supports": [str(x)[:160] for x in h.get("supports", [])][:3],
                 "against": [str(x)[:160] for x in h.get("against", [])][:2],
                 "next_check": str(h.get("next_check", ""))[:80]} for h in found_objs][:3]
    except (ValueError, TypeError, AttributeError):
        hyps = []
    if not hyps:
        hyps, source = _rule_hypotheses(ev), "rule-fallback"
    _say(inc, "Coach (Nemotron Super)", f"Analysed {len(ev['items'])} piece(s) of evidence: {len(hyps)} hypotheses on the board.",
         kind="hint")
    return {"hypotheses": sorted(hyps, key=lambda h: -h["confidence"]), "source": source, "evidence": ev}


class PredictReq(BaseModel):
    change: str


def _keyword_predictions(change: str) -> list:
    """Offline fallback: rank library scenarios by words shared with the change."""
    words = {w for w in re.findall(r"[a-z0-9_]{3,}", change.lower())}
    scored = []
    for s in SCENARIOS.values():
        text = f"{s.title} {s.description} {s.root_cause} {' '.join(s.fixes)}".lower()
        hits = sum(1 for w in words if w in text)
        if hits:
            scored.append((hits, s))
    scored.sort(key=lambda x: -x[0])
    return [{"scenario_id": s.id, "why": s.root_cause.split(". ")[0] + ".",
             "early_signs": [s.page], "prevent": f"Know the fix before you ship: {next(iter(s.fixes))}"}
            for _, s in scored[:3]]


@app.post("/api/predict")
def predict(req: PredictReq):
    """Change Risk Radar: predict which outages a planned change could cause."""
    change = req.change.strip()[:1200]
    if len(change) < 8:
        raise HTTPException(400, "describe the change in a sentence or two")
    catalog = "\n".join(f"- {s.id}: {s.title}. Cause pattern: {s.root_cause}" for s in SCENARIOS.values())
    system = ("You are a principal SRE doing a pre-mortem on a change an engineer is about to ship. "
              "Using ONLY the outage patterns in the catalog, predict which ones this change could cause. "
              "Answer with JSON only, no markdown, in this exact shape: "
              '{"risk":"low|medium|high","summary":"one sentence","predictions":[{"scenario_id":"<id from catalog>",'
              '"why":"one sentence linking the change to this failure","early_signs":["metric or log to watch",'
              '"..."],"prevent":"one concrete safeguard"}]}. Give 1 to 3 predictions, most likely first. '
              "If the change looks safe, use risk low and an empty predictions list. Never mention catalog "
              "ids or the word 'pattern' in your sentences; write for the engineer.")
    user = f"Outage catalog:\n{catalog}\n\nPlanned change:\n{change}"
    raw = llm.chat("super", system, user, max_tokens=900, fallback="")
    result, source = None, "nemotron-3-super"
    try:
        start = raw.index("{")
        data = json.loads(raw[start:raw.rindex("}") + 1])
        preds = [p for p in data.get("predictions", []) if p.get("scenario_id") in SCENARIOS][:3]
        if data.get("risk") in ("low", "medium", "high"):
            result = {"risk": data["risk"], "summary": str(data.get("summary", ""))[:300],
                      "predictions": [] if data["risk"] == "low" else preds}
    except (ValueError, AttributeError, TypeError):
        result = None
    if result is None:  # AI offline or unparseable: say so and fall back to keyword matching
        preds = _keyword_predictions(change)
        result = {"risk": "medium" if preds else "low", "predictions": preds,
                  "summary": "Keyword match against the incident library (AI estimate unavailable)."}
        source = "keyword-fallback"
    for p in result["predictions"]:
        s = SCENARIOS[p["scenario_id"]]
        p.update(title=s.title, icon=s.icon, category=s.category, difficulty=s.difficulty)
        p["early_signs"] = [str(x) for x in p.get("early_signs", [])][:3]
    return {**result, "source": source, "ai": llm.usage_report()["online"]}


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
