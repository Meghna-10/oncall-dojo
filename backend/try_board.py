"""Live check: evidence graph + Nemotron multi-hypothesis analysis + verified recovery."""
import json
import time

from fastapi.testclient import TestClient

from app import app

c = TestClient(app)
H = {"X-Session": "board"}
c.post("/api/incident", json={"scenario": "pool_exhausted"}, headers=H)
print("before any command:", c.get("/api/evidence", headers=H).json()["items"])
for cmd in ("status", "logs orders", "logs db", "deploys", "config diff orders"):
    c.post("/api/cmd", json={"cmd": cmd}, headers=H)
ev = c.get("/api/evidence", headers=H).json()
print("evidence:", [(i["kind"], i["svc"], i["label"]) for i in ev["items"]])
t0 = time.time()
r = c.post("/api/hypotheses", headers=H).json()
print(f"\n[{time.time() - t0:.1f}s] source={r['source']}")
for h in r["hypotheses"]:
    print(json.dumps(h, indent=1))
c.post("/api/cmd", json={"cmd": "config rollback orders"}, headers=H)
time.sleep(6)
end = c.post("/api/end", headers=H).json()
print("\nrecovery:", end["recovery"]["verified"], [(s["svc"], s["err_peak"], s["err_now"]) for s in end["recovery"]["services"]])
print("score:", end["score"], end["breakdown"])
