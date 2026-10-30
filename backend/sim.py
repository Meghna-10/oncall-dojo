"""Simulated production system for OnCall Dojo.

A small e-commerce stack (gateway -> orders/payments -> db/cache) whose metrics,
logs, configs and deploy history react to an injected fault and to the commands
the trainee runs. Everything is deterministic enough to grade, noisy enough to
feel real.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field

SERVICES = ["gateway", "orders", "payments", "db", "cache"]

BASELINE = {
    #            rps   err%   p99ms  cpu%  mem%
    "gateway":  (420,  0.2,   180,   35,   40),
    "orders":   (260,  0.1,   140,   30,   45),
    "payments": (90,   0.1,   220,   25,   38),
    "db":       (900,  0.0,   12,    40,   60),
    "cache":    (2400, 0.0,   2,     15,   55),
}

HISTORY_LEN = 90


from scenarios import SCENARIOS, Scenario  # noqa: E402,F401  (scenario library lives in its own file)

CONFIGS = {  # last known-good config; scenarios override keys to inject faults
    "gateway": {"payments.timeout_ms": 5000, "orders.timeout_ms": 3000,
                "retries": 2, "rate_limit_rps": 2000, "jwt.key_id": "k1"},
    "orders": {"db.pool_size": 50, "cache.ttl_s": 300, "feature.new_history_api": False,
               "feature.recommendations": False},
    "payments": {"fraud_check.enabled": True, "fraud_cache": "lru(10000)", "provider": "PayFast"},
    "db": {"max_connections": 500, "slow_query_log_ms": 500},
    "cache": {"maxmemory": "4gb", "eviction": "allkeys-lru", "min_replicas": 3},
}

CRON = ["cache-cleanup     58 2 * * *    redis-cli FLUSHALL",
        "db-backup         0 3 * * *     pg_dump --format=custom",
        "report-mailer     0 6 * * 1     python send_weekly.py"]

DEPLOYS = {
    "gateway": [("v3.2.0", "3 days ago"), ("v3.1.4", "9 days ago")],
    "orders": [("v2.4.0", "4 days ago"), ("v2.3.9", "11 days ago")],
    "payments": [("v1.8.3", "6 days ago"), ("v1.8.2", "14 days ago")],
    "db": [("pg-15.4", "41 days ago")],
    "cache": [("redis-7.2", "60 days ago")],
}

NOISE_LOGS = [
    ("gateway", "WARN", "TLS handshake from 10.2.8.14 took 410ms (client slow)"),
    ("orders", "INFO", "feature flag refresh complete (12 flags)"),
    ("payments", "INFO", "fraud-check model loaded: fraud-v7"),
    ("cache", "INFO", "background save complete (rdb, 1.2gb)"),
    ("db", "INFO", "autovacuum: table public.sessions"),
    ("gateway", "WARN", "deprecated header X-Client-Ver from mobile app 4.1"),
    ("orders", "WARN", "retrying inventory lookup (1/2) - transient"),
]


@dataclass
class Incident:
    scenario: Scenario
    started: float = field(default_factory=time.time)
    resolved_at: float | None = None
    resolution: str | None = None        # "full" | "partial"
    partial_until: float | None = None   # partial fixes wear off
    commands: list = field(default_factory=list)
    harmful_actions: list = field(default_factory=list)
    hints_used: int = 0
    analyses_used: int = 0                # AI hypothesis analyses requested
    peak: dict = field(default_factory=dict)   # worst err/p99 per service while broken
    status_updates: int = 0               # trainee messages to stakeholders
    chat: list = field(default_factory=list)
    configs: dict = field(default_factory=dict)
    deploys: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)
    last_tick: float = 0.0
    leak_mem: float = 50.0
    harm_until: float = 0.0
    logs: list = field(default_factory=list)

    # ---------- setup ----------
    def __post_init__(self):
        import copy
        self.configs = copy.deepcopy(CONFIGS)
        self.deploys = {k: list(v) for k, v in DEPLOYS.items()}
        sc = self.scenario
        if sc.deploy:
            svc, ver, when = sc.deploy
            self.deploys[svc].insert(0, (ver, when))
        for svc, kv in sc.config.items():
            self.configs[svc].update(kv)
        self.history = {s: {m: [] for m in ("rps", "err", "p99", "cpu", "mem")} for s in SERVICES}
        self.last_tick = self.started - HISTORY_LEN
        self.tick()

    @property
    def elapsed(self) -> float:
        end = self.resolved_at or time.time()
        return end - self.started

    def broken(self, now: float) -> bool:
        if self.resolution == "full":
            return False
        if self.resolution == "partial" and self.partial_until and now < self.partial_until:
            return False
        return True

    # ---------- metrics ----------
    def _sample(self, svc: str, t: float) -> tuple:
        rps, err, p99, cpu, mem = BASELINE[svc]
        j = lambda v, pct=0.06: max(0.0, v * (1 + random.uniform(-pct, pct)))
        rps, err, p99, cpu, mem = j(rps), j(err, .5), j(p99, .1), j(cpu), j(mem, .02)
        faulted = t >= self.started and self.broken(t)
        if faulted:
            m = {"rps": rps, "err": err, "p99": p99, "cpu": cpu, "mem": mem}
            for k, target in self.scenario.effects.get(svc, {}).items():
                m[k] = j(target, .1)
            rps, err, p99, cpu, mem = m["rps"], m["err"], m["p99"], m["cpu"], m["mem"]
            if self.scenario.id == "memory_leak" and svc == "payments":  # memory climbs, then OOM
                self.leak_mem = min(99.0, self.leak_mem + 3)
                if self.leak_mem >= 99:
                    self.leak_mem = 35.0  # OOMKilled -> restarted
                mem, err, p99 = self.leak_mem, j(30, .3), j(1800, .2)
        if t < self.harm_until and svc in ("gateway", "orders", "payments"):
            err, p99 = err + 15, p99 + 1500
        return round(rps), round(err, 2), round(p99), round(min(cpu, 100), 1), round(min(mem, 100), 1)

    def tick(self):
        now = time.time()
        t = max(self.last_tick + 1, now - HISTORY_LEN)
        while t <= now:
            for s in SERVICES:
                vals = self._sample(s, t)
                h = self.history[s]
                for k, v in zip(("rps", "err", "p99", "cpu", "mem"), vals):
                    h[k].append(v)
                    if len(h[k]) > HISTORY_LEN:
                        h[k].pop(0)
                if t >= self.started and self.broken(t):     # remember the worst, for the recovery check
                    pk = self.peak.setdefault(s, {"err": 0, "p99": 0})
                    pk["err"], pk["p99"] = max(pk["err"], vals[1]), max(pk["p99"], vals[2])
            self._emit_logs(t)
            t += 1
        self.last_tick = t - 1

    def _log(self, t, svc, lvl, msg):
        self.logs.append({"t": t, "svc": svc, "lvl": lvl, "msg": msg})
        if len(self.logs) > 600:
            self.logs = self.logs[-600:]

    def _emit_logs(self, t):
        if random.random() < 0.35:
            self._log(t, *random.choice(NOISE_LOGS))
        if not self.broken(t) or t < self.started:
            return
        r = random.random
        for svc, lvl, msg, prob in self.scenario.logs:
            if r() < prob:
                self._log(t, svc, lvl, msg.replace("{n}", str(random.randint(1200, 4900))))
        if self.scenario.id == "memory_leak":
            if r() < .4: self._log(t, "payments", "WARN", f"heap usage {int(self.leak_mem)}% - fraud_cache entries={random.randint(200, 900)}k")
            if self.leak_mem < 40 and r() < .8: self._log(t, "payments", "ERROR", "container killed: OOMKilled (exit 137), restarting (restarts=14)")
            if r() < .3: self._log(t, "gateway", "ERROR", "upstream payments: connection refused")

    # ---------- commands ----------
    def run(self, raw: str) -> str:
        self.tick()
        cmd = " ".join(raw.strip().split())
        if not cmd:
            return ""
        self.commands.append({"t": round(self.elapsed), "cmd": cmd})
        parts = cmd.split()
        head = parts[0]

        for prefix, why in self.scenario.harmful.items():
            if cmd.startswith(prefix):
                self.harmful_actions.append({"cmd": cmd, "why": why})
                self.harm_until = time.time() + 25
                return f"[ok] {cmd}\n!! side effects observed: error rates spiking across services"

        fix = self.scenario.fixes.get(cmd)
        if fix and self.resolution != "full":
            kind, why = fix
            if kind == "full":
                self.resolution, self.resolved_at = "full", time.time()
            else:
                self.resolution, self.partial_until = "partial", time.time() + 35
            self._apply_side_state(cmd)
            return f"[ok] {cmd}\n{self._fix_output(cmd)}"

        h = HANDLERS.get(head)
        if h is None:
            return f"dojo: command not found: {head}\nType 'help' to see available commands."
        return h(self, parts[1:])

    def _apply_side_state(self, cmd):
        if cmd.startswith("rollback "):
            svc = cmd.split()[1]
            if len(self.deploys[svc]) > 1:
                self.deploys[svc].pop(0)
        parts = cmd.split()
        if cmd.startswith("config rollback ") and parts[2] in CONFIGS:
            self.configs[parts[2]] = dict(CONFIGS[parts[2]])
        if cmd.startswith("config set ") and len(parts) >= 4 and "=" in parts[3]:
            k, v = parts[3].split("=", 1)
            self.configs[parts[2]][k] = v
        if self.scenario.id == "memory_leak" and cmd == "rollback payments":
            self.configs["payments"]["fraud_cache"] = "lru(10000)"
        if cmd == "restart payments":
            self.leak_mem = 35.0

    def _fix_output(self, cmd):
        if cmd.startswith("rollback"):
            svc = cmd.split()[1]
            return f"deploying {svc} {self.deploys[svc][0][0]} ... 3/3 pods ready"
        if cmd.startswith("restart"):
            return "pods terminated, 3/3 pods ready"
        if cmd.startswith("db add-index"):
            return "CREATE INDEX CONCURRENTLY idx_orders_customer_id ... done (41s)"
        if cmd.startswith("config"):
            return f"config applied to {cmd.split()[2]} (3/3 instances reloaded)"
        if cmd == "cache warm":
            return "warming 48,210 hot keys from db snapshot ... done"
        if cmd.startswith("disable cron"):
            return f"cron job {cmd.split()[-1]} disabled"
        if cmd.startswith("scale"):
            return f"{cmd.split()[1]} scaled to {cmd.split()[2]} replicas ... ready"
        if cmd.startswith("cert renew"):
            return "ACME order placed ... certificate issued (valid 90 days) ... reloaded"
        if cmd == "dns rollback":
            return "payments.internal -> 10.0.4.21 (previous record) ... propagated"
        if cmd.startswith("failover"):
            return f"{cmd.split()[1]}: switched to standby ... healthy"
        if cmd.startswith("queue scale"):
            return f"order-events consumers -> {cmd.split()[2]} ... backlog draining"
        if cmd.startswith("disk cleanup"):
            return "removed 61 GB of old logs ... disk 72%"
        if cmd == "db kill-locks":
            return "terminated 14 blocked transactions"
        return "done"

    # ---------- view ----------
    def snapshot(self) -> dict:
        self.tick()
        now = time.time()
        healthy = not self.broken(now)
        return {
            "scenario": {"id": self.scenario.id, "title": self.scenario.title,
                         "page": self.scenario.page, "difficulty": self.scenario.difficulty},
            "elapsed": round(self.elapsed),
            "resolved": self.resolution == "full",
            "healthy": healthy,
            "partial": self.resolution == "partial",
            "history": self.history,
            "chat": self.chat[-60:],
            "hints_used": self.hints_used,
        }

    # ---------- evidence graph ----------
    DEPS = [("gateway", "orders"), ("gateway", "payments"), ("orders", "db"),
            ("payments", "db"), ("orders", "cache"), ("payments", "cache")]

    def evidence(self) -> dict:
        """What the trainee has actually discovered, linked to the service it concerns.

        Only clues surfaced by commands the trainee ran appear here, so the board
        organises their investigation instead of solving it for them."""
        self.tick()
        services = []
        for s in SERVICES:
            h = self.history[s]
            bad = h["err"][-1] > 5 or h["p99"][-1] > 1500 or h["cpu"][-1] > 90 or h["mem"][-1] > 90
            services.append({"id": s, "degraded": bad, "err": h["err"][-1], "p99": h["p99"][-1],
                             "cpu": h["cpu"][-1], "mem": h["mem"][-1]})
        items, seen = [], set()

        def add(kind, svc, label, detail=""):
            key = (kind, svc, label)
            if key not in seen:
                seen.add(key)
                items.append({"id": f"e{len(items)}", "kind": kind, "svc": svc, "label": label, "detail": detail})

        for c in self.commands:
            p = c["cmd"].split()
            if p[0] == "logs" and len(p) > 1 and p[1] in SERVICES:
                recent = [l for l in self.logs if l["svc"] == p[1] and l["lvl"] in ("WARN", "ERROR")][-40:]
                shape = lambda m: re.sub(r"\d+", "#", m)          # same line, different numbers = one clue
                shapes = [shape(l["msg"]) for l in recent]
                example = {shape(l["msg"]): l for l in recent}
                # errors before warnings, then the most repeated: noise is usually a one-off WARN
                for sh in sorted(set(shapes), key=lambda s: (example[s]["lvl"] == "ERROR", shapes.count(s)), reverse=True)[:2]:
                    add("log", p[1], example[sh]["msg"][:90], f"seen {shapes.count(sh)}x in {p[1]} logs")
            elif p[0] == "grep" and len(p) > 1:
                q = " ".join(p[1:]).lower()
                for l in [l for l in self.logs if q in l["msg"].lower()][-2:]:
                    add("log", l["svc"], l["msg"][:90], f"grep '{q}'")
            elif p[0] == "deploys":
                for s in ([p[1]] if len(p) > 1 and p[1] in SERVICES else SERVICES):
                    ver, when = self.deploys[s][0]
                    if "min ago" in when:
                        add("deploy", s, f"{s} {ver} deployed {when}", "recent deploy")
            elif p[:2] == ["config", "diff"] and len(p) > 2 and p[2] in SERVICES:
                for k, v in self.configs[p[2]].items():
                    if str(CONFIGS[p[2]].get(k)) != str(v):
                        add("config", p[2], f"{k}: {CONFIGS[p[2]].get(k)} -> {v}", "config change")
            elif p[0] == "crontab":
                for row in CRON[:1] + self.scenario.cron:
                    name = row.split()[0]
                    add("cron", "cache" if "redis" in row else "db", f"cron {name}: {' '.join(row.split()[1:6])}", row)
        return {"services": services, "deps": self.DEPS, "items": items,
                "commands_run": len(self.commands)}

    def recovery(self) -> dict:
        """Verified recovery: worst values while broken vs. the last 5 seconds."""
        self.tick()
        out, ok = [], True
        for s in SERVICES:
            h = self.history[s]
            last = {k: sum(h[k][-5:]) / 5 for k in ("err", "p99", "cpu", "mem")}
            healthy = last["err"] <= 5 and last["p99"] <= 1500 and last["cpu"] <= 90 and last["mem"] <= 90
            ok = ok and healthy
            pk = self.peak.get(s, {})
            out.append({"svc": s, "healthy": healthy, "err_peak": pk.get("err", last["err"]),
                        "err_now": round(last["err"], 2), "p99_peak": pk.get("p99", last["p99"]),
                        "p99_now": round(last["p99"])})
        return {"verified": ok and self.resolution == "full", "services": out}

    # ---------- shadow engineer: decision milestones ----------
    def _clue_cmds(self) -> set:
        """Commands that surface this scenario's real clue (deploy, config, cron, or the key log)."""
        sc, cmds = self.scenario, set()
        if sc.deploy:
            cmds |= {"deploys", f"deploys {sc.deploy[0]}"}
        for svc in sc.config:
            cmds.add(f"config diff {svc}")
        if sc.cron or sc.id == "cache_stampede":
            cmds.add("crontab")
        if not cmds:                                   # incidents found only in logs (cert, dns, provider, ...)
            cmds |= {f"logs {svc}" for svc, lvl, *_ in sc.logs if lvl == "ERROR"}
        return cmds

    def decisions(self) -> dict:
        """Milestones of the trainee's run vs. an estimated expert path, plus the facts a reviewer needs."""
        sc = self.scenario
        affected = set(sc.effects) or {"payments"}
        first = lambda pred: next((c["t"] for c in self.commands if pred(c["cmd"])), None)
        clue = self._clue_cmds()
        fix_t = round(self.resolved_at - self.started) if self.resolved_at else None
        upd_t = next((m["t"] for m in self.chat if m["kind"] == "me"), None)
        actual = {
            "first_look": first(lambda c: c.split()[0] in ("status", "logs", "metrics", "grep")),
            "first_affected_log": first(lambda c: c.split()[0] == "logs" and len(c.split()) > 1 and c.split()[1] in affected),
            "clue_found": first(lambda c: c in clue),
            "status_update": upd_t,
            "fix_applied": fix_t,
        }
        # estimated expert path: status, logs of the worst service, the clue, an update, the fix (~8 s per step)
        bench = {"first_look": 5, "first_affected_log": 12, "clue_found": 22, "status_update": 30, "fix_applied": 40}
        wrong_logs = [c["cmd"] for c in self.commands if c["cmd"].startswith("logs ") and c["cmd"].split()[-1] not in affected]
        return {"actual": actual, "benchmark": bench, "clue_commands": sorted(clue),
                "affected": sorted(affected), "detours": wrong_logs[:5],
                "harmful": [h["cmd"] for h in self.harmful_actions], "hints": self.hints_used,
                "analyses": self.analyses_used, "updates": self.status_updates,
                "partial_fix_used": any(c["cmd"] in sc.fixes and sc.fixes[c["cmd"]][0] == "partial" for c in self.commands)}

    def decision_quality(self) -> dict:
        """Judgement scored on four axes (0-100 each), separate from the speed-based drill score."""
        d = self.decisions()
        a = d["actual"]
        inv = 100 if a["clue_found"] is not None else 30
        if a["clue_found"] is not None and a["fix_applied"] is not None and a["clue_found"] > a["fix_applied"]:
            inv = 50                                    # fixed first, understood later
        inv -= min(30, 10 * len(d["detours"]))
        safety = max(0, 100 - 35 * len(d["harmful"]) - (15 if d["partial_fix_used"] else 0))
        comm = 0 if d["updates"] == 0 else 70 + min(30, 15 * (d["updates"] - 1))
        if a["status_update"] is not None and a["status_update"] > 120:
            comm -= 20
        verify = 100 if self.resolution == "full" else 20
        axes = {"investigation": max(0, inv), "safety": safety, "communication": max(0, comm), "verification": verify}
        return {"axes": axes, "overall": round(sum(axes.values()) / 4)}

    def score(self) -> dict:
        mttr = self.elapsed
        s = 100
        breakdown = []
        if self.resolution != "full":
            s -= 40; breakdown.append(("Incident not fully resolved", -40))
        t_pen = int(max(0, mttr - 120) / 30) * 3
        t_pen = min(t_pen, 25)
        if t_pen: s -= t_pen; breakdown.append((f"Time to resolve {int(mttr)}s", -t_pen))
        h_pen = len(self.harmful_actions) * 12
        if h_pen: s -= h_pen; breakdown.append((f"{len(self.harmful_actions)} harmful action(s)", -h_pen))
        hint_pen = self.hints_used * 5
        if hint_pen: s -= hint_pen; breakdown.append((f"{self.hints_used} hint(s) used", -hint_pen))
        a_pen = self.analyses_used * 3
        if a_pen: s -= a_pen; breakdown.append((f"{self.analyses_used} AI hypothesis analysis(es)", -a_pen))
        if self.status_updates == 0:
            s -= 10; breakdown.append(("No status update sent to stakeholders", -10))
        investigated = any(c["cmd"].split()[0] in ("logs", "metrics", "deploys", "config") for c in self.commands)
        if not investigated:
            s -= 10; breakdown.append(("Changed things before investigating", -10))
        s = max(0, s)
        grade = "S" if s >= 95 else "A" if s >= 85 else "B" if s >= 70 else "C" if s >= 50 else "D"
        return {"score": s, "grade": grade, "mttr": int(mttr), "breakdown": breakdown}


