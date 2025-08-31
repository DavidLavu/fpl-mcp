from __future__ import annotations

from typing import Dict, Any


def build_indexes(bootstrap: dict) -> dict:
    """Build lookup indexes from the FPL bootstrap payload.

    Returns a dict with:
    - players_by_id: {element_id: {id, web_name, team, now_cost, element_type, selected_by_percent}}
    - teams_by_id: {team_id: {id, name, strength}}
    - positions_by_id: {element_type_id: "GK"|"DEF"|"MID"|"FWD"}
    """
    players = bootstrap.get("elements", []) or []
    teams = bootstrap.get("teams", []) or []
    element_types = bootstrap.get("element_types", []) or []

    players_by_id: Dict[int, Dict[str, Any]] = {}
    for p in players:
        pid = int(p.get("id"))
        players_by_id[pid] = {
            "id": pid,
            "web_name": p.get("web_name"),
            "team": int(p.get("team", 0) or 0),
            "now_cost": int(p.get("now_cost", 0) or 0),
            "element_type": int(p.get("element_type", 0) or 0),
            "selected_by_percent": p.get("selected_by_percent"),
        }

    teams_by_id: Dict[int, Dict[str, Any]] = {}
    for t in teams:
        tid = int(t.get("id"))
        teams_by_id[tid] = {
            "id": tid,
            "name": t.get("name"),
            "strength": int(t.get("strength", 3) or 3),
        }

    # Default positions mapping
    positions_by_id: Dict[int, str] = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    # If element_types provided, map by id->singular_name_short or pick first char heuristic
    for et in element_types:
        et_id = int(et.get("id", 0) or 0)
        short = et.get("singular_name_short") or et.get("singular_name")
        if isinstance(short, str) and short:
            token = short.upper()
            if token.startswith("G"):
                positions_by_id[et_id] = "GK"
            elif token.startswith("D"):
                positions_by_id[et_id] = "DEF"
            elif token.startswith("M"):
                positions_by_id[et_id] = "MID"
            elif token.startswith("F"):
                positions_by_id[et_id] = "FWD"

    return {
        "players_by_id": players_by_id,
        "teams_by_id": teams_by_id,
        "positions_by_id": positions_by_id,
    }


def describe_player(element_id: int, idx: dict) -> dict:
    """Return a denormalized player view for LLM-friendly payloads."""
    p = idx["players_by_id"].get(int(element_id)) or {}
    team_id = int(p.get("team", 0) or 0)
    team = idx["teams_by_id"].get(team_id) or {}
    et_id = int(p.get("element_type", 0) or 0)
    position = idx["positions_by_id"].get(et_id)
    # Ownership can be a string percentage; parse to float if present.
    raw_own = p.get("selected_by_percent")
    try:
        ownership = float(raw_own) if raw_own is not None else 0.0
    except (TypeError, ValueError):
        ownership = 0.0
    return {
        "id": int(p.get("id", 0) or 0),
        "name": p.get("web_name"),
        "team_id": team_id,
        "team_name": team.get("name"),
        "position": position,
        "now_cost": int(p.get("now_cost", 0) or 0),
        "ownership_pct": ownership,
    }


def describe_fixture_context(fx_row: dict, idx: dict, was_home: bool) -> dict:
    """Return a denormalized fixture context for a pick."""
    opponent_team_id = fx_row.get("opponent_team")
    team = idx["teams_by_id"].get(int(opponent_team_id)) if opponent_team_id is not None else None
    return {
        "opponent_team_id": opponent_team_id,
        "opponent_team_name": team.get("name") if team else None,
        "opponent_strength": fx_row.get("opponent_strength"),
        "was_home": bool(was_home),
    }

