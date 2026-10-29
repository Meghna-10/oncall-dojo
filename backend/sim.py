"""Simulated production system for OnCall Dojo.

A small e-commerce stack (gateway -> orders/payments -> db/cache) whose metrics,
logs, configs and deploy history react to an injected fault and to the commands
the trainee runs. Everything is deterministic enough to grade, noisy enough to
feel real.
"""
from __future__ import annotations

import random
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


@dataclass
class Scenario:
    id: str
    title: str
    page: str                # what the pager says
    root_cause: str          # hidden from the trainee, used for grading + AI coach
    fixes: dict              # command -> ("full"|"partial", explanation)
    harmful: dict            # command prefix -> penalty explanation
    difficulty: str


SCENARIOS = {
    "slow_query": Scenario(
        id="slow_query",
        title="Checkout is timing out",
        page="CRITICAL: gateway 5xx rate > 25% on /api/checkout",
        root_cause=("orders v2.4.1 (deployed 6 min before the page) added "
                    "'SELECT * FROM orders WHERE customer_id = ?' with no index on "
                    "customer_id. Sequential scans pin db CPU at ~98%, orders p99 "
                    "climbs past 4s and the gateway returns 504s."),
        fixes={
            "rollback orders": ("full", "Rolled back the deploy that introduced the slow query."),
            "db add-index orders.customer_id": ("full", "Added the missing index; the query is fast again."),
            "restart db": ("partial", "Restart cleared connections but the slow query returns immediately."),
        },
        harmful={
            "flush cache": "Flushing the cache during a DB overload sends even more traffic to the db.",
            "scale db": "The db is CPU-bound on one bad query; more replicas only spread the pain.",
        },
        difficulty="medium",
    ),
    "memory_leak": Scenario(
        id="memory_leak",
        title="Payments keep crashing",
        page="CRITICAL: payments pods restarting (OOMKilled) - card payments failing",
        root_cause=("payments v1.9.0 caches every fraud-check response in an "
                    "unbounded in-process dict. Memory grows ~3%/s until the pod is "
                    "OOMKilled; each restart buys ~30s before it dies again."),
        fixes={
            "rollback payments": ("full", "Rolled back to v1.8.3, which has a bounded LRU cache."),
            "restart payments": ("partial", "Restart frees memory but the leak refills it within a minute."),
        },
        harmful={
            "restart db": "Restarting a healthy database caused a needless outage for every service.",
            "flush cache": "The shared cache was healthy; flushing it slowed every service.",
        },
        difficulty="easy",
    ),
    "bad_config": Scenario(
        id="bad_config",
        title="Every payment times out",
        page="CRITICAL: 100% of payment attempts failing with upstream timeout",
        root_cause=("A config push changed gateway 'payments.timeout_ms' from 5000 to "
                    "50 (typo). Payments is healthy, but the gateway gives up after 50ms, "
                    "so every payment call is reported as a timeout."),
        fixes={
            "config rollback gateway": ("full", "Reverted the gateway config to the previous version."),
            "config set gateway payments.timeout_ms=5000": ("full", "Restored the correct upstream timeout."),
        },
        harmful={
            "restart payments": "Payments was never broken; restarting it dropped in-flight charges.",
            "rollback payments": "Rolled back a healthy service; the real problem was the gateway config.",
            "scale payments": "Payments had spare capacity; the timeout lives in the gateway config.",
        },
        difficulty="hard",
    ),
    "cache_stampede": Scenario(
        id="cache_stampede",
        title="Whole site is slow",
        page="WARNING: p99 latency > 3s on all endpoints, db connections at 98%",
        root_cause=("A cron job ran 'FLUSHALL' on the cache at 02:58. With a cold cache "
                    "every request goes to the db; db connections saturate and every "
                    "service slows down (a cache stampede)."),
        fixes={
            "cache warm": ("full", "Warmed the hot keys; the db load fell back to normal."),
            "disable cron cache-cleanup": ("partial", "Stopped the job from repeating, but the cache is still cold."),
        },
        harmful={
            "restart db": "Restarting the db dropped all connections and made the stampede worse.",
            "rollback orders": "orders' latest deploy was days old and unrelated.",
        },
        difficulty="medium",
    ),
}

