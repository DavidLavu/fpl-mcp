from typing import Any, Literal, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.services import fpl_client
from app.util.models import (
    BootstrapPlayer,
    BootstrapSlim,
    BootstrapTeam,
    FixturesResponse,
    Fixture,
    ManagerPick,
    ManagerPicks,
    PickNote,
    CaptainCandidate,
    TemplateDifferential,
    GWManagerSummary,
    EPDeltaRow,
    TransferSuggestion,
    GWManagerAnalysis,
    PicksExpandedItem,
    CaptainCandidateExpanded,
    EPDeltaExpandedRow,
    TransferSuggestionExpanded,
    NamesIndex,
    NamesIndexPlayer,
    PlayerRefExpanded,
    FixtureCtxExpanded,
    GWPlannerLite,
    PlannerPlayerSlot,
    GWPlannerResponse,
)
from app.tools.analysis import (
    ownership_index,
    link_fixtures_for_manager,
    template_vs_differential,
    captain_score,
    recommend_captain,
    recommend_captain_from_ids,
    suggest_transfers,
    expected_points_delta,
    plan_gameweek,
)
from app.util.lookups import build_indexes, describe_player, describe_fixture_context

router = APIRouter(prefix="/api")

# Tools router
tools_router = APIRouter(prefix="/tools", tags=["tools"])


@tools_router.get(
    "/get_bootstrap_data",
    response_model=BootstrapSlim,
    summary="Bootstrap data (teams, players)",
    description="Teams and players from FPL bootstrap-static (selected fields).",
    responses={
        200: {
            "description": "Slim bootstrap payload",
            "content": {
                "application/json": {
                    "examples": {
                        "default": {
                            "summary": "Example",
                            "value": {
                                "teams": [{"id": 1, "name": "Arsenal", "strength": 4}],
                                "players": [{"id": 1, "web_name": "Player", "now_cost": 45, "form": "1.2", "ict_index": "4.5", "minutes": 270, "team": 1}],
                            },
                        }
                    }
                }
            },
        },
        502: {"description": "Upstream FPL API error"},
        422: {"description": "Validation error"},
    },
)
async def get_bootstrap_data() -> BootstrapSlim:
    data: dict[str, Any] = await fpl_client.bootstrap()
    players_raw = data.get("elements", []) or []
    teams_raw = data.get("teams", []) or []

    player_keys = [
        "id",
        "web_name",
        "now_cost",
        "form",
        "ict_index",
        "minutes",
        "team",
    ]
    team_keys = ["id", "name", "strength"]

    players = [
        BootstrapPlayer.model_validate({k: p.get(k) for k in player_keys}) for p in players_raw
    ]
    teams = [BootstrapTeam.model_validate({k: t.get(k) for k in team_keys}) for t in teams_raw]

    return BootstrapSlim(teams=teams, players=players)


@tools_router.get(
    "/get_fixtures",
    response_model=FixturesResponse,
    summary="All fixtures",
    description="Full list of FPL fixtures.",
    responses={
        200: {
            "description": "Fixtures list",
            "content": {
                "application/json": {
                    "examples": {
                        "default": {
                            "summary": "Example",
                            "value": {"fixtures": [{"id": 1, "event": 1, "team_h": 1, "team_a": 2}]},
                        }
                    }
                }
            },
        },
        502: {"description": "Upstream FPL API error"},
    },
)
async def get_fixtures() -> FixturesResponse:
    data = await fpl_client.fixtures()
    fixtures = [Fixture.model_validate(item) for item in data]
    return FixturesResponse(fixtures=fixtures)


@tools_router.get(
    "/get_fixtures_by_gw/{gw}",
    response_model=FixturesResponse,
    summary="Fixtures by gameweek",
    description="Fixtures filtered by a specific gameweek (event).",
    responses={
        200: {
            "description": "Filtered fixtures list",
            "content": {
                "application/json": {
                    "examples": {
                        "default": {
                            "summary": "Example",
                            "value": {"fixtures": [{"id": 2, "event": 3, "team_h": 3, "team_a": 4}]},
                        }
                    }
                }
            },
        },
        422: {"description": "Validation error"},
        502: {"description": "Upstream FPL API error"},
    },
)
async def get_fixtures_by_gw(gw: int) -> FixturesResponse:
    if gw < 1:
        raise HTTPException(status_code=422, detail="gw must be >= 1")
    data = await fpl_client.fixtures_by_gw(gw)
    fixtures = [Fixture.model_validate(item) for item in data]
    return FixturesResponse(fixtures=fixtures)


