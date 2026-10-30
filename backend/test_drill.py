"""End-to-end smoke test: every scenario can be investigated, fixed and graded."""
from fastapi.testclient import TestClient

from app import app
from scenarios import CATEGORIES
from sim import SCENARIOS

c = TestClient(app)
H = {"X-Session": "test"}


def any_degraded(state):
    for h in state["history"].values():
        if h["err"][-1] > 5 or h["p99"][-1] > 1500 or h["cpu"][-1] > 90 or h["mem"][-1] > 90:
            return True
    return False


def test_all_scenarios_resolve():
    for sid, sc in SCENARIOS.items():
        assert sc.category in CATEGORIES, sid
        c.post("/api/incident", json={"scenario": sid}, headers=H)
        s = c.get("/api/state", headers=H).json()
        assert s["healthy"] is False and any_degraded(s), f"{sid}: nothing looks broken"
        for cmd in ("status", "logs db", "deploys", "config diff gateway", "crontab"):
            assert c.post("/api/cmd", json={"cmd": cmd}, headers=H).json()["output"]
        c.post("/api/chat", json={"text": "Investigating, update in 5 min"}, headers=H)
        fix = next(k for k, (kind, _) in sc.fixes.items() if kind == "full")
        out = c.post("/api/cmd", json={"cmd": fix}, headers=H).json()["output"]
        assert "command not found" not in out, (sid, fix)
        s = c.get("/api/state", headers=H).json()
        assert s["resolved"] and s["healthy"], sid
        r = c.post("/api/end", headers=H).json()
        assert r["score"] >= 90 and r["review"], (sid, r)


def test_every_fix_and_harm_command_is_known():
    from sim import HANDLERS
    for sc in SCENARIOS.values():
        for cmd in list(sc.fixes) + list(sc.harmful):
            assert cmd.split()[0] in HANDLERS, (sc.id, cmd)


def test_card_data_hides_root_cause():
    for card in c.get("/api/scenarios").json():
        assert set(card) == {"id", "title", "difficulty", "category", "icon", "description", "duration"}


def test_harmful_action_is_penalised():
    c.post("/api/incident", json={"scenario": "bad_config"}, headers=H)
    c.post("/api/cmd", json={"cmd": "restart payments"}, headers=H)
    r = c.post("/api/end", headers=H).json()
    assert r["score"] < 50


def test_hint_works_offline():
    c.post("/api/incident", json={"scenario": "slow_query"}, headers=H)
    assert c.post("/api/hint", headers=H).json()["hint"]


if __name__ == "__main__":
    test_all_scenarios_resolve(); test_every_fix_and_harm_command_is_known()
    test_card_data_hides_root_cause(); test_harmful_action_is_penalised(); test_hint_works_offline()
    print(f"all {len(SCENARIOS)} scenarios pass")
