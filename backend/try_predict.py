"""Live check of the Change Risk Radar against the real Nemotron model."""
import json
import time

from fastapi.testclient import TestClient

from app import app

c = TestClient(app)
for change in ["Lowering the orders service database connection pool from 50 to 10 to save memory",
               "Rotating the JWT signing key on the gateway to k2 tonight",
               "Fixing a typo in the README"]:
    t0 = time.time()
    r = c.post("/api/predict", json={"change": change}).json()
    print(f"\n[{time.time() - t0:.1f}s] {change}\n" + json.dumps(
        {k: r[k] for k in ("risk", "summary", "source")} |
        {"predictions": [(p["scenario_id"], p["why"]) for p in r["predictions"]]}, indent=1))
