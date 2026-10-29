"""Quick live check: one call to each Nemotron tier."""
import time

import llm

for tier in ("nano", "super", "ultra"):
    t0 = time.time()
    out = llm.chat(tier, "Answer in one short sentence.", "What does an on-call engineer do?",
                   max_tokens=400, fallback="<<FALLBACK>>")
    print(f"{tier:6} {time.time() - t0:5.1f}s  {out[:160]!r}")
print(llm.usage)
