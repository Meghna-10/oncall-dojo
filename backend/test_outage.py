"""If the Nebius API is unreachable, a drill must still finish quickly (fallback text)."""
import os
import time

os.environ["NEBIUS_API_KEY"] = "dummy"
os.environ["NEBIUS_BASE_URL"] = "http://127.0.0.1:9/v1/"  # nothing listens here

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

c = TestClient(app)
H = {"X-Session": "outage"}
c.post("/api/incident", json={"scenario": "memory_leak"}, headers=H)
t0 = time.time()
hint = c.post("/api/hint", headers=H).json()["hint"]
c.post("/api/cmd", json={"cmd": "rollback payments"}, headers=H)
r = c.post("/api/end", headers=H).json()
took = time.time() - t0
assert hint and r["review"] and took < 10, took
assert c.get("/api/state", headers={"X-Session": "gone"}).status_code == 404
# Risk Radar falls back to keyword matching, says so, and never invents scenario ids
r = c.post("/api/predict", json={"change": "lowering the orders db pool_size to 5"}).json()
assert r["source"] == "keyword-fallback" and r["predictions"], r
assert all(p["scenario_id"] in __import__("sim").SCENARIOS for p in r["predictions"])
assert c.post("/api/predict", json={"change": "hi"}).status_code == 400
print(f"API down: hint + review fell back in {took:.1f}s; unknown session -> 404")
