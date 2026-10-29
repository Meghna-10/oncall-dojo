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
print(f"API down: hint + review fell back in {took:.1f}s; unknown session -> 404")