@tools_router.get(
    "/get_manager_picks/{tid}/{gw}",
    response_model=ManagerPicks,
    summary="Manager picks",
    description=(
        "Manager's picks for an entry (team id) and gameweek. "
        "Add ?expand=true to include player and fixture context."
    ),
    responses={
        200: {
            "description": "Manager picks",
            "content": {
                "application/json": {
                    "examples": {
                        "default": {
                            "summary": "Example",
                            "value": {
                                "picks": [
                                    {
                                        "element": 1,
                                        "is_captain": True,
                                        "is_vice_captain": False,
                                        "multiplier": 2,
                                    }
                                ]
                            },
                        }
                    }
                }
            },
        },
        422: {"description": "Validation error"},
        502: {"description": "Upstream FPL API error"},
    },
)
async def get_manager_picks(tid: int, gw: int, expand: bool = False) -> ManagerPicks:
    if tid <= 0:
        raise HTTPException(status_code=422, detail="tid must be > 0")
    if gw < 1:
        raise HTTPException(status_code=422, detail="gw must be >= 1")
    data = await fpl_client.manager_picks(tid=tid, gw=gw)
    picks_raw = data.get("picks", []) or []
    picks = [ManagerPick.model_validate(p) for p in picks_raw]

    if not expand:
        return ManagerPicks(picks=picks)

    # Expanded: attach player and fixture context for this GW
    boot = await fpl_client.bootstrap()
    fix_all = await fpl_client.fixtures()
    fix = [f for f in fix_all if f.get("event") == gw]
    idx = build_indexes(boot)
    linked = link_fixtures_for_manager(
        gw, picks_raw, fix, boot.get("elements", []), boot.get("teams", [])
    )
    picks_expanded = []
    for row in linked:
        pid = int(row.get("element"))
        pref = PlayerRefExpanded(**describe_player(pid, idx))
        fx = row.get("fixture_row", {}) or {}
        fx_ctx = None
        if fx:
            fx_ctx = FixtureCtxExpanded(**describe_fixture_context(fx, idx, bool(fx.get("was_home"))))
        picks_expanded.append(
            PicksExpandedItem(
                player=pref,
                is_captain=bool(row.get("is_captain")),
                is_vice_captain=bool(row.get("is_vice_captain")),
                fixture=fx_ctx,
            )
        )
    return ManagerPicks(picks=picks, picks_expanded=picks_expanded)


def init_app(app: FastAPI) -> None:
    """Register API routers and CORS middleware on the given app.

    Allows localhost origins for local development.
    """
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.include_router(tools_router)


__all__ = ["router", "init_app"]


# Additional analysis endpoints

