"""Nemotron model router on Nebius Token Factory (OpenAI-compatible API).

Three tiers, each matched to the job:
  nano  -> stakeholder role-play (fast, cheap, called often)
  super -> the coach: reads the trainee's commands and gives a Socratic hint
  ultra -> the post-incident review: reasons over the whole incident timeline

If NEBIUS_API_KEY is not set, every call falls back to scripted text so the
dojo still runs offline (the UI shows "offline mode").
"""
from __future__ import annotations

import os
import time

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.us-central1.nebius.com/v1/")
MODELS = {
    "nano": os.getenv("MODEL_NANO", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"),
    "super": os.getenv("MODEL_SUPER", "nvidia/nemotron-3-super-120b-a12b"),
    "ultra": os.getenv("MODEL_ULTRA", "nvidia/Nemotron-3-Ultra-550b-a55b"),
}

_client = None
usage = {tier: {"calls": 0, "tokens": 0, "ms": 0} for tier in MODELS}


def online() -> bool:
    return bool(os.getenv("NEBIUS_API_KEY")) and OpenAI is not None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(base_url=BASE_URL, api_key=os.getenv("NEBIUS_API_KEY"))
    return _client


# Hard safety cap: Token Factory has no spending limit, so the app enforces one.
# Once this many tokens have been used in total, every call falls back to scripted text.
TOKEN_BUDGET = int(os.getenv("TOKEN_BUDGET", "300000"))


def chat(tier: str, system: str, user: str, max_tokens: int = 300, fallback: str = "") -> str:
    if not online():
        return fallback
    if sum(u["tokens"] for u in usage.values()) >= TOKEN_BUDGET:
        print("[llm] token budget reached - using offline fallback")
        return fallback
    t0 = time.time()
    try:
        r = _get_client().chat.completions.create(
            model=MODELS[tier],
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0.7 if tier == "nano" else 0.4,
            # Nano (chat lines) and Super (one hint) must answer fast: skip the reasoning
            # pass. Ultra keeps it for the post-incident review.
            extra_body={"chat_template_kwargs": {"enable_thinking": False}} if tier != "ultra" else None,
        )
        text = (r.choices[0].message.content or "").strip()
        # reasoning models may wrap their thinking; keep only the answer
        if "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        u = usage[tier]
        u["calls"] += 1
        u["tokens"] += getattr(r.usage, "total_tokens", 0) or 0
        u["ms"] += int((time.time() - t0) * 1000)
        return text or fallback
    except Exception as e:  # network/model errors must never break a drill
        print(f"[llm:{tier}] {e}")
        return fallback


def usage_report() -> dict:
    return {"online": online(), "models": MODELS, "usage": usage}
