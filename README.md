# 🚨 OnCall Dojo: a flight simulator for production outages

> Practise your first 3 a.m. incident before it happens for real.

**▶ Live demo: https://oncall-dojo.onrender.com** (free hosting: the first visit may take ~1 min to wake up)

**Track:** Best Apps and Agents · **License:** MIT · **Built during the hackathon submission period** (new project, no prior code)

New engineers usually learn incident response on a real outage, with real customers
losing money and a manager asking for an ETA. Pilots train in simulators first.
OnCall Dojo gives engineers the same kind of practice.

## What it does

1. **You get paged.** A live (simulated) production stack of `gateway`, `orders`,
   `payments`, `db` and `cache` breaks in one of **21 realistic ways** across 5
   categories (API & Application, Database, Infrastructure & Cloud, Network & Security,
   Payments & Microservices): slow queries, memory leaks, config typos, expired TLS
   certificates, DNS mistakes, deadlocks, full disks, retry storms, provider outages,
   queue backlogs and more. Each one has its own metrics, logs, clues, fix and scoring,
   defined as data in `backend/scenarios.py`, so adding a new incident needs no engine code.
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

### Investigation board: evidence graph + multi-hypothesis AI

During a drill, the investigation board draws the 5 services and links each clue **you
have found** (error log lines, recent deploys, config changes, scheduled jobs) to the
service it concerns. Clues you haven't discovered stay hidden, so the board organises
your investigation instead of solving it. **Analyse my evidence** asks Nemotron 3 Super for
2–3 competing root-cause hypotheses, each with a confidence, evidence for and against,
and the one command that would confirm or refute it. It never gives the fix, and each
analysis costs 3 points (`GET /api/evidence`, `POST /api/hypotheses`).

### Verified recovery

The report doesn't take "resolved" on trust. For every service it compares the worst
error rate and p99 latency while the incident was live with the average of the last 5
seconds, and it only marks recovery as verified if every service is healthy.

### Change Risk Radar: predict the outage before you ship

Describe a change you're about to make, for example *"rotating the gateway's JWT key to
k2 tonight"*. Nemotron 3 Super runs a pre-mortem against the incident library and returns
a risk level, the outages the change could cause, early warning signs to watch and a
safeguard. Each prediction has a **Practise this outage** button that starts that exact
drill. Predictions are limited to real scenarios in the library (unknown ids are
discarded) and are labelled as an AI estimate. If the AI is unavailable, the Radar falls
back to keyword matching and says so (`POST /api/predict`).

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

### Where Token Factory accelerated our workflow

- **One API, three model sizes.** Switching between Nano, Super and Ultra is just a
  different `model` string on the same OpenAI-compatible endpoint, so we could try each
  job on each tier in minutes and pick the right size for it.
- **No GPUs to manage.** A 550B-parameter Ultra model was one HTTPS call away; we
  spent our time on the simulator and the prompts, not on serving.
- **Fast enough to feel live.** Measured on our account: short replies took about
  0.6-2s across all three tiers, and Ultra's full post-incident review (thinking on)
  about 8s, quick enough for the chat to feel real.
- **Cheap.** A full drill (about 5 calls, ~2,000 tokens) costs about a cent, so testing
  every scenario end to end against the live models was practical.

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
`python test_outage.py` checks that a drill still finishes quickly when the API is
unreachable.

### Deploy

The live demo runs on Render's free tier from this repo's `Dockerfile`, a single
container (API + UI) that listens on `$PORT` (default 8000). The same image can run on
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

**What worked well**
- The OpenAI-compatible API meant zero new SDKs: the standard `openai` Python client
  worked once we changed `base_url`.
- `GET /v1/models` made it easy to confirm exactly which Nemotron 3 models our account
  could use.
- Having Nano, Super and Ultra side by side made "right model for the right job" a real
  design choice instead of a compromise.
- Latency was consistently low, even for Ultra.

**What tripped us up**
- **Reasoning output can come back empty.** With thinking on, Nemotron 3 Nano spent its
  whole `max_tokens` budget reasoning and returned no answer text. Turning it off with
  `chat_template_kwargs: {"enable_thinking": false}` fixed it. A note in the docs about
  sizing `max_tokens` for thinking mode would save people time.
- **Onboarding from India was hard.** Stripe rejected our first card ("card type isn't
  accepted"). A card is mandatory even when you only use promo credits, and several
  participants on Discord hit the same wall. A card-free path for hackathon credits would
  help a lot.
- **No hard spending cap.** Since the card can be charged once credits run out, we built
  our own token budget into the app. A per-key or per-project spend limit would make
  hackathon users more comfortable.
- **Finding the endpoint.** The dashboard shows a region-specific base URL
  (`api.tokenfactory.us-central1.nebius.com`), which took a moment to match up with the
  docs.
- **Promo-code flow.** The activation code is entered in a separate form, and the real
  promo code arrives by email. We first typed the activation code straight into the
  top-up dialog, which was rejected as invalid.

**Built during the hackathon:** OnCall Dojo is a new project, created entirely during
the submission period.
