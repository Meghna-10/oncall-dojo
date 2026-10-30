"""Live check of the AI Shadow Engineer + decision quality on a run with detours."""
import json
import time

from fastapi.testclient import TestClient

from app import app

c = TestClient(app)
H = {"X-Session": "shadow"}
c.post("/api/incident", json={"scenario": "slow_query"}, headers=H)
for cmd, wait in [("status", 2), ("logs payments", 3), ("logs cache", 3), ("logs db", 3), ("deploys", 4)]:
    c.post("/api/cmd", json={"cmd": cmd}, headers=H); time.sleep(wait)
c.post("/api/chat", json={"text": "Looking at a slow query"}, headers=H)
c.post("/api/cmd", json={"cmd": "rollback orders"}, headers=H)
t0 = time.time()
r = c.post("/api/end", headers=H).json()
print(f"end took {time.time() - t0:.1f}s")
print(json.dumps(r["shadow"], indent=1))