@tools_router.get(
    "/get_manager_gameweek_summary/{tid}/{gw}",
    response_model=GWManagerSummary,
    summary="Manager GW summary",
    description="Picks, template/differential split, and top captain candidates for a GW. Add ?expand=true for denormalized fields.",
    responses={
        200: {
            "description": "GW summary",
            "content": {
                "application/json": {
                    "examples": {
                        "default": {
                            "summary": "Example",
                            "value": {
                                "gw": 1,
                                "picks": [{"element": 1, "is_captain": True, "is_vice_captain": False}],
                                "template_vs_differential": {
                                    "template_count": 7,
                                    "differential_count": 4,
                                    "template_ratio": 0.636,
                                },
                                "captain_candidates": [
                                    {"element": 1, "score": 5.1},
                                    {"element": 2, "score": 4.7},
                                    {"element": 3, "score": 4.1},
                                ],
                            },
                        },
                        "expanded": {
                            "summary": "Expanded snippet",
                            "value": {
                                "gw": 1,
                                "picks_expanded": [
                                    {
                                        "player": {"id": 381, "name": "Saka", "team_id": 1, "team_name": "Arsenal", "position": "MID", "now_cost": 86, "ownership_pct": 64.3},
                                        "is_captain": True,
                                        "is_vice_captain": False,
                                        "fixture": {"opponent_team_id": 10, "opponent_team_name": "Chelsea", "opponent_strength": 3, "was_home": True}
                                    }
                                ],
                                "captain_candidates_expanded": [
                                    {"player": {"id": 381, "name": "Saka", "team_id": 1, "team_name": "Arsenal", "position": "MID"}, "score": 19.2}
                                ]
                            }
                        }
                    }
                }
            },
        },
        422: {"description": "Validation error"},
        502: {"description": "Upstream FPL API error"},
    },
)
async def get_manager_gameweek_summary(tid: int, gw: int, expand: bool = False) -> GWManagerSummary:
    if tid <= 0:
        raise HTTPException(status_code=422, detail="tid must be > 0")
    if gw < 1:
        raise HTTPException(status_code=422, detail="gw must be >= 1")

    boot = await fpl_client.bootstrap()
    picks_data = await fpl_client.manager_picks(tid, gw)
    fix_all = await fpl_client.fixtures()
    fix = [f for f in fix_all if f.get("event") == gw]

    ownership = ownership_index(boot.get("elements", []))
    linked = link_fixtures_for_manager(
        gw, picks_data.get("picks", []), fix, boot.get("elements", []), boot.get("teams", [])
    )

    pick_notes: list[PickNote] = [
        PickNote(element=int(p.get("element")), is_captain=bool(p.get("is_captain")), is_vice_captain=bool(p.get("is_vice_captain")))
        for p in linked
    ]

    tvd_raw = template_vs_differential(picks_data.get("picks", []), ownership, threshold=20.0)
    tvd = TemplateDifferential(
        template_count=int(tvd_raw["template_count"]),
        differential_count=int(tvd_raw["differential_count"]),
        template_ratio=float(tvd_raw["template_ratio"]),
    )

    # Rank top 3 captain candidates among starting XI (multiplier > 0)
    candidates: list[CaptainCandidate] = []
    for row in linked:
        if int(row.get("multiplier", 0)) <= 0:
            continue
        player = row.get("player")
        fixture_row = row.get("fixture_row", {})
        if not player or not fixture_row:
            continue
        pid = int(row.get("element"))
        own = ownership.get(pid, 0.0)
        score = captain_score(player, fixture_row, own, mode="safe")
        candidates.append(CaptainCandidate(element=pid, score=float(score)))
    candidates = sorted(candidates, key=lambda c: c.score, reverse=True)[:3]

    # Build compact response first
    top3_candidates = [{"element": c.element, "score": c.score} for c in candidates]
    resp: dict[str, Any] = {
        "gw": gw,
        "picks": [
            {
                "element": int(p.get("element")),
                "is_captain": bool(p.get("is_captain")),
                "is_vice_captain": bool(p.get("is_vice_captain")),
            }
            for p in linked
        ],
        "template_vs_differential": tvd.model_dump() if hasattr(tvd, "model_dump") else tvd,
        "captain_candidates": top3_candidates,
    }

    if expand:
        idx = build_indexes(boot)
        picks_expanded = []
        for p in linked:
            fx = p.get("fixture_row") or {}
            picks_expanded.append(
                {
                    "player": describe_player(int(p["element"]), idx),
                    "is_captain": bool(p.get("is_captain")),
                    "is_vice_captain": bool(p.get("is_vice_captain")),
                    "fixture": describe_fixture_context(fx, idx, bool(p.get("was_home", fx.get("was_home", False))))
                    if fx
                    else None,
                }
            )
        captain_candidates_expanded = [
            {"player": describe_player(int(c["element"]), idx), "score": float(c["score"])}
            for c in top3_candidates
        ]
        resp["picks_expanded"] = picks_expanded
        resp["captain_candidates_expanded"] = captain_candidates_expanded

    return resp


