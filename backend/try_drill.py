"""Live end-to-end drill against the real Nemotron models (prints the AI output)."""
import time

from fastapi.testclient import TestClient

import llm
from app import app

c = TestClient(app)
H = {"X-Session": "live"}
c.post("/api/incident", json={"scenario": "slow_query"}, headers=H)
for cmd in ("status", "logs db"):
    c.post("/api/cmd", json={"cmd": cmd}, headers=H)
print("HINT:", c.post("/api/hint", headers=H).json()["hint"])
c.post("/api/chat", json={"text": "Looking at the db, seems like a slow query. Update in 5 min."}, headers=H)
c.post("/api/cmd", json={"cmd": "deploys orders"}, headers=H)
c.post("/api/cmd", json={"cmd": "rollback orders"}, headers=H)
time.sleep(6)  # let the threaded Nano replies land
for m in c.get("/api/state", headers=H).json()["chat"]:
    print(f"CHAT {m['who']}: {m['text']}")
r = c.post("/api/end", headers=H).json()
print("SCORE", r["score"], r["grade"])
print(r["review"])
print(llm.usage)