# ---------- read-only commands ----------
def _fmt_t(t):
    return time.strftime("%H:%M:%S", time.localtime(t))


def c_help(inc, a):
    return """Available commands
  status                         overview of all services
  logs <svc> [n]                 last n log lines (default 15)   svc: gateway orders payments db cache
  grep <text>                    search logs of every service
  metrics <svc>                  current metrics for a service
  deploys [svc]                  recent deploy history
  config show <svc>              current config
  config diff <svc>              config changes since last known-good
  config set <svc> key=value     change a config value
  config rollback <svc>          revert config to last known-good
  restart <svc>                  restart a service
  rollback <svc>                 roll back to previous deploy
  scale <svc> <n>                change replica count
  db add-index <table>.<column>  create an index
  cache warm | flush cache       warm or flush the shared cache
  crontab                        list scheduled jobs
  disable cron <name>            disable a scheduled job
  db kill-locks                  kill blocked database transactions
  disk cleanup <svc>             delete old logs and temp files
  cert renew <svc>               issue a new TLS certificate
  dns rollback                   restore the previous internal DNS records
  failover <svc>                 switch db primary region / payment provider
  queue scale <n>                set the number of queue consumers
  clear                          clear the terminal"""


def c_status(inc, a):
    rows = ["SERVICE    RPS     ERR%    P99ms   CPU%   MEM%   STATE"]
    for s in SERVICES:
        h = inc.history[s]
        err, p99 = h["err"][-1], h["p99"][-1]
        state = "DEGRADED" if err > 5 or p99 > 1500 or h["cpu"][-1] > 90 or h["mem"][-1] > 90 else "ok"
        rows.append(f"{s:<10} {h['rps'][-1]:<7} {err:<7} {p99:<7} {h['cpu'][-1]:<6} {h['mem'][-1]:<6} {state}")
    return "\n".join(rows)