@tools_router.get(
    "/get_manager_gameweek_analysis/{tid}/{gw}",
    response_model=GWManagerAnalysis,
    summary="Manager GW analysis",
    description=(
        "Captain picks, EPΔ per player, and simple transfer suggestions. "
        "Query params: expand=true for denormalized fields; mode=safe|aggressive (default aggressive); "
        "allow_hit=true to allow a 0.4m budget deficit (simulating -4); bank_override=<int 0.1m units> to override bank."
    ),
    responses={
        200: {
            "description": "GW analysis",
            "content": {
                "application/json": {
                    "examples": {
                        "default": {
                            "summary": "Example",
                            "value": {
                                "gw": 1,
                                "recommended_captain_safe": {"element": 1, "score": 5.2},
                                "recommended_captain_aggressive": {"element": 2, "score": 5.0},
                                "epdeltas": [
                                    {"element": 1, "epdelta": 3.4, "opponent_team": 2, "opponent_strength": 3, "was_home": True}
                                ],
                                "transfer_suggestions": [
                                    {"out_element": 3, "in_element": 10, "reason": "Higher projected EPΔ", "epdelta_gain": 1.1}
                                ],
                            },
                        },
                        "expanded": {
                            "summary": "Expanded snippet",
                            "value": {
                                "recommended_captain_safe_expanded": {"player": {"id": 381, "name": "Saka", "team_id": 1, "team_name": "Arsenal", "position": "MID"}, "score": 19.2},
                                "epdeltas_expanded": [
                                    {"player": {"id": 381, "name": "Saka"}, "epdelta": 2.09, "fixture": {"opponent_team_id": 10, "opponent_team_name": "Chelsea", "opponent_strength": 3, "was_home": True}}
                                ],
                                "transfer_suggestions_expanded": [
                                    {"out": {"id": 3}, "in_": {"id": 10}, "reason": "Higher projected EPΔ", "epdelta_gain": 1.99}
                                ]
                            }
                        }
                    }
                }
            },
        },
        422: {"description": "Validation error"},
        502: {"description": "Upstream FPL API error"},
    },
)
async def get_manager_gameweek_analysis(
    tid: int,
    gw: int,
    expand: bool = False,
    mode: Literal["safe", "aggressive"] = "aggressive",
    allow_hit: bool = False,
    bank_override: Optional[int] = None,
) -> GWManagerAnalysis:
    if tid <= 0:
        raise HTTPException(status_code=422, detail="tid must be > 0")
    if gw < 1:
        raise HTTPException(status_code=422, detail="gw must be >= 1")

    boot = await fpl_client.bootstrap()
    picks_data = await fpl_client.manager_picks(tid, gw)
    fix_all = await fpl_client.fixtures()
    fix = [f for f in fix_all if f.get("event") == gw]

    ownership = ownership_index(boot.get("elements", []))
    linked = link_fixtures_for_manager(
        gw, picks_data.get("picks", []), fix, boot.get("elements", []), boot.get("teams", [])
    )

    # Recommended captains (safe/aggressive)
    safe_elem, safe_score = recommend_captain(linked, ownership, mode="safe")
    agg_elem, agg_score = recommend_captain(linked, ownership, mode="aggressive")

    recommended_captain_safe = CaptainCandidate(element=int(safe_elem), score=float(safe_score))
    recommended_captain_aggressive = CaptainCandidate(element=int(agg_elem), score=float(agg_score))

    # EPΔ rows for each pick
    epdeltas: list[EPDeltaRow] = []
    for row in linked:
        player = row.get("player")
        fx = row.get("fixture_row", {})
        if not player or not fx:
            continue
        opp = int(fx.get("opponent_strength") or 3)
        minutes_proxy = float(min(float(player.get("minutes", 0) or 0), 180.0))
        epd = expected_points_delta(player, opp, minutes_proxy)
        epdeltas.append(
            EPDeltaRow(
                element=int(row.get("element")),
                epdelta=float(epd),
                opponent_team=fx.get("opponent_team"),
                opponent_strength=fx.get("opponent_strength"),
                was_home=fx.get("was_home"),
            )
        )

    # Transfer suggestions with reason and EPΔ gain
    # Determine bank (0.1m units) and allowance for hits
    entry_history = picks_data.get("entry_history", {}) or {}
    bank_val = int(entry_history.get("bank", 0) or 0)
    if bank_override is not None:
        bank_val = int(bank_override)
    allowance = 4 if allow_hit else 0

    suggestions_raw = suggest_transfers(
        linked, boot.get("elements", []), ownership, mode=mode, bank=bank_val, bank_allowance=allowance
    )
    # Build index for elements to compute EPΔ for suggested 'in'
    elem_by_id = {int(e.get("id")): e for e in boot.get("elements", [])}
    # Current EPΔ map for quick lookup
    current_epd: dict[int, float] = {row.element: row.epdelta for row in epdeltas}
    transfers: list[TransferSuggestion] = []
    for s in suggestions_raw:
        out_id = int(s.get("out"))
        in_id = int(s.get("in"))
        in_player = elem_by_id.get(in_id)
        if not in_player:
            continue
        # Neutral opponent assumption for incoming player
        in_minutes = float(min(float(in_player.get("minutes", 0) or 0), 180.0))
        in_epd = expected_points_delta(in_player, 3, in_minutes)
        gain = float(in_epd - current_epd.get(out_id, 0.0))
        transfers.append(
            TransferSuggestion(
                out_element=out_id,
                in_element=in_id,
                reason="Higher projected EPΔ",
                epdelta_gain=gain,
            )
        )

    # Compact response
    rec_safe = {"element": recommended_captain_safe.element, "score": recommended_captain_safe.score}
    rec_aggr = {
        "element": recommended_captain_aggressive.element,
        "score": recommended_captain_aggressive.score,
    }
    epdeltas_compact = [
        {
            "element": e.element,
            "epdelta": e.epdelta,
            "opponent_team": e.opponent_team,
            "opponent_strength": e.opponent_strength,
            "was_home": e.was_home,
        }
        for e in epdeltas
    ]
    transfer_compact = [
        {
            "out_element": t.out_element,
            "in_element": t.in_element,
            "reason": t.reason,
            "epdelta_gain": t.epdelta_gain,
        }
        for t in transfers
    ]

    resp2: dict[str, Any] = {
        "gw": gw,
        "recommended_captain_safe": rec_safe,
        "recommended_captain_aggressive": rec_aggr,
        "epdeltas": epdeltas_compact,
        "transfer_suggestions": transfer_compact,
    }

    if expand:
        idx = build_indexes(boot)
        epdeltas_expanded = []
        for row in epdeltas_compact:
            epdeltas_expanded.append(
                {
                    "player": describe_player(int(row["element"]), idx),
                    "epdelta": float(row["epdelta"]),
                    "fixture": {
                        "opponent_team_id": row.get("opponent_team"),
                        "opponent_team_name": (idx["teams_by_id"].get(row.get("opponent_team"), {}) or {}).get(
                            "name"
                        ),
                        "opponent_strength": row.get("opponent_strength"),
                        "was_home": row.get("was_home", None),
                    },
                }
            )
        rec_safe_expanded = {
            "player": describe_player(int(rec_safe["element"]), idx),
            "score": float(rec_safe["score"]),
        }
        rec_aggr_expanded = {
            "player": describe_player(int(rec_aggr["element"]), idx),
            "score": float(rec_aggr["score"]),
        }
        transfer_suggestions_expanded = [
            {
                "out": describe_player(int(s["out_element"]), idx),
                "in_": describe_player(int(s["in_element"]), idx),
                "reason": s["reason"],
                "epdelta_gain": float(s["epdelta_gain"]),
            }
            for s in transfer_compact
        ]
        resp2["epdeltas_expanded"] = epdeltas_expanded
        resp2["recommended_captain_safe_expanded"] = rec_safe_expanded
        resp2["recommended_captain_aggressive_expanded"] = rec_aggr_expanded
        resp2["transfer_suggestions_expanded"] = transfer_suggestions_expanded

    return resp2


