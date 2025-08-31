import datetime as dt

from app.util.models import (
    GWPlannerResponse,
    GWPlannerLite,
)


def test_planner_response_shape_compact_validates():
    now = dt.datetime(2024, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = GWPlannerLite(
        gw=3,
        picks_gw_used=2,
        formation_current="4-4-2",
        formation_optimal="4-4-2",
        current_start=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        current_bench=[12, 13, 14, 15],
        optimal_start=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        optimal_bench=[12, 13, 14, 15],
        captain=1,
        vice_captain=2,
        ep_total_current=10.12,
        ep_total_optimal=10.12,
        ep_gain_lineup=0.0,
        bench_ep_total=1.23,
        chip_eval={"bench_boost_gain": 0.0, "triple_captain_gain": 0.0},
        per_player_ep={i: 0.5 for i in range(1, 16)},
    )

    resp = GWPlannerResponse(
        schema_version="planner/1.1",
        generated_at=now,
        meta={"tid": 123, "gw": 3, "mode": "safe", "allow_hit": False, "bank_used": 0},
        data=data,
        actions=[
            {
                "type": "swap",
                "action_group": "lineup",
                "priority": 10,
                "bundle_id": "lineup-3-1",
                "in_player": 12,
                "out_player": 11,
                "ep_in": 0.70,
                "ep_out": 0.14,
                "delta_ep": 0.56,
                "reason_code": "higher_ep",
                "factors": {"home": True, "opp_strength": 3, "form": 2.7},
                "in_fixture": {"opponent_team_id": 2, "opponent_strength": 3, "was_home": True},
                "out_fixture": {"opponent_team_id": 5, "opponent_strength": 4, "was_home": False},
                "reason": "EP_diff 0.14 -> 0.70; form 2.7",
            },
            {
                "type": "set_captain",
                "action_group": "captaincy",
                "priority": 50,
                "player": 9,
                "old_player": 1,
                "ep_new": 2.24,
                "ep_old": 1.39,
                "delta_ep": 0.85,
                "captain_mode": "safe",
                "reason_code": "highest_captain_score",
                "reason": "Highest captain score in mode=safe",
            },
            {
                "type": "chip",
                "action_group": "chip",
                "priority": 90,
                "chip": "NONE",
                "reason_code": "below_threshold",
                "details": {
                    "bench_boost_gain": 0.0,
                    "triple_captain_gain": 0.0,
                    "bench_boost_threshold": 12.0,
                    "triple_captain_threshold": 4.0,
                },
                "reason": "Chip evaluation",
            },
        ],
        summary="Start A; bench B. Captain C (safe). Chip: none.",
        summary_long="Start A for B (+0.56 EP). No chip—bench adds +0.00 EP below 12.",
    )

    dumped = resp.model_dump(exclude_none=True)
    assert dumped["schema_version"] == "planner/1.1"
    assert "actions_expanded" not in dumped
    assert all("opponent_team_name" not in (a.get("in_fixture") or {}) for a in dumped["actions"]) 
from fastapi.testclient import TestClient
from app.api.main import app


def _mock_bootstrap():
    # Minimal bootstrap: events, elements (15 + some), teams, element_types
    return {
        "events": [
            {"id": 3, "is_current": True, "finished": False},
            {"id": 2, "is_current": False, "finished": True},
        ],
        "element_types": [
            {"id": 1, "singular_name_short": "G"},
            {"id": 2, "singular_name_short": "D"},
            {"id": 3, "singular_name_short": "M"},
            {"id": 4, "singular_name_short": "F"},
        ],
        "teams": [
            {"id": 1, "name": "Arsenal", "strength": 4},
            {"id": 2, "name": "Chelsea", "strength": 3},
            {"id": 3, "name": "Liverpool", "strength": 4},
            {"id": 4, "name": "Man City", "strength": 5},
        ],
        "elements": [
            # GK 2
            {"id": 1, "web_name": "Dbravka", "team": 1, "element_type": 1, "now_cost": 45, "form": "2.7", "ict_index": "4.0", "minutes": 270, "selected_by_percent": "10.0"},
            {"id": 12, "web_name": "Snchez", "team": 2, "element_type": 1, "now_cost": 45, "form": "0.1", "ict_index": "1.0", "minutes": 90, "selected_by_percent": "6.0"},
            # DEF 5
            {"id": 191, "web_name": "Esteve", "team": 2, "element_type": 2, "now_cost": 40, "form": "2.7", "ict_index": "5.0", "minutes": 270, "selected_by_percent": "1.0"},
            {"id": 506, "web_name": "Murillo", "team": 3, "element_type": 2, "now_cost": 40, "form": "0.1", "ict_index": "1.0", "minutes": 90, "selected_by_percent": "2.0"},
            {"id": 4, "web_name": "DEF4", "team": 1, "element_type": 2, "now_cost": 45, "form": "1.0", "ict_index": "3.0", "minutes": 270, "selected_by_percent": "5.0"},
            {"id": 5, "web_name": "DEF5", "team": 1, "element_type": 2, "now_cost": 45, "form": "1.0", "ict_index": "3.0", "minutes": 270, "selected_by_percent": "5.0"},
            {"id": 6, "web_name": "DEF6", "team": 1, "element_type": 2, "now_cost": 45, "form": "1.0", "ict_index": "3.0", "minutes": 270, "selected_by_percent": "5.0"},
            # MID 5
            {"id": 7, "web_name": "B Fernandes", "team": 3, "element_type": 3, "now_cost": 95, "form": "3.0", "ict_index": "9.0", "minutes": 270, "selected_by_percent": "20.0"},
            {"id": 8, "web_name": "MID2", "team": 2, "element_type": 3, "now_cost": 60, "form": "2.0", "ict_index": "4.0", "minutes": 270, "selected_by_percent": "12.0"},
            {"id": 9, "web_name": "MID3", "team": 1, "element_type": 3, "now_cost": 60, "form": "2.0", "ict_index": "4.0", "minutes": 270, "selected_by_percent": "12.0"},
            {"id": 10, "web_name": "MID4", "team": 1, "element_type": 3, "now_cost": 60, "form": "2.0", "ict_index": "4.0", "minutes": 270, "selected_by_percent": "12.0"},
            {"id": 11, "web_name": "MID5", "team": 1, "element_type": 3, "now_cost": 60, "form": "2.0", "ict_index": "4.0", "minutes": 270, "selected_by_percent": "12.0"},
            # FWD 3
            {"id": 13, "web_name": "FWD1", "team": 2, "element_type": 4, "now_cost": 70, "form": "2.2", "ict_index": "5.0", "minutes": 270, "selected_by_percent": "5.0"},
            {"id": 14, "web_name": "FWD2", "team": 3, "element_type": 4, "now_cost": 70, "form": "1.9", "ict_index": "4.0", "minutes": 270, "selected_by_percent": "4.0"},
            {"id": 15, "web_name": "FWD3", "team": 4, "element_type": 4, "now_cost": 70, "form": "1.7", "ict_index": "3.0", "minutes": 270, "selected_by_percent": "3.0"},
        ],
    }


def _mock_fixtures(gw: int):
    # Simple mapping: team 1 plays 2 (home), 3 plays 4 (home)
    return [
        {"id": 1, "event": gw, "team_h": 1, "team_a": 2},
        {"id": 2, "event": gw, "team_h": 3, "team_a": 4},
    ]


def _mock_picks(gw: int):
    # 11 starters + 4 bench
    starters = [
        1, 191, 506, 4, 5, 7, 8, 9, 10, 13, 14
    ]
    bench = [12, 6, 11, 15]
    picks = []
    for eid in starters:
        picks.append({"element": eid, "multiplier": 1, "is_captain": eid == 7, "is_vice_captain": eid == 9})
    for eid in bench:
        picks.append({"element": eid, "multiplier": 0, "is_captain": False, "is_vice_captain": False})
    return {"picks": picks, "entry_history": {"bank": 0}}


def test_planner_endpoint_compact_and_expanded(monkeypatch):
    # Monkeypatch network calls
    from app.services import fpl_client

    monkeypatch.setattr(fpl_client, "bootstrap", lambda: _mock_bootstrap())
    monkeypatch.setattr(fpl_client, "fixtures", lambda: _mock_fixtures(4))
    monkeypatch.setattr(fpl_client, "manager_picks", lambda tid, gw: _mock_picks(3))

    client = TestClient(app)

    # Compact
    r = client.get("/tools/get_gameweek_planner/123/4")
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == "planner/1.1"
    assert "actions_expanded" not in data
    # Compact has no nulls and no opponent names in fixtures
    for a in data.get("actions", []):
        for k, v in a.items():
            assert v is not None
        if a.get("type") == "swap":
            assert "opponent_team_name" not in a.get("in_fixture", {})
            assert "opponent_team_name" not in a.get("out_fixture", {})
    # captain_mode present on set_captain
    caps = [a for a in data.get("actions", []) if a.get("type") == "set_captain"]
    if caps:
        assert "captain_mode" in caps[0]

    # Rounding: check 2dp formatting on a delta if present
    swaps = [a for a in data.get("actions", []) if a.get("type") == "swap"]
    if swaps:
        d = swaps[0]["delta_ep"]
        assert abs(d - round(d, 2)) < 1e-9

    # Expanded
    r2 = client.get("/tools/get_gameweek_planner/123/4?expand=true")
    assert r2.status_code == 200
    data2 = r2.json()
    assert "actions_expanded" in data2
    # formation string is legal
    form = data2["data"]["formation_optimal"]
    assert form.count("-") == 2