def c_logs(inc, a):
    if not a or a[0] not in SERVICES:
        return "usage: logs <svc> [n]"
    n = int(a[1]) if len(a) > 1 and a[1].isdigit() else 15
    lines = [l for l in inc.logs if l["svc"] == a[0]][-n:]
    return "\n".join(f"{_fmt_t(l['t'])} {l['lvl']:<5} {l['msg']}" for l in lines) or "(no recent logs)"


def c_grep(inc, a):
    if not a:
        return "usage: grep <text>"
    q = " ".join(a).lower()
    lines = [l for l in inc.logs if q in l["msg"].lower()][-20:]
    return "\n".join(f"{_fmt_t(l['t'])} [{l['svc']}] {l['lvl']:<5} {l['msg']}" for l in lines) or "(no matches)"


def c_metrics(inc, a):
    if not a or a[0] not in SERVICES:
        return "usage: metrics <svc>"
    h = inc.history[a[0]]
    avg = lambda k: round(sum(h[k][-10:]) / 10, 1)
    return (f"{a[0]} (avg last 10s)\n  requests/s  {avg('rps')}\n  error rate  {avg('err')}%\n"
            f"  p99 latency {avg('p99')}ms\n  cpu         {avg('cpu')}%\n  memory      {avg('mem')}%")


