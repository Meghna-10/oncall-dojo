"""End-to-end smoke test: every scenario can be investigated, fixed and graded."""
from fastapi.testclient import TestClient

from app import app
from sim import SCENARIOS

c = TestClient(app)
H = {"X-Session": "test"}


def test_all_scenarios_resolve():
    for sid, sc in SCENARIOS.items():
        c.post("/api/incident", json={"scenario": sid}, headers=H)
        assert c.get("/api/state", headers=H).json()["healthy"] is False
        for cmd in ("status", "logs db", "deploys", "config diff gateway", "crontab"):
            assert c.post("/api/cmd", json={"cmd": cmd}, headers=H).json()["output"]
        c.post("/api/chat", json={"text": "Investigating, update in 5 min"}, headers=H)
        fix = next(k for k, (kind, _) in sc.fixes.items() if kind == "full")
        c.post("/api/cmd", json={"cmd": fix}, headers=H)
        s = c.get("/api/state", headers=H).json()
        assert s["resolved"] and s["healthy"], sid
        r = c.post("/api/end", headers=H).json()
        assert r["score"] >= 90 and r["review"], (sid, r)


def test_harmful_action_is_penalised():
    c.post("/api/incident", json={"scenario": "bad_config"}, headers=H)
    c.post("/api/cmd", json={"cmd": "restart payments"}, headers=H)
    r = c.post("/api/end", headers=H).json()
    assert r["score"] < 50


def test_hint_works_offline():
    c.post("/api/incident", json={"scenario": "slow_query"}, headers=H)
    assert c.post("/api/hint", headers=H).json()["hint"]


if __name__ == "__main__":
    test_all_scenarios_resolve(); test_harmful_action_is_penalised(); test_hint_works_offline()
    print("all drills pass")
