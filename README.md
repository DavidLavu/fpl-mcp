[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/DavidLavu/fpl-mcp)


# fpl-mcp

FastAPI service scaffold for working with Fantasy Premier League (FPL) data. This repo includes a production-ready layout, typed settings, caching utilities, and developer tooling (Ruff, Black, pytest, pre-commit).

## Requirements

- Python >= 3.10

## Setup

- Create and activate a virtual environment
  - Windows (PowerShell): `python -m venv .venv; .\\.venv\\Scripts\\Activate.ps1`
  - macOS/Linux (bash): `python -m venv .venv && source .venv/bin/activate`
- Install dependencies
  - Dev install (includes tooling and `uvicorn`): `pip install -e .[dev]`
- Optional: install pre-commit hooks: `pre-commit install`

## Run the server

- With `uvicorn`:
  - `uvicorn app.api.main:app --reload --port 8000`
  - You can set `PORT` via env and use it from code if you extend the entrypoint.
- CORS is enabled for localhost origins (e.g., `http://localhost:3000`).

## Deploy (Free)

Option 1 — Render (Docker, free plan)
- Push this repo to GitHub.
- Create a new Web Service at https://render.com (pick “Deploy an existing Docker repo”).
- Point it at this repo; Render detects `render.yaml` and the `Dockerfile`.
- Keep the free plan; health check path is `/health`.
- Render injects `PORT`; the container honors it. Outbound HTTP is allowed for FPL API calls.

Option 2 — Railway (no Docker needed)
- Create a new project, add “Empty Service” from GitHub.
- Build command: `pip install -U pip && pip install .`
- Start command: `uvicorn app.api.main:app --host 0.0.0.0 --port $PORT`
- Set `CACHE_TTL` if desired.

Option 3 — Hugging Face Spaces (Docker)
- Create a Space (type: Docker) and upload this repo with the `Dockerfile`.
- Set Space hardware: CPU Basic is fine; port is provided via `PORT` env.

## Endpoints

- `GET /health` -> `{ "status": "ok" }`
- Future (planned):
  - `GET /api/players` – player summaries
  - `GET /api/teams` – team metadata
  - `GET /api/fixtures` – fixture list
  - `GET /tools/get_gameweek_planner/{tid}/{gw}` – optimize XI and captain; supports `expand`, `mode`, `include_transfers`, `allow_hit`, `bank_override`, `picks_strategy`.

### Planner response (schema_version planner/1.1)

- Top-level:
  - `schema_version`: string, e.g., `planner/1.1`
  - `generated_at`: ISO8601 UTC
  - `meta`: `{ tid, gw, mode, allow_hit, bank_used, bank_override? }`
  - `summary`: short (<=140 chars)
  - `summary_long`: short paragraph with EP deltas
  - `data`: `GWPlannerLite`
  - `actions`: list of actions (machine-readable)
  - `actions_expanded`: same, with player objects instead of ids

- `GWPlannerLite`:
  - `gw`, `picks_gw_used`
  - `formation_current` / `formation_optimal`
  - `current_start` / `current_bench`
  - `optimal_start` / `optimal_bench`
  - `captain` / `vice_captain`
  - `ep_total_current` / `ep_total_optimal` / `ep_gain_lineup` / `bench_ep_total`
  - `chip_eval`: `{ bench_boost_gain, triple_captain_gain }`
  - `per_player_ep`: `{ element_id: EP (2dp) }`

- Actions (enums):
  - `type`: `swap` | `set_captain` | `set_vice` | `chip`
  - `action_group`: `lineup` | `captaincy` | `chip`
  - `reason_code`: `higher_ep` | `highest_captain_score` | `second_best_captain` | `below_threshold`
  - `chip`: `BB` | `TC` | `FH` | `WC` | `NONE`
  - `captain_mode`: `safe` | `aggressive` (present on `set_captain`)
  - Thresholds: bench_boost >= 12.0 EP, triple_captain >= 4.0 EP

- `swap` action:
  - Compact: `{ type: "swap", action_group: "lineup", priority, bundle_id, in_player, out_player, ep_in, ep_out, delta_ep, reason_code: "higher_ep", factors: { home, opp_strength, form }, in_fixture: {opponent_team_id, opponent_strength, was_home}, out_fixture: {...} }`
  - Expanded: replaces players with `{ id, name, team_name, position }` and fixtures include `opponent_team_name`.

- `set_captain` action:
  - `{ type: "set_captain", action_group: "captaincy", priority, player, old_player?, ep_new, ep_old?, delta_ep, captain_mode: "safe"|"aggressive", reason_code: "highest_captain_score" }`

- `set_vice` action:
  - `{ type: "set_vice", action_group: "captaincy", priority, player, old_player?, reason_code: "second_best_captain" }`

- `chip` action:
  - `{ type: "chip", action_group: "chip", priority, chip, reason_code?: "below_threshold", details: { bench_boost_gain, triple_captain_gain, bench_boost_threshold, triple_captain_threshold } }`

Rounding and nulls
- All EP values are rounded to 2 decimals in the response (data.*, actions.*, transfer_suggestions*).
- Compact outputs exclude nulls; expanded outputs may include names for convenience.

JSON snippets
- Compact swap example:
  `{ "type":"swap","action_group":"lineup","priority":10,"bundle_id":"lineup-3-1","in_player":191,"out_player":506,"ep_in":0.70,"ep_out":0.14,"delta_ep":0.56,"reason_code":"higher_ep","factors":{"home":true,"opp_strength":3,"form":2.7},"in_fixture":{"opponent_team_id":10,"opponent_strength":3,"was_home":true},"out_fixture":{"opponent_team_id":7,"opponent_strength":4,"was_home":false} }`
- Expanded swap example:
  `{ "type":"swap","action_group":"lineup","priority":10,"bundle_id":"lineup-3-1","in_player":{"id":191,"name":"Estève","team_name":"Burnley","position":"DEF"},"out_player":{"id":506,"name":"Murillo","team_name":"Nott'm Forest","position":"DEF"},"ep_in":0.70,"ep_out":0.14,"delta_ep":0.56,"reason_code":"higher_ep","in_fixture":{"opponent_team_id":10,"opponent_team_name":"Chelsea","opponent_strength":3,"was_home":true},"out_fixture":{"opponent_team_id":7,"opponent_team_name":"Aston Villa","opponent_strength":4,"was_home":false} }`

All EP values are rounded to 2 decimals. Reasons use ASCII only (e.g., `EP_diff 0.27 -> 1.97`).

## Project structure

```
app/
  api/
    main.py        # FastAPI app and /health
    routes.py      # Router registration and CORS
  services/
    fpl_client.py  # Async HTTP client stub for FPL API
  tools/
    analysis.py    # Example analysis helper (numpy)
  util/
    cache.py       # Cache helpers (TTLCache)
    models.py      # Pydantic models
    settings.py    # pydantic-settings with PORT and CACHE_TTL
```

## Testing

- Run tests: `pytest -q`

## Tooling

- Ruff: `ruff check .` and `ruff format .`
- Black: `black .`
- Pre-commit: `pre-commit run --all-files`

## Settings

`app/util/settings.py` uses `pydantic-settings` to read environment variables:
- `PORT` – server port (default: `8000`)
- `CACHE_TTL` – cache TTL seconds (default: `300`)

You can create a `.env` file to set these locally.