@tools_router.get(
    "/get_names_index",
    response_model=NamesIndex,
    summary="Names index",
    description="IDs mapped to human-friendly player and team names.",
    responses={
        200: {
            "description": "Names index",
            "content": {
                "application/json": {
                    "examples": {
                        "default": {
                            "summary": "Example",
                            "value": {
                                "players": {"381": {"name": "Saka", "team_id": 1, "team_name": "Arsenal", "position": "MID"}},
                                "teams": {"1": "Arsenal"}
                            },
                        }
                    }
                }
            },
        }
    },
)
async def get_names_index() -> NamesIndex:
    boot = await fpl_client.bootstrap()
    idx = build_indexes(boot)
    # Build players dict
    players: dict[int, NamesIndexPlayer] = {}
    for pid_str, pdata in idx["players_by_id"].items():
        pid = int(pid_str)
        players[pid] = NamesIndexPlayer(
            name=pdata.get("web_name"),
            team_id=int(pdata.get("team", 0) or 0),
            team_name=idx["teams_by_id"].get(int(pdata.get("team", 0) or 0), {}).get("name"),
            position=idx["positions_by_id"].get(int(pdata.get("element_type", 0) or 0)),
        )
    teams: dict[int, str | None] = {}
    for tid, t in idx["teams_by_id"].items():
        teams[int(tid)] = t.get("name")

    return NamesIndex(players=players, teams=teams)