CONFIGS = {
    "gateway": {"payments.timeout_ms": 5000, "orders.timeout_ms": 3000,
                "retries": 2, "rate_limit_rps": 2000},
    "orders": {"db.pool_size": 50, "cache.ttl_s": 300, "feature.new_history_api": True},
    "payments": {"fraud_check.enabled": True, "fraud_cache": "lru(10000)"},
    "db": {"max_connections": 500, "slow_query_log_ms": 500},
    "cache": {"maxmemory": "4gb", "eviction": "allkeys-lru"},
}

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
        sid = self.scenario.id
        if sid == "slow_query":
            self.deploys["orders"].insert(0, ("v2.4.1", "6 min ago"))
        elif sid == "memory_leak":
            self.deploys["payments"].insert(0, ("v1.9.0", "25 min ago"))
            self.configs["payments"]["fraud_cache"] = "dict()  # unbounded"
        elif sid == "bad_config":
            self.configs["gateway"]["payments.timeout_ms"] = 50
            self._config_prev = {"payments.timeout_ms": 5000}
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
        sid = self.scenario.id
        faulted = t >= self.started and self.broken(t)
        if faulted:
            if sid == "slow_query":
                if svc == "db": cpu, p99 = j(97, .02), j(2400, .2)
                if svc == "orders": p99, err = j(4200, .15), j(18, .2)
                if svc == "gateway": err, p99 = j(27, .15), j(5000, .05)
            elif sid == "memory_leak":
                if svc == "payments":
                    self.leak_mem = min(99.0, self.leak_mem + 3)
                    if self.leak_mem >= 99:
                        self.leak_mem = 35.0  # OOMKilled -> restarted
                    mem, err, p99 = self.leak_mem, j(30, .3), j(1800, .2)
                if svc == "gateway": err = j(9, .2)
            elif sid == "bad_config":
                if svc == "gateway": err = j(21, .1)
                if svc == "payments": rps = j(88)   # payments looks perfectly healthy
            elif sid == "cache_stampede":
                if svc == "cache": rps = j(300)
                if svc == "db": cpu, rps, p99 = j(91, .03), j(4100), j(900, .2)
                if svc in ("orders", "payments", "gateway"): p99 = j(3400, .15); err = j(4, .3)
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
        sid = self.scenario.id
        r = random.random
        if sid == "slow_query":
            if r() < .6: self._log(t, "db", "WARN", f"slow query ({random.randint(2100, 4800)}ms): SELECT * FROM orders WHERE customer_id = $1  -- Seq Scan on orders (rows=18.2M)")
            if r() < .5: self._log(t, "orders", "ERROR", "GET /orders/history: context deadline exceeded after 3000ms")
            if r() < .5: self._log(t, "gateway", "ERROR", "upstream orders returned 504 for /api/checkout")
        elif sid == "memory_leak":
            if r() < .4: self._log(t, "payments", "WARN", f"heap usage {int(self.leak_mem)}% - fraud_cache entries={random.randint(200, 900)}k")
            if self.leak_mem < 40 and r() < .8: self._log(t, "payments", "ERROR", "container killed: OOMKilled (exit 137), restarting (restarts=14)")
            if r() < .3: self._log(t, "gateway", "ERROR", "upstream payments: connection refused")
        elif sid == "bad_config":
            if r() < .7: self._log(t, "gateway", "ERROR", "upstream payments timeout after 50ms (POST /api/pay)")
            if r() < .3: self._log(t, "payments", "INFO", f"POST /charge 200 in {random.randint(180, 260)}ms")
            if r() < .1: self._log(t, "payments", "WARN", "client closed connection before response was written")
        elif sid == "cache_stampede":
            if r() < .5: self._log(t, "cache", "INFO", f"keyspace hits=0.{random.randint(1, 9)}% misses high")
            if r() < .5: self._log(t, "db", "WARN", "remaining connection slots are reserved (connections 491/500)")
            if r() < .4: self._log(t, "orders", "WARN", "cache MISS product:* - falling back to db")
            if r() < .05: self._log(t, "cache", "INFO", "cron[cache-cleanup] executed FLUSHALL at 02:58 (schedule: 58 2 * * *)")

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
        if cmd.startswith("config rollback gateway") or cmd.startswith("config set gateway"):
            self.configs["gateway"]["payments.timeout_ms"] = 5000
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
            return "config applied to gateway (3/3 instances reloaded)"
        if cmd == "cache warm":
            return "warming 48,210 hot keys from db snapshot ... done"
        if cmd.startswith("disable cron"):
            return "cron job cache-cleanup disabled"
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
    return ("NAME            SCHEDULE      COMMAND\n"
            "cache-cleanup   58 2 * * *    redis-cli FLUSHALL\n"
            "db-backup       0 3 * * *     pg_dump --format=custom\n"
            "report-mailer   0 6 * * 1     python send_weekly.py")


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
    "flush": c_noop,
}
