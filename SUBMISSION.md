# Submission draft: OnCall Dojo

## Category
Best Apps and Agents

## Project description

**What we created:** OnCall Dojo is a flight simulator for production outages. It pages
you, breaks a live (simulated) production system, and puts you in a war room with
AI colleagues. You investigate with real logs, metrics, deploy history and config
diffs, fix the outage, and get a scored, blameless post-incident review.

**Why we created it:** Engineers usually learn incident response during their first
real outage, at 3 a.m., with customers losing money and a manager asking for an ETA.
Pilots, surgeons and firefighters all train in simulation before the real thing.
On-call engineers don't. Chaos-engineering tools break systems, but none of them
train the person who has to fix them.

**How it works:**
- A simulator (`sim.py`) runs a 5-service stack (gateway, orders, payments, db, cache)
  with live metrics, noisy logs, configs, deploy history and cron jobs. Four outage
  scenarios: a slow query from a fresh deploy, a memory leak, a one-character config
  typo, and a cache stampede. Wrong actions have visible side effects.
- Three Nemotron models on **Nebius Token Factory**, each picked for its job:
  - **Nemotron Nano:** a stressed manager and a frantic support agent message the
    trainee every ~40s and react to their status updates. These calls are frequent
    and must be fast and cheap.
  - **Nemotron Super:** the coach. It reads the hidden root cause and the trainee's
    commands, then gives a Socratic hint without revealing the fix.
  - **Nemotron Ultra:** writes the post-incident review by reasoning over the full
    timeline of commands, messages and mistakes.
- Scoring covers time to resolve, harmful actions, hints, communication, and whether
  the trainee investigated before changing anything.
- Deployed as one container on **Nebius Serverless Endpoints**.

## Links
- Demo: TODO (Nebius Serverless Endpoint URL)
- Video: TODO (YouTube, public, 3 min or less)
- Repo: TODO (GitHub, MIT)

## Feedback on Nebius and NVIDIA tools
TODO after using them for real. Note honestly: setup speed, model latency
(Nano vs Ultra), the OpenAI-compatible API, docs, and the deploy experience.

## Updated during the submission period?
New project, built entirely during the submission period.

---

# Demo video script (about 2:50)

| Time | Show on screen | Say |
|---|---|---|
| 0:00-0:15 | Black screen, then the pager goes off | "It's 3 a.m. Your phone screams. Checkout is down. It's your first on-call shift. Nobody trains you for this, until now." |
| 0:15-0:30 | Landing page | "OnCall Dojo is a flight simulator for production outages, powered by NVIDIA Nemotron on Nebius Token Factory." |
| 0:30-1:20 | Acknowledge the page, run `status`, `logs db`, `deploys`; red dashboards | "A real-looking production stack is breaking. I have a terminal, logs, metrics, deploys. The logs are noisy, like in real life." |
| 1:20-1:45 | Manager messages pop in; type a status update; the manager replies | "My manager is panicking. That's Nemotron Nano: fast, cheap role-play that reacts to what I actually say." |
| 1:45-2:00 | Click Hint | "Stuck? The coach, Nemotron Super, knows the root cause but only nudges me." |
| 2:00-2:20 | Run the fix; charts turn green; RESOLVED | "Rolled back the bad deploy. Resolved." |
| 2:20-2:45 | Review screen: grade, review, model usage panel | "Then Nemotron Ultra reasons over my whole timeline and writes a blameless post-incident review. Nano for speed, Super for coaching, Ultra for deep reasoning, all on Nebius." |
| 2:45-2:50 | Logo + repo URL | "OnCall Dojo. Break things safely. Open source, MIT." |
