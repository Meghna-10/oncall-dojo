# 🚨 OnCall Dojo: a flight simulator for production outages

> Practise your first 3 a.m. incident before it happens for real.

**Track:** Best Apps and Agents · **License:** MIT · **Built during the hackathon submission period** (new project, no prior code)

New engineers usually learn incident response on a real outage, with real customers
losing money and a manager asking for an ETA. Pilots train in simulators first.
OnCall Dojo gives engineers the same kind of practice.

## What it does

1. **You get paged.** A live (simulated) production stack of `gateway`, `orders`,
   `payments`, `db` and `cache` breaks in a realistic way: a slow query from a fresh
   deploy, a memory leak, a one-character config typo, or a cache stampede.
2. **You investigate in a real terminal.** You have logs, metrics, deploy history,
   config diffs and crontab. There are red herrings in the logs, just like real life.
3. **People ping you.** A stressed engineering manager and a frantic support agent
   message you in the war room. Both are played by **Nemotron Nano**, and they react to
   what you actually tell them.
4. **A coach is there if you're stuck.** **Nemotron Super** reads the commands you've
   tried and gives a Socratic hint. It never gives away the answer.
5. **You fix it, or make it worse.** Harmful actions, like restarting a healthy
   database, have visible side effects and cost points.
6. **You get a blameless post-incident review.** **Nemotron Ultra** reasons over your
   whole timeline and writes what went well, what to improve, and what to drill next.

## How NVIDIA Nemotron and Nebius Token Factory are used

| Model (via Token Factory) | Job | Why this tier |
|---|---|---|
| **Nemotron 3 Nano** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`) | Manager and customer role-play | Called every ~40s; must be fast and cheap (~2s, thinking off) |
| **Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b`) | Coach hints | Weighs the hidden root cause against the trainee's commands (~1-2s) |
| **Nemotron 3 Ultra** (`nvidia/Nemotron-3-Ultra-550b-a55b`) | Post-incident review | Reasons (thinking on) over the full incident timeline (~8s) |

A built-in token budget (`TOKEN_BUDGET`, default 300k tokens) stops the app from
calling the API after that point. Token Factory itself has no hard spending cap.

All calls go through Nebius Token Factory's OpenAI-compatible API (`backend/llm.py`).
The review screen shows exactly how many calls and tokens each model used.
Model IDs can be changed with environment variables.

## Run it

```bash
cd backend
pip install -r requirements.txt
export NEBIUS_API_KEY=...            # from Nebius Token Factory (optional: runs offline without it)
uvicorn app:app --port 8000
# open http://localhost:8000
```

Optional overrides: `NEBIUS_BASE_URL`, `MODEL_NANO`, `MODEL_SUPER`, `MODEL_ULTRA`.

Tests: `cd backend && python test_drill.py` checks that every scenario can be
investigated, fixed and graded, and that harmful actions are penalised.

### Deploy

`Dockerfile` builds a single container (API + UI) on port 8000. It is ready for
Nebius Serverless Endpoints:

```bash
docker build -t oncall-dojo .
docker run -p 8000:8000 -e NEBIUS_API_KEY=... oncall-dojo
```

## Architecture

```
browser (vanilla JS)  ──►  FastAPI  ──►  sim.py   simulated prod stack: metrics, logs, configs, deploys
                                    └──►  llm.py   Nemotron Nano / Super / Ultra router on Token Factory
```

## Scoring

The score starts at 100. Points come off for: not resolving the incident, slow
resolution, harmful actions, hints used, never posting a status update, and changing
things before investigating. Grades run S / A / B / C / D.

## Roadmap

Nemotron-generated scenarios ("describe your stack and get a custom outage"),
team drills, and replaying real postmortems as drills.

## Feedback on Nebius and NVIDIA tools

_To be filled in after the build._
