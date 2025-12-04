# ADAAD-Free — Public Aponi Dashboard

This repository contains the ADAAD-Free public interface:
a safe, offline dashboard and minimal API that demonstrates the Aponi UI without exposing ADAAD’s proprietary engine, agents, Cryovant registry, mutation logic, or internal logs.

All endpoints are read-only and serve deterministic demo JSON from `data/` with no writes or side effects.

## Features
- Fully local Starlette backend (Termux/Android compatible)
- Aponi dashboard UI (HTML/CSS/JS)
- Demo health, metrics, and agent listings
- No write endpoints, no mutation, no execution

## Run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --no-cache-dir -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000

Open in browser:

http://127.0.0.1:8000

API Endpoints (Read-Only)

/health

/metrics

/agents


These return demo JSON from data/.

Upgrade Path

Aponi can connect to a private ADAAD backend using:

ADAAD_BACKEND_URL=http://your-private-adaad:5001

No UI changes required.
