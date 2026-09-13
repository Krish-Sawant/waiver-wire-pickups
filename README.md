# Fantasy Football Waiver Helper

Rank the best waiver-wire pickups in your [Sleeper](https://sleeper.com) fantasy
football leagues using real nflverse data — snap share, target/opportunity
share, and volume — with injury, roster, team, and depth-chart awareness so it
never recommends a player who's hurt, cut, or buried on the bench.

A FastAPI + nflverse backend, a React + TypeScript frontend, and optional
Gemini-powered analysis (add/drop outlooks, a waiver-assistant chat, and
head-to-head player comparisons).

---

## Features

- **Opportunity-based ranking** — players scored on snap %, target/opportunity
  share, and per-game volume (carries + targets), percentile-normalized within
  position group. Current-season stats are weighted more heavily than last
  season. QBs use a fantasy-points model instead of usage share.
- **Only real, available players** — filters out players not on a current NFL
  roster, players who are Out/Inactive (using current-season injury data as
  authoritative), and players buried on the depth chart.
- **Sleeper integration** — link your Sleeper username, pick a league, and see
  your roster and the waiver board for that league.
- **Player detail cards** — headshot, position, current team, per-season game
  logs (2025 / 2026 tabs), and the underlying pickup metrics.
- **Search + position filter + shortlist** on the waiver board.
- **Gemini analysis (optional)** — a startup waiver report + chat assistant, an
  add/drop "Fantasy Outlook," and any-vs-any player comparisons.
- **Accounts** — email/password signup with Argon2-hashed passwords and JWT
  session tokens; every page is behind the login gate. Each account links its
  own Sleeper username (stored per-user in SQLite).

The ranking components were validated with **walk-forward backtests** before
being trusted — the weights aren't guesses.

---

## Tech stack

| Layer      | Tech |
|------------|------|
| Data       | [nflreadpy](https://github.com/nflverse/nflreadpy) (nflverse), [polars](https://pola.rs) |
| Backend    | FastAPI + uvicorn, SQLite (users), Argon2 + JWT (auth) |
| Frontend   | React + TypeScript + Vite |
| League data| Sleeper public API |
| AI (opt.)  | Google Gemini (`google-genai`) |

---

## Project layout

```
waiverwire/        Python package (data, ranking, API, auth)
  nfl.py           nflverse data layer (stats, injuries, rosters, depth, teams)
  ranking.py       opportunity_score — the core ranking model
  sleeper.py       Sleeper API helpers (leagues, rosters)
  waiver.py        combine ranking + league rosters -> available players
  api.py           FastAPI app (all endpoints)
  auth.py          Argon2 hashing + JWT tokens + the require_auth gate
  users.py         SQLite user store (accounts + linked Sleeper username)
frontend/          React + TypeScript + Vite app
deploy/            systemd unit + nginx snippet for the server
tests/             tests
DEPLOY.md          step-by-step AWS deploy runbook (EC2 + S3/CloudFront)
```

---

## Local development

### Prerequisites
- Python 3.11+
- Node.js 18+
- A [Gemini API key](https://aistudio.google.com/apikey) (optional — only the AI
  features need it)

### 1. Backend
```bash
python3 -m venv venv
./venv/bin/pip install -e .
cp .env.example .env      # then fill in the values (see below)
./venv/bin/uvicorn waiverwire.api:app --reload --port 8000
```

### 2. Frontend
```bash
cd frontend
npm install
npm run dev               # http://localhost:5173
```
The Vite dev server proxies `/api` to `localhost:8000`, so both run side by side
with no extra config.

### Environment variables (`.env`)
See [`.env.example`](.env.example). The important ones:

| Variable | What it's for |
|----------|---------------|
| `AUTH_SECRET` | Signs session tokens. Set a stable random value in production. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `USERS_DB` | Path to the SQLite user database (default `waiverwire.db`) |
| `GEMINI_API_KEY` | Enables the AI features (outlook / chat / compare) |
| `GEMINI_MODEL` | Gemini model name (e.g. `gemini-3.6-flash`) |
| `ALLOWED_ORIGINS` | Extra CORS origins, comma-separated (not needed when the frontend is served from the same origin as the API) |

`.env` and `*.db` are gitignored — never commit real secrets.

---

## How stats stay current

The backend caches nflverse data in memory for ~6 hours; the next request after
that re-downloads the latest. nflverse refreshes its data as each week's games
are finalized, so as long as the server is running, the app shows up-to-date
numbers on its own — no scheduled job required. The season/week rollover is
date-based and advances automatically.

---

## Deployment

See **[DEPLOY.md](DEPLOY.md)** for a full step-by-step AWS runbook: a single EC2
box for the FastAPI backend (behind nginx) and S3 + CloudFront for the React
build, with CloudFront proxying `/api/*` to the backend (so there's one origin
and no CORS in production).

---

## CLI helpers

Installed by `pip install -e .`:

```bash
waiver-leagues                 # list the Sleeper leagues for $sleeper_username
waiver-rank [league_id]        # rank available players for a league
```
These read `sleeper_username` from `.env`; the web app instead stores each
user's Sleeper name in the database.

---

## Data & credits

Player data from [nflverse](https://github.com/nflverse) via nflreadpy. League
data from the [Sleeper API](https://docs.sleeper.com). Not affiliated with the
NFL or Sleeper.