def c_deploys(inc, a):
    svcs = [a[0]] if a and a[0] in SERVICES else SERVICES
    out = []
    for s in svcs:
        for i, (v, when) in enumerate(inc.deploys[s][:3]):
            out.append(f"{s:<10} {v:<10} {when:<14} {'CURRENT' if i == 0 else ''}")
    return "\n".join(out)


def c_config(inc, a):
    if len(a) < 2 or a[1] not in SERVICES:
        return "usage: config show|diff|set|rollback <svc> ..."
    op, svc = a[0], a[1]
    if op == "show":
        return "\n".join(f"{k}: {v}" for k, v in inc.configs[svc].items())
    if op == "diff":
        diffs = [f"- {k}: {CONFIGS[svc][k]}\n+ {k}: {v}" for k, v in inc.configs[svc].items()
                 if str(CONFIGS[svc].get(k)) != str(v)]
        if diffs:
            return f"{svc} config changed 14 min ago by deploy-bot (ticket OPS-2291):\n" + "\n".join(diffs)
        return f"{svc}: no changes from last known-good config"
    if op == "rollback":
        inc.configs[svc] = dict(CONFIGS[svc])
        return f"[ok] {svc} config reverted (no change in behaviour)"
    if op == "set" and len(a) >= 3 and "=" in a[2]:
        k, v = a[2].split("=", 1)
        inc.configs[svc][k] = v
        return f"[ok] {svc} {k}={v} (no change in behaviour)"
    return "usage: config show|diff|set|rollback <svc> ..."