@tools_router.get(
    "/get_gameweek_planner/{tid}/{gw}",
    response_model=GWPlannerResponse,
    response_model_exclude_none=True,
    summary="Gameweek Planner",
    description=(
        "Optimize XI, bench, and captain/vice for a target GW. "
        "Default picks_strategy=latest uses your last live GW squad; picks_strategy=exact requires target-GW picks. "
        "Use expand=true for denormalized fields; include_transfers adds legal suggestions."
    ),
    responses={
        200: {"description": "Planner response (compact + optional expanded)"},
        422: {"description": "Validation error"},
        404: {"description": "Manager picks not found"},
        502: {"description": "Upstream FPL API error"},
    },
)
async def get_gameweek_planner(
    tid: int,
    gw: int,
    expand: bool = Query(False, description="Include denormalized fields (LLM-friendly)"),
    mode: Literal["safe", "aggressive"] = Query(
        "safe", description="Captain preference: safe (template) or aggressive (differentials)"
    ),
    include_transfers: bool = Query(True, description="Include legal transfer suggestions"),
    allow_hit: bool = Query(False, description="Allow 0.4m deficit (simulate -4) for transfers"),
    bank_override: Optional[int] = Query(
        None, description="Override bank in 0.1m units for transfer checks"
    ),
    picks_strategy: Literal["latest", "exact"] = Query(
        "latest",
        description="Use last live GW squad when exact GW picks unavailable (latest) or require exact GW picks (exact)",
    ),
) -> GWPlannerResponse:
    if tid <= 0 or gw <= 0:
        raise HTTPException(status_code=422, detail="Invalid tid/gw")

    boot = await fpl_client.bootstrap()
    fixtures_all = await fpl_client.fixtures()
    fixtures_gw = [f for f in fixtures_all if f.get("event") == gw]

    # Choose picks baseline per strategy
    picks_gw_used: Optional[int] = None
    if picks_strategy == "exact":
        mp = await fpl_client.manager_picks(tid, gw)
        picks_gw_used = gw
    else:
        events = boot.get("events", []) or []
        last_live = max((int(e.get("id")) for e in events if e.get("is_current") or e.get("finished")), default=None)
        if not last_live:
            raise HTTPException(status_code=502, detail="Cannot determine last live GW from bootstrap")
        cur = int(last_live)
        mp = None
        while cur >= 1:
            try:
                mp = await fpl_client.manager_picks(tid, cur)
                picks_gw_used = cur
                break
            except HTTPException as e:
                if e.status_code == 404:
                    cur -= 1
                    continue
                raise
        if mp is None:
            raise HTTPException(status_code=404, detail="Could not load any baseline picks for this team")

    ownership = ownership_index(boot.get("elements", []))

    # Link fixtures for TARGET gw using baseline squad
    linked = link_fixtures_for_manager(
        gw, mp.get("picks", []), fixtures_all, boot.get("elements", []), boot.get("teams", [])
    )
    plan = plan_gameweek(
        mp.get("picks", []),
        boot.get("elements", []),
        boot.get("teams", []),
        fixtures_gw,
        gw,
        ownership,
        mode=mode,
    )

    resp = GWPlannerResponse(
        schema_version="planner/1.1",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        meta={
            "tid": tid,
            "gw": gw,
            "mode": mode,
            "allow_hit": allow_hit,
            "bank_used": int((mp.get("entry_history", {}) or {}).get("bank", 0) or 0)
            if bank_override is None
            else int(bank_override),
        },
        data=GWPlannerLite(
            gw=gw,
            picks_gw_used=picks_gw_used,
            formation_current=plan["formation_current"],
            formation_optimal=plan["formation_optimal"],
            current_start=plan["current_start"],
            current_bench=plan["current_bench"],
            optimal_start=plan["optimal_start"],
            optimal_bench=plan["optimal_bench"],
            captain=plan["captain"],
            vice_captain=plan["vice_captain"],
            ep_total_current=plan["ep_total_current"],
            ep_total_optimal=plan["ep_total_optimal"],
            ep_gain_lineup=plan["ep_gain_lineup"],
            bench_ep_total=plan["bench_ep_total"],
            chip_eval=plan["chip_eval"],
            per_player_ep=plan["per_player_ep"],
        )
    )
    # top-level actions and summaries
    resp.actions = plan.get("actions", [])
    resp.summary = plan.get("summary")
    resp.summary_long = plan.get("summary_long")

    # Guardrail validation: swaps should transform current_start to optimal_start and formation should match
    try:
        elements = boot.get("elements", [])
        elem_by_id = {int(e.get("id")): e for e in elements}
        positions = {pid: {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(int(elem_by_id.get(pid, {}).get("element_type", 0) or 0), "MID") for pid in set(resp.data.current_start + resp.data.optimal_start)}
        start_set = set(resp.data.current_start)
        bench_set = set(resp.data.current_bench)
        swaps = [a for a in (resp.actions or []) if a.get("type") == "swap"]
        swaps.sort(key=lambda a: (a.get("bundle_id") or "", int(a.get("priority", 0))))
        for sw in swaps:
            inn = int(sw["in_player"])  # must be from bench
            outn = int(sw["out_player"])  # must be from start
            if inn not in bench_set or outn not in start_set:
                raise ValueError(f"Invalid swap order: in={inn} out={outn}")
            start_set.remove(outn)
            start_set.add(inn)
            bench_set.remove(inn)
            bench_set.add(outn)
            if len(start_set) != 11:
                raise ValueError("Starters count must remain 11 after swap")
        if sorted(start_set) != sorted(resp.data.optimal_start):
            raise ValueError("Swaps do not yield optimal_start")
        # Validate formation matches positions
        from app.tools.analysis import formation_str
        if formation_str(resp.data.optimal_start, positions) != resp.data.formation_optimal:
            raise ValueError("formation_optimal does not match derived positions")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Planner validation failed: {e}")

    # Captain/vice already computed inside plan

    if include_transfers:
        bank = int((mp.get("entry_history", {}) or {}).get("bank", 0) or 0)
        if bank_override is not None:
            bank = int(bank_override)
        allowance = 4 if allow_hit else 0
        raw = suggest_transfers(
            linked, boot.get("elements", []), ownership, mode=mode, bank=bank, bank_allowance=allowance
        )
        # Build compact suggestions with gain, then de-dup by in and min gain
        compact = [
            {
                "out_element": int(s.get("out")),
                "in_element": int(s.get("in")),
                "reason": str(s.get("reason")),
                "epdelta_gain": float(s.get("epdelta_in", 0.0) - s.get("epdelta_out", 0.0))
                if "epdelta_in" in s
                else float(s.get("epdelta_gain", 0.0)),
            }
            for s in raw
        ]
        MIN_GAIN = 0.5
        seen_in: set[int] = set()
        dedup: list[dict] = []
        for s in compact:
            if s["epdelta_gain"] < MIN_GAIN or s["in_element"] in seen_in:
                continue
            seen_in.add(s["in_element"])
            dedup.append(s)
        # Round epdelta_gain to 2dp
        for s in dedup:
            s["epdelta_gain"] = round(float(s["epdelta_gain"]), 2)
        resp.transfer_suggestions = [TransferSuggestion(**s) for s in dedup]

    if expand:
        idx = build_indexes(boot)
        fx_by_id = {int(p.get("element")): p.get("fixture_row") for p in linked}

        def slot(eid: int, cap: bool = False, vc: bool = False) -> PlannerPlayerSlot:
            fx = fx_by_id.get(int(eid))
            return PlannerPlayerSlot(
                player=PlayerRefExpanded(**describe_player(int(eid), idx)),
                fixture=FixtureCtxExpanded(**describe_fixture_context(fx, idx, bool(fx.get("was_home", False)))) if fx else None,
                epdelta=float(plan["per_player_ep"].get(int(eid), 0.0)),
                is_captain=cap,
                is_vice_captain=vc,
            )

        cap_id = int(plan.get("captain", 0) or 0)
        vc_id = int(plan.get("vice_captain", 0) or 0)
        resp.current_expanded = [
            slot(e, cap=(e == cap_id and e in plan["current_start"]), vc=(e == vc_id and e in plan["current_start"]))
            for e in plan["current_start"]
        ]
        resp.optimal_expanded = [
            slot(e, cap=(e == cap_id and e in plan["optimal_start"]), vc=(e == vc_id and e in plan["optimal_start"]))
            for e in plan["optimal_start"]
        ]
        resp.bench_expanded = [slot(e) for e in plan["optimal_bench"]]

        if include_transfers and resp.transfer_suggestions:
            resp.transfer_suggestions_expanded = [
                TransferSuggestionExpanded(
                    out=PlayerRefExpanded(**describe_player(int(s.out_element), idx)),
                    in_=PlayerRefExpanded(**describe_player(int(s.in_element), idx)),
                    reason=s.reason,
                    epdelta_gain=s.epdelta_gain,
                )
                for s in resp.transfer_suggestions
            ]

        # Expanded actions
        actions_expanded: list[dict] = []
        for act in (resp.actions or []):
            a = dict(act)
            if "in_player" in a and a["in_player"] is not None:
                a["in_player"] = PlayerRefExpanded(**describe_player(int(a["in_player"]), idx)).model_dump()
            if "out_player" in a and a["out_player"] is not None:
                a["out_player"] = PlayerRefExpanded(**describe_player(int(a["out_player"]), idx)).model_dump()
            if "player" in a and a["player"] is not None:
                a["player"] = PlayerRefExpanded(**describe_player(int(a["player"]), idx)).model_dump()
            if "old_player" in a and a.get("old_player") is not None:
                a["old_player"] = PlayerRefExpanded(**describe_player(int(a["old_player"]), idx)).model_dump()
            # Expand fixtures if present
            if "in_fixture" in a and isinstance(a["in_fixture"], dict):
                fx = a["in_fixture"]
                tid = fx.get("opponent_team_id")
                a["in_fixture"] = FixtureCtxExpanded(
                    opponent_team_id=tid,
                    opponent_team_name=(idx["teams_by_id"].get(int(tid), {}).get("name") if tid is not None else None),
                    opponent_strength=fx.get("opponent_strength"),
                    was_home=fx.get("was_home"),
                ).model_dump()
            if "out_fixture" in a and isinstance(a["out_fixture"], dict):
                fx = a["out_fixture"]
                tid = fx.get("opponent_team_id")
                a["out_fixture"] = FixtureCtxExpanded(
                    opponent_team_id=tid,
                    opponent_team_name=(idx["teams_by_id"].get(int(tid), {}).get("name") if tid is not None else None),
                    opponent_strength=fx.get("opponent_strength"),
                    was_home=fx.get("was_home"),
                ).model_dump()
            actions_expanded.append(a)
        resp.actions_expanded = actions_expanded

    return resp
