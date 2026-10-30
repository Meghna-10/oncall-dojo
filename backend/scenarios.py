"""Scenario library for OnCall Dojo.

Each scenario is pure data: what the pager says, which service metrics go bad,
which log lines appear, what changed (deploy / config / cron), the hidden root
cause, which commands fix it (fully or partially), which commands make it worse,
and the coach's offline hint. sim.py turns this into a live system.

Metric effects are target values (rps, err %, p99 ms, cpu %, mem %) that apply
while the incident is unresolved. Log entries are (service, level, message,
probability per second); "{n}" in a message becomes a random number.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CATEGORIES = ["API & Application", "Database", "Infrastructure & Cloud",
              "Network & Security", "Payments & Microservices"]
DURATION = {"easy": 5, "medium": 10, "hard": 15}


@dataclass
class Scenario:
    id: str
    title: str
    category: str
    difficulty: str
    icon: str
    description: str           # shown on the card (symptom only, never the cause)
    page: str                  # what the pager says
    root_cause: str            # hidden until the review; used by the coach and Ultra
    fixes: dict                # exact command -> ("full" | "partial", explanation)
    harmful: dict              # command prefix -> why it hurts
    hint: str                  # offline coach hint
    effects: dict = field(default_factory=dict)   # svc -> {metric: target}
    logs: list = field(default_factory=list)      # (svc, level, msg, prob)
    deploy: tuple | None = None                   # (svc, version, when) pushed on top
    config: dict = field(default_factory=dict)    # svc -> {key: bad value}
    cron: list = field(default_factory=list)      # extra crontab rows

    @property
    def duration(self) -> int:
        return DURATION[self.difficulty]


_S = Scenario
SCENARIOS_LIST = [
    # ------------------------------------------------------------ API & Application
    _S("slow_query", "Checkout is timing out", "API & Application", "medium", "🐢",
       "Checkout requests time out and customers can't pay.",
       "CRITICAL: gateway 5xx rate > 25% on /api/checkout",
       "orders v2.4.1 (deployed 6 min before the page) added 'SELECT * FROM orders WHERE "
       "customer_id = ?' with no index on customer_id. Sequential scans pin db CPU at ~98%, "
       "orders p99 climbs past 4s and the gateway returns 504s.",
       {"rollback orders": ("full", "Rolled back the deploy that introduced the slow query."),
        "db add-index orders.customer_id": ("full", "Added the missing index; the query is fast again."),
        "restart db": ("partial", "Restart cleared connections but the slow query returns immediately.")},
       {"flush cache": "Flushing the cache during a DB overload sends even more traffic to the db.",
        "scale db": "The db is CPU-bound on one bad query; more replicas only spread the pain."},
       "Something changed recently. Which service deployed last, and what is the database complaining about in its logs?",
       effects={"db": {"cpu": 97, "p99": 2400}, "orders": {"p99": 4200, "err": 18},
                "gateway": {"err": 27, "p99": 5000}},
       logs=[("db", "WARN", "slow query ({n}ms): SELECT * FROM orders WHERE customer_id = $1  -- Seq Scan on orders (rows=18.2M)", .6),
             ("orders", "ERROR", "GET /orders/history: context deadline exceeded after 3000ms", .5),
             ("gateway", "ERROR", "upstream orders returned 504 for /api/checkout", .5)],
       deploy=("orders", "v2.4.1", "6 min ago")),

    _S("http500_flag", "Order history returns HTTP 500", "API & Application", "easy", "🔴",
       "Customers see an error page when they open their order history.",
       "CRITICAL: orders 5xx rate > 30% on /orders/history",
       "The feature flag 'feature.new_history_api' was switched on 9 min ago. The new code path "
       "throws a NullPointerException for customers with no past orders, so a third of requests fail.",
       {"config rollback orders": ("full", "Turned the new feature flag back off."),
        "config set orders feature.new_history_api=false": ("full", "Disabled the broken feature flag."),
        "restart orders": ("partial", "Restart changes nothing for long; the flag is still on.")},
       {"rollback orders": "The deploy was days old; the change was a feature flag, not code.",
        "restart db": "The database was healthy; restarting it hurt every service."},
       "Errors started without a deploy. What else can change how code behaves at runtime?",
       effects={"orders": {"err": 34}, "gateway": {"err": 14}},
       logs=[("orders", "ERROR", "NullPointerException at HistoryController.render (flag new_history_api=on)", .7),
             ("gateway", "ERROR", "upstream orders returned 500 for /orders/history", .4)],
       config={"orders": {"feature.new_history_api": True}}),

    _S("retry_storm", "API gateway is overloaded", "API & Application", "hard", "🌐",
       "Every endpoint is slow and the gateway's CPU is maxed out.",
       "CRITICAL: gateway CPU > 95%, p99 latency > 3s on all routes",
       "A config push raised gateway 'retries' from 2 to 8. One slow upstream call now becomes up to "
       "8 retries, multiplying traffic to orders (a retry storm) and pinning gateway CPU.",
       {"config rollback gateway": ("full", "Restored retries=2; the retry storm stopped."),
        "config set gateway retries=2": ("full", "Set retries back to 2."),
        "scale gateway 6": ("partial", "More gateways absorb the storm for a while, but retries keep amplifying traffic.")},
       {"restart orders": "orders was only a victim of the retries; restarting it caused errors.",
        "flush cache": "The cache was healthy; flushing it added load."},
       "Look at how much traffic orders receives compared to what users send. Who is multiplying requests?",
       effects={"gateway": {"cpu": 98, "p99": 3100, "err": 12}, "orders": {"rps": 1900, "cpu": 88, "p99": 900}},
       logs=[("gateway", "WARN", "retrying POST /api/cart upstream=orders (attempt {n}/8)", .7),
             ("orders", "WARN", "request queue depth {n} (limit 500)", .4)],
       config={"gateway": {"retries": 8}}),

    _S("crash_loop", "Orders service won't start", "API & Application", "easy", "🔁",
       "The orders service keeps restarting and orders can't be placed.",
       "CRITICAL: orders pods in CrashLoopBackOff, 0/3 ready",
       "orders v2.5.0 renamed the environment variable DATABASE_URL to DB_URL in code, but the "
       "deployment still sets DATABASE_URL. Every pod crashes on startup with a KeyError.",
       {"rollback orders": ("full", "Rolled back to v2.4.0, which reads DATABASE_URL."),
        "restart orders": ("partial", "The pods crash again a few seconds after starting.")},
       {"restart db": "The database was fine; restarting it took down every service.",
        "scale orders": "More copies of a crashing pod just crash more."},
       "When a service crashes on startup, its own logs usually say why. What changed in it recently?",
       effects={"orders": {"err": 95, "rps": 20, "cpu": 4}, "gateway": {"err": 41}},
       logs=[("orders", "ERROR", "Traceback: KeyError: 'DB_URL' (config.py line 12) - exiting", .7),
             ("orders", "WARN", "container restarted (restarts={n}), back-off 40s", .4),
             ("gateway", "ERROR", "upstream orders: no healthy endpoints", .5)],
       deploy=("orders", "v2.5.0", "4 min ago")),

    # ------------------------------------------------------------ Database
    _S("pool_exhausted", "Orders can't reach the database", "Database", "medium", "🔌",
       "Orders fail with database timeouts, but the database itself looks quiet.",
       "CRITICAL: orders error rate > 25%, 'timeout acquiring connection'",
       "A config change dropped orders 'db.pool_size' from 50 to 5. Under normal traffic every "
       "request waits for one of 5 connections and times out, while the database sits idle.",
       {"config rollback orders": ("full", "Restored the 50-connection pool."),
        "config set orders db.pool_size=50": ("full", "Raised the connection pool back to 50.")},
       {"restart db": "The database was idle and healthy; restarting it dropped every connection.",
        "scale db": "The db had plenty of capacity; the bottleneck was the client pool."},
       "The database CPU is low, yet orders can't get answers. Is the problem in the db, or in how orders connects to it?",
       effects={"orders": {"err": 28, "p99": 5000}, "db": {"rps": 180, "cpu": 12}, "gateway": {"err": 19}},
       logs=[("orders", "ERROR", "timeout acquiring connection from pool after 5000ms (5/5 in use, {n} waiting)", .7),
             ("db", "INFO", "active connections: 5 / 500", .3)],
       config={"orders": {"db.pool_size": 5}}),

    _S("deadlock", "Payments and orders deadlock", "Database", "hard", "🔒",
       "Random payments and orders fail with database errors.",
       "WARNING: deadlocks detected, payments error rate > 15%",
       "payments v1.8.4 updates the 'payments' row before the 'orders' row, while orders updates them "
       "in the opposite order. Concurrent checkouts lock each other and Postgres kills one of them.",
       {"rollback payments": ("full", "Rolled back to v1.8.3, which locks rows in the same order as orders."),
        "db kill-locks": ("partial", "Killed the stuck transactions, but new deadlocks form within a minute.")},
       {"restart db": "Restarting the db aborted every in-flight payment.",
        "rollback orders": "orders hadn't changed; payments' new lock order caused the deadlock."},
       "Deadlocks need two parties. Which of them changed recently?",
       effects={"payments": {"err": 17, "p99": 2600}, "orders": {"err": 6}, "db": {"cpu": 70}},
       logs=[("db", "ERROR", "deadlock detected: process {n} waits for ShareLock on transaction; blocked by process", .6),
             ("payments", "ERROR", "UPDATE payments ... ; UPDATE orders ... failed: deadlock detected (SQLSTATE 40P01)", .5)],
       deploy=("payments", "v1.8.4", "11 min ago")),

    _S("report_cron", "Database CPU spikes every morning", "Database", "medium", "📈",
       "The database CPU is maxed out and every page is slow.",
       "WARNING: db CPU > 95% for 10 minutes",
       "A new 'analytics-report' cron job runs a full-table aggregation over 18M orders at peak time, "
       "starving the database of CPU.",
       {"disable cron analytics-report": ("full", "Stopped the heavy report job; db CPU dropped."),
        "restart db": ("partial", "The restart killed the report, but cron will start it again.")},
       {"rollback orders": "orders hadn't changed; the load came from a scheduled job.",
        "flush cache": "Flushing the cache added even more database load."},
       "No deploy and no config change, but load appeared at a fixed time. What runs on a schedule?",
       effects={"db": {"cpu": 98, "p99": 1500}, "orders": {"p99": 2500, "err": 5}, "payments": {"p99": 1800}},
       logs=[("db", "WARN", "long-running query (pid {n}) 412s: SELECT customer_id, sum(total) FROM orders GROUP BY 1", .5),
             ("orders", "WARN", "slow db response ({n}ms)", .4)],
       cron=["analytics-report  0 9 * * *     psql -f monthly_report.sql"]),

    # ------------------------------------------------------------ Infrastructure & Cloud
    _S("memory_leak", "Payments keep crashing", "Infrastructure & Cloud", "easy", "💥",
       "The payments service keeps crashing and restarting.",
       "CRITICAL: payments pods restarting (OOMKilled) - card payments failing",
       "payments v1.9.0 caches every fraud-check response in an unbounded in-process dict. Memory "
       "grows ~3%/s until the pod is OOMKilled; each restart buys ~30s before it dies again.",
       {"rollback payments": ("full", "Rolled back to v1.8.3, which has a bounded LRU cache."),
        "restart payments": ("partial", "Restart frees memory but the leak refills it within a minute.")},
       {"restart db": "Restarting a healthy database caused a needless outage for every service.",
        "flush cache": "The shared cache was healthy; flushing it slowed every service."},
       "Watch the memory of the failing service over a minute. What changed in that service recently?",
       effects={"gateway": {"err": 9}},
       deploy=("payments", "v1.9.0", "25 min ago"),
       config={"payments": {"fraud_cache": "dict()  # unbounded"}}),

    _S("disk_full", "Database stopped accepting writes", "Infrastructure & Cloud", "medium", "💾",
       "New orders fail, but reading old orders still works.",
       "CRITICAL: db disk usage 100%, writes failing",
       "Someone set db 'slow_query_log_ms' to 0 while debugging, so every single query is logged. "
       "The log filled the disk and Postgres can't write.",
       {"config rollback db": ("full", "Restored slow_query_log_ms=500 and rotated the giant log."),
        "disk cleanup db": ("partial", "Freed space, but logging every query fills it again.")},
       {"restart db": "A database with a full disk may not come back up after a restart.",
        "scale db": "New replicas copy the same full-disk problem."},
       "Reads work but writes fail. What is the db host running out of, and what is writing so much?",
       effects={"db": {"err": 40, "mem": 70}, "orders": {"err": 31}, "gateway": {"err": 16}},
       logs=[("db", "ERROR", "could not extend file: No space left on device (disk 100%)", .6),
             ("db", "INFO", "duration: {n}.2 ms  statement: SELECT 1", .5),
             ("orders", "ERROR", "INSERT INTO orders failed: could not write to file", .4)],
       config={"db": {"slow_query_log_ms": 0}}),

    _S("cpu_regex", "Gateway CPU at 100%", "Infrastructure & Cloud", "hard", "🔥",
       "The gateway is extremely slow even though traffic is normal.",
       "CRITICAL: gateway CPU 100% at normal traffic",
       "gateway v3.2.1 added a user-agent validation regex with catastrophic backtracking (ReDoS). "
       "Certain long user-agent strings make a single request burn seconds of CPU.",
       {"rollback gateway": ("full", "Rolled back to v3.2.0 without the bad regex."),
        "scale gateway 6": ("partial", "More gateways spread the load, but each still burns CPU on the regex.")},
       {"restart orders": "orders was healthy; the gateway itself was burning CPU.",
        "restart db": "The database had nothing to do with it."},
       "Traffic is normal but CPU is not. Something in the gateway's own code got more expensive. What changed?",
       effects={"gateway": {"cpu": 100, "p99": 4800, "err": 18}},
       logs=[("gateway", "WARN", "request took {n}ms in middleware validate_user_agent", .6),
             ("gateway", "WARN", "event loop blocked for {n}ms", .4)],
       deploy=("gateway", "v3.2.1", "18 min ago")),

    _S("cache_evicted", "Cache cluster disappeared", "Infrastructure & Cloud", "easy", "☁️",
       "Every page got slow at once after a cluster maintenance.",
       "WARNING: cache has 0 ready replicas",
       "An autoscaler config change set the cache's minimum replicas to 0. During low traffic it scaled "
       "the cache to zero, so every request now hits the database directly.",
       {"scale cache 3": ("full", "Brought the cache back to 3 replicas."),
        "config rollback cache": ("full", "Restored min_replicas=3; the cache came back.")},
       {"restart db": "The db was only overloaded because the cache was gone.",
        "flush cache": "There was no cache to flush."},
       "One service on the dashboard isn't serving anything. How many copies of it are running?",
       effects={"cache": {"rps": 0, "cpu": 0, "mem": 0}, "db": {"cpu": 88, "rps": 3800, "p99": 700},
                "orders": {"p99": 2200}},
       logs=[("cache", "WARN", "deployment cache: 0/0 replicas (scaled down by autoscaler)", .5),
             ("orders", "WARN", "cache connection refused - falling back to db", .5)],
       config={"cache": {"min_replicas": 0}}),

    # ------------------------------------------------------------ Network & Security
    _S("bad_config", "Every payment times out", "Network & Security", "hard", "⏱️",
       "Every payment fails, but the payments service looks healthy.",
       "CRITICAL: 100% of payment attempts failing with upstream timeout",
       "A config push changed gateway 'payments.timeout_ms' from 5000 to 50 (typo). Payments is healthy, "
       "but the gateway gives up after 50ms, so every payment call is reported as a timeout.",
       {"config rollback gateway": ("full", "Reverted the gateway config to the previous version."),
        "config set gateway payments.timeout_ms=5000": ("full", "Restored the correct upstream timeout.")},
       {"restart payments": "Payments was never broken; restarting it dropped in-flight charges.",
        "rollback payments": "Rolled back a healthy service; the real problem was the gateway config.",
        "scale payments": "Payments had spare capacity; the timeout lives in the gateway config."},
       "Is the failing service actually unhealthy, or is someone giving up on it too early? Compare configs.",
       effects={"gateway": {"err": 21}, "payments": {"rps": 88}},
       logs=[("gateway", "ERROR", "upstream payments timeout after 50ms (POST /api/pay)", .7),
             ("payments", "INFO", "POST /charge 200 in {n}ms", .3),
             ("payments", "WARN", "client closed connection before response was written", .1)],
       config={"gateway": {"payments.timeout_ms": 50}}),

    _S("cert_expired", "Users see a security warning", "Network & Security", "easy", "🔐",
       "Browsers show 'Your connection is not private' and the apps can't connect.",
       "CRITICAL: gateway TLS handshake failures > 90%",
       "The gateway's TLS certificate for api.shop.com expired at 00:00 UTC; automatic renewal had "
       "been failing silently for 3 weeks.",
       {"cert renew gateway": ("full", "Issued and installed a fresh certificate.")},
       {"restart gateway": "A restart reloads the same expired certificate.",
        "rollback gateway": "The gateway code was fine; the certificate expired."},
       "Requests fail before they even reach the application. What happens at the very start of an HTTPS connection?",
       effects={"gateway": {"err": 92, "rps": 60}, "orders": {"rps": 20}, "payments": {"rps": 8}},
       logs=[("gateway", "ERROR", "TLS handshake error: x509: certificate has expired (CN=api.shop.com, notAfter=00:00 UTC)", .7),
             ("gateway", "WARN", "cert-renewer: ACME challenge failed (attempt {n})", .2)]),

    _S("dns_record", "Orders can't find payments", "Network & Security", "medium", "🧭",
       "Checkout fails at the payment step with connection errors.",
       "CRITICAL: orders -> payments calls failing 100%",
       "A DNS change 12 min ago pointed payments.internal at a decommissioned IP (10.0.9.14). Orders "
       "connects to a host that no longer exists.",
       {"dns rollback": ("full", "Restored the previous DNS record for payments.internal.")},
       {"restart payments": "payments was healthy; nobody could reach it.",
        "rollback orders": "orders hadn't changed; the DNS record had."},
       "payments looks healthy, but orders can't reach it. How does orders find payments' address?",
       effects={"orders": {"err": 33}, "payments": {"rps": 4}, "gateway": {"err": 22}},
       logs=[("orders", "ERROR", "dial tcp 10.0.9.14:443: connect: no route to host (payments.internal)", .7),
             ("orders", "INFO", "resolved payments.internal -> 10.0.9.14 (ttl 300)", .3)]),

    _S("rate_limit", "Customers get 'Too many requests'", "Network & Security", "medium", "🚦",
       "During a big sale, many customers get rejected with HTTP 429.",
       "WARNING: gateway 429 responses > 20% during flash sale",
       "A flash sale doubled traffic to ~2400 req/s, but the gateway's rate limit is 2000 req/s, so "
       "real customers are rejected as if they were abusive.",
       {"config set gateway rate_limit_rps=5000": ("full", "Raised the rate limit for the sale."),
        "scale gateway 6": ("partial", "More gateways help latency, but the global limit still rejects users.")},
       {"restart gateway": "Restarting dropped every in-flight request during peak sales.",
        "restart db": "The database was healthy."},
       "The errors are a specific HTTP status. Who decides to send it, and with what limit?",
       effects={"gateway": {"rps": 2400, "err": 21}},
       logs=[("gateway", "WARN", "429 Too Many Requests: global limit 2000 rps exceeded ({n} rps)", .7)]),

    _S("db_failover", "Everything got 200ms slower", "Network & Security", "hard", "🐌",
       "No errors, but every page is noticeably slower since this morning.",
       "WARNING: p99 latency +200ms on all services",
       "An automatic failover moved the database primary to the standby in another region "
       "(eu-west -> us-east). Every query now crosses an ocean.",
       {"failover db": ("full", "Moved the primary back to the local region.")},
       {"restart db": "A restart triggered yet another failover.",
        "flush cache": "The cache was hiding some latency; flushing it made things worse."},
       "No errors and normal CPU, yet every request is slower by the same amount. Where does the database live now?",
       effects={"db": {"p99": 210}, "orders": {"p99": 1900}, "payments": {"p99": 1700}, "gateway": {"p99": 2100}},
       logs=[("db", "INFO", "primary is db-standby-us-east-1 (promoted after health-check failure)", .3),
             ("orders", "WARN", "db round-trip {n}ms (expected < 5ms)", .5)]),

    # ------------------------------------------------------------ Payments & Microservices
    _S("cache_stampede", "Whole site is slow", "Payments & Microservices", "medium", "🌊",
       "Every page is slow and the database is overloaded.",
       "WARNING: p99 latency > 3s on all endpoints, db connections at 98%",
       "A cron job ran 'FLUSHALL' on the cache at 02:58. With a cold cache every request goes to the "
       "db; db connections saturate and every service slows down (a cache stampede).",
       {"cache warm": ("full", "Warmed the hot keys; the db load fell back to normal."),
        "disable cron cache-cleanup": ("partial", "Stopped the job from repeating, but the cache is still cold.")},
       {"restart db": "Restarting the db dropped all connections and made the stampede worse.",
        "rollback orders": "orders' latest deploy was days old and unrelated."},
       "The database is drowning. Why would traffic suddenly stop being absorbed upstream? Check what runs on a schedule.",
       effects={"cache": {"rps": 300}, "db": {"cpu": 91, "rps": 4100, "p99": 900},
                "orders": {"p99": 3400, "err": 4}, "payments": {"p99": 3400, "err": 4},
                "gateway": {"p99": 3400, "err": 4}},
       logs=[("cache", "INFO", "keyspace hits=0.{n}% misses high", .5),
             ("db", "WARN", "remaining connection slots are reserved (connections 491/500)", .5),
             ("orders", "WARN", "cache MISS product:* - falling back to db", .4),
             ("cache", "INFO", "cron[cache-cleanup] executed FLUSHALL at 02:58 (schedule: 58 2 * * *)", .05)]),

    _S("provider_down", "Card payments are failing", "Payments & Microservices", "medium", "💳",
       "Card payments fail, though our own services look fine.",
       "CRITICAL: payment authorisations failing > 60%",
       "The external card provider PayFast is having an outage and returns HTTP 503. Our payments "
       "service is healthy; it just has no working provider configured.",
       {"failover payments": ("full", "Switched card payments to the backup provider.")},
       {"rollback payments": "Our payments code was fine; the external provider was down.",
        "restart payments": "Restarting didn't fix an external outage and dropped live charges."},
       "Our services look healthy. Read the payment errors carefully: whose server is returning them?",
       effects={"payments": {"err": 63, "p99": 3000}, "gateway": {"err": 15}},
       logs=[("payments", "ERROR", "PayFast API 503 Service Unavailable (POST /v2/authorize, request {n})", .7),
             ("payments", "INFO", "backup provider 'CardHub' configured but not active", .2)]),

    _S("queue_backlog", "Order confirmations are hours late", "Payments & Microservices", "medium", "📬",
       "Customers pay but never get a confirmation email.",
       "WARNING: order-events queue depth > 1,000,000",
       "The order-events queue consumers were scaled to 1 by mistake during last night's cost cleanup. "
       "Messages pile up faster than one consumer can process them.",
       {"queue scale 10": ("full", "Scaled consumers to 10; the backlog drains."),
        "queue scale 20": ("full", "Scaled consumers to 20; the backlog drains quickly.")},
       {"restart orders": "Restarting the producer doesn't drain the queue.",
        "restart db": "The database wasn't the bottleneck."},
       "Messages go in, but are they coming out fast enough? How many workers read the queue?",
       effects={"orders": {"p99": 1900, "mem": 94}, "db": {"cpu": 55}},
       logs=[("orders", "WARN", "order-events queue depth {n}000 (consumers=1)", .6),
             ("orders", "INFO", "published OrderPaid event", .4)]),

    _S("auth_keys", "Everyone got logged out", "Payments & Microservices", "hard", "🔑",
       "All users are suddenly logged out and can't log back in.",
       "CRITICAL: gateway 401 Unauthorized > 60%",
       "A key rotation changed the gateway's 'jwt.key_id' to k2 before the auth service started signing "
       "tokens with k2. Every token signed with k1 is now rejected as invalid.",
       {"config rollback gateway": ("full", "Restored jwt.key_id=k1 so existing tokens are valid again."),
        "config set gateway jwt.key_id=k1": ("full", "Pointed the gateway back at the active signing key.")},
       {"restart gateway": "A restart reloads the same wrong key.",
        "flush cache": "Flushing the cache also wiped every user's session."},
       "Logins fail with 401 for everyone at once. What does the gateway use to check a token, and did it change?",
       effects={"gateway": {"err": 64}, "orders": {"rps": 60}, "payments": {"rps": 20}},
       logs=[("gateway", "ERROR", "JWT verification failed: unknown key id 'k1' (expected 'k2')", .7),
             ("gateway", "INFO", "key rotation: jwt.key_id set to k2 (OPS-2310)", .1)],
       config={"gateway": {"jwt.key_id": "k2"}}),

    _S("dependency_fail", "Product pages are broken", "Payments & Microservices", "easy", "🧩",
       "Product pages error out, but checkout works.",
       "CRITICAL: orders /products errors > 40%",
       "The recommendations service that product pages call was shut down in a cleanup, but the "
       "'feature.recommendations' flag in orders is still on, so every product page call fails.",
       {"config set orders feature.recommendations=false": ("full", "Turned off the dead dependency."),
        "config rollback orders": ("full", "Restored the config without the recommendations call.")},
       {"restart orders": "Restarting orders kept calling the dead service.",
        "rollback orders": "The code was fine; a flag still pointed at a removed service."},
       "Only one page type fails. What does that page call that checkout doesn't?",
       effects={"orders": {"err": 42}, "gateway": {"err": 17}},
       logs=[("orders", "ERROR", "GET http://recommendations.internal/v1/similar: connection refused", .7),
             ("orders", "INFO", "feature.recommendations=on", .2)],
       config={"orders": {"feature.recommendations": True}}),
]

SCENARIOS = {s.id: s for s in SCENARIOS_LIST}