def c_noop(inc, a, name=""):
    return f"[ok] done. (no visible change)"


def c_crontab(inc, a):
    return "\n".join(["NAME              SCHEDULE      COMMAND"] + CRON + inc.scenario.cron)


def c_restart(inc, a):
    if not a or a[0] not in SERVICES:
        return "usage: restart <svc>"
    return f"[ok] restarting {a[0]} ... 3/3 pods ready (no change in behaviour)"


def c_rollback(inc, a):
    if not a or a[0] not in SERVICES:
        return "usage: rollback <svc>"
    return f"[ok] {a[0]} rolled back ... 3/3 pods ready (no change in behaviour)"


def c_scale(inc, a):
    if len(a) < 2:
        return "usage: scale <svc> <n>"
    return f"[ok] {a[0]} scaled to {a[1]} replicas (no change in behaviour)"


HANDLERS = {
    "help": c_help, "status": c_status, "logs": c_logs, "grep": c_grep,
    "metrics": c_metrics, "deploys": c_deploys, "config": c_config,
    "crontab": c_crontab, "restart": c_restart, "rollback": c_rollback,
    "scale": c_scale, "db": c_noop, "cache": c_noop, "disable": c_noop,
    "flush": c_noop, "disk": c_noop, "cert": c_noop, "dns": c_noop,
    "failover": c_noop, "queue": c_noop,
}
