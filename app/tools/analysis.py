from __future__ import annotations

from typing import Dict, List, Tuple, Optional
import math


def _nz(x: Optional[float], default: float = 0.0) -> float:
    """Return x if not None, otherwise default.

    Parameters
    - x: Optional float value
    - default: value to use when x is None
    """
    return float(x) if x is not None else float(default)


def _sigmoid(x: float) -> float:
    """Numerically-stable logistic function in the range (0, 1).

    s(x) = 1 / (1 + exp(-x))
    """
    # Clamp extreme values to avoid overflow in exp
    if x >= 50:
        return 1.0
    if x <= -50:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _norm(x: float, lo: float, hi: float) -> float:
    """Normalize x linearly to [0, 1] given [lo, hi], with clamping.

    If hi == lo, returns 0.0 to avoid division by zero.
    """
    if hi == lo:
        return 0.0
    # Ensure lo <= hi for normalization
    lo_, hi_ = (lo, hi) if lo <= hi else (hi, lo)
    v = (x - lo_) / (hi_ - lo_)
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def position_code(element_type: int) -> str:
    """Map FPL element_type to position code."""
    return {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(int(element_type), "MID")


# FPL position constraints
MIN_BY_POS: Dict[str, int] = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}
MAX_BY_POS: Dict[str, int] = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}


def formation_str(ids: List[int], positions: Dict[int, str]) -> str:
    """Return outfield formation string like '4-4-2'."""
    d = sum(1 for i in ids if positions.get(i) == "DEF")
    m = sum(1 for i in ids if positions.get(i) == "MID")
    f = sum(1 for i in ids if positions.get(i) == "FWD")
    return f"{d}-{m}-{f}"


def expected_points_delta(player: dict, opponent_strength: int, recent_minutes: float) -> float:
    """Estimate an expected points delta (EPΔ) for a player.

    This is a simple, deterministic heuristic using public FPL fields:
    - Normalize `form` (string) to [0, 1] assuming a rough 0–10 range.
    - Normalize `ict_index` (string) to [0, 1] assuming a rough 0–20 range.
    - Combine as 0.6*form_n + 0.4*ict_n to capture both recent returns and involvement.
    - Minutes sustainability factor m = sigmoid((recent_minutes - 120) / 60).
      (>120 mins over the last ~2 GWs boosts confidence.)
    - Opponent difficulty d: weaker opponent => higher EPΔ.
      We map strength (1 best → 5 worst) using d = _norm(opponent_strength, 5, 1) which favors weaker foes.

    Returns
    - EPΔ = 6.0 * (0.6*form_n + 0.4*ict_n) * m * d
    """
    # Parse numeric fields from bootstrap element
    form_raw = player.get("form")
    ict_raw = player.get("ict_index")
    try:
        form = float(form_raw) if form_raw is not None else 0.0
    except (TypeError, ValueError):
        form = 0.0
    try:
        ict = float(ict_raw) if ict_raw is not None else 0.0
    except (TypeError, ValueError):
        ict = 0.0

    form_n = _norm(form, 0.0, 10.0)
    ict_n = _norm(ict, 0.0, 20.0)
    mix = 0.6 * form_n + 0.4 * ict_n

    m = _sigmoid((recent_minutes - 120.0) / 60.0)

    # Favor weaker opponents (higher strength number -> weaker team)
    d = _norm(float(opponent_strength), 5.0, 1.0)

    return 6.0 * mix * m * d


def captain_score(
    player: dict,
    fixture_row: dict,
    ownership_pct: float,
    mode: str = "safe",
) -> float:
    """Compute a captaincy score for a player given the next fixture and ownership.

    - Base score uses `expected_points_delta` with a simple recent-minutes proxy
      (min(total minutes, 180) to approximate last ~2 GWs when granular data is absent).
    - Ownership adjustment:
        - mode == "safe": + 0.15 * ownership_pct (reward template captains)
        - mode == "aggressive": - 0.10 * ownership_pct (reward differentials)
    - Home bonus: +5% if fixture_row["was_home"] is True.
    """
    recent_minutes = float(min(_nz(player.get("minutes"), 0.0), 180.0))
    opponent_strength = int(fixture_row.get("opponent_strength") or 3)

    base = expected_points_delta(player, opponent_strength, recent_minutes)

    adj = 0.0
    if mode == "safe":
        adj += 0.15 * _nz(ownership_pct, 0.0)
    elif mode == "aggressive":
        adj -= 0.10 * _nz(ownership_pct, 0.0)

    home_bonus = 0.05 if bool(fixture_row.get("was_home", False)) else 0.0

    return base * (1.0 + adj + home_bonus)


def aggregate_epdelta_for_fixtures(player: dict, fixtures_rows: List[dict], teams_idx: Dict[int, dict]) -> float:
    """Aggregate EPΔ across all given fixtures for a player.

    Adds a +10% bonus if there are multiple fixtures (DGW heuristic).
    """
    pid_minutes = float(min(_nz(player.get("minutes"), 0.0), 180.0))
    total = 0.0
    for fx in fixtures_rows:
        opp_strength = int((fx.get("opponent_strength") or 3))
        total += expected_points_delta(player, opp_strength, pid_minutes)
    if len(fixtures_rows) > 1:
        total *= 1.1
    return total


def choose_starting_xi(ep_by_player: Dict[int, float], positions: Dict[int, str]) -> Tuple[List[int], List[int]]:
    """Choose a legal XI with FPL minima/maxima and order bench.

    - Exactly one GK.
    - Outfield minima: DEF>=3, MID>=2, FWD>=1.
    - Fill remaining to 11 respecting MAX_BY_POS.
    Bench order: three outfield by ascending EP, GK last.
    """
    by_pos: Dict[str, List[Tuple[int, float]]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for pid, ep in ep_by_player.items():
        by_pos.setdefault(positions.get(pid, "MID"), []).append((pid, ep))
    for k in by_pos:
        by_pos[k].sort(key=lambda x: x[1], reverse=True)

    selected: List[int] = []
    counts: Dict[str, int] = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}

    # A) exactly one GK
    if by_pos["GK"]:
        gk = by_pos["GK"][0][0]
        selected.append(gk)
        counts["GK"] = 1

    # B) meet minima for outfield
    for pos in ("DEF", "MID", "FWD"):
        need = MIN_BY_POS[pos]
        pool = [pid for pid, _ in by_pos[pos] if pid not in selected]
        selected.extend(pool[:need])
        counts[pos] += min(len(pool), need)

    # C) fill remaining to 11 respecting MAX
    remaining_slots = 11 - len(selected)
    candidates: List[Tuple[int, float]] = [
        (pid, ep)
        for pos in ("DEF", "MID", "FWD")
        for pid, ep in by_pos[pos]
        if pid not in selected
    ]
    candidates.sort(key=lambda x: x[1], reverse=True)
    for pid, _ in candidates:
        if len(selected) >= 11:
            break
        pos = positions[pid]
        if counts[pos] < MAX_BY_POS[pos]:
            selected.append(pid)
            counts[pos] += 1

    # Bench = all others (order: outfield ascending EP, GK last)
    all_ids = list(ep_by_player.keys())
    bench = [pid for pid in all_ids if pid not in selected]
    outfield_bench = [pid for pid in bench if positions.get(pid) != "GK"]
    gk_bench = [pid for pid in bench if positions.get(pid) == "GK"]
    outfield_bench.sort(key=lambda pid: ep_by_player.get(pid, 0.0))
    bench_ordered = outfield_bench[:3] + gk_bench[:1]
    return selected, bench_ordered


def recommend_captain_from_ids(
    starting_ids: List[int],
    per_player_ep: Dict[int, float],
    ownership_idx: Dict[int, float],
    positions: Dict[int, str],
    mode: str = "safe",
) -> Tuple[int, int]:
    """Return (captain_id, vice_id) among starting picks using a simple heuristic.

    - Excludes GK
    - Scores by EPΔ adjusted by ownership preference depending on `mode`.
    - Falls back to top EPΔ if the best score has a very low base EPΔ (<0.8).
    """
    starters = [pid for pid in starting_ids if positions.get(pid) != "GK"]
    scored: List[Tuple[int, float, float]] = []  # (pid, score, base)
    for pid in starters:
        own = ownership_idx.get(pid, 0.0)
        base = float(per_player_ep.get(pid, 0.0))
        if mode == "safe":
            score = base * (1.0 + min(own, 80.0) / 100.0)
        else:
            score = base * (1.0 + max(0.0, (20.0 - min(own, 20.0))) / 25.0)
        scored.append((pid, score, base))
    if not scored:
        return 0, 0
    scored.sort(key=lambda x: x[1], reverse=True)
    top_pid, top_score, top_base = scored[0]
    if top_base < 0.8:
        top_pid = max(scored, key=lambda x: x[2])[0]
    vice_pid = next((pid for pid, _, _ in scored if pid != top_pid), 0)
    return top_pid, vice_pid


def evaluate_chips(per_player_ep: Dict[int, float], captain_id: int, bench_ids: List[int]) -> Dict[str, float]:
    """Estimate simple chip gains for Bench Boost and Triple Captain."""
    bench_ep = float(sum(per_player_ep.get(pid, 0.0) for pid in bench_ids))
    cap_ep = float(per_player_ep.get(captain_id, 0.0))
    return {"bench_boost_gain": bench_ep, "triple_captain_gain": cap_ep}


def plan_gameweek(
    picks: List[dict],
    elements: List[dict],
    teams: List[dict],
    fixtures_gw: List[dict],
    gw: int,
    ownership_idx: Dict[int, float],
    mode: str = "safe",
) -> dict:
    """Produce a compact plan for the given picks and GW fixtures.

    Computes per-player EPΔ across all GW fixtures, chooses an optimal XI respecting minima,
    estimates bench EP, and suggests captain/vice among the optimal XI using the chosen mode.
    """
    elem_by_id = {int(e.get("id")): e for e in elements}
    team_idx = {int(t.get("id")): t for t in teams}

    # Positions per player (for all picked players)
    positions: Dict[int, str] = {}
    for p in picks:
        eid = int(p.get("element"))
        e = elem_by_id.get(eid, {})
        positions[eid] = position_code(int(e.get("element_type", 0) or 0))

    # Fixtures per team in this GW
    fixtures_by_team: Dict[int, List[dict]] = {}
    for fx in fixtures_gw:
        team_h = int(fx.get("team_h", 0) or 0)
        team_a = int(fx.get("team_a", 0) or 0)
        fixtures_by_team.setdefault(team_h, []).append({
            "was_home": True,
            "opponent_team": team_a,
            "opponent_strength": int(team_idx.get(team_a, {}).get("strength", 3) or 3),
        })
        fixtures_by_team.setdefault(team_a, []).append({
            "was_home": False,
            "opponent_team": team_h,
            "opponent_strength": int(team_idx.get(team_h, {}).get("strength", 3) or 3),
        })

    # EPΔ per player (rounded to 2 decimals for output)
    ep_by_player: Dict[int, float] = {}
    for p in picks:
        eid = int(p.get("element"))
        e = elem_by_id.get(eid, {})
        team_id = int(e.get("team", 0) or 0)
        fx_rows = fixtures_by_team.get(team_id, [])
        ep = aggregate_epdelta_for_fixtures(e, fx_rows, team_idx)
        ep_by_player[eid] = round(float(ep), 2)

    # Current start/bench from picks
    current_start = [int(p.get("element")) for p in picks if int(p.get("multiplier", 0)) > 0]
    current_bench = [int(p.get("element")) for p in picks if int(p.get("multiplier", 0)) <= 0]
    # Coerce to legal: if >1 GK in current XI, bench lower-EP GK and promote best outfielder from bench
    current_gks = [pid for pid in current_start if positions.get(pid) == "GK"]
    if len(current_gks) > 1:
        # keep highest EP GK
        current_gks.sort(key=lambda pid: ep_by_player.get(pid, 0.0), reverse=True)
        keep = current_gks[0]
        for g in current_gks[1:]:
            current_start.remove(g)
            current_bench.append(g)
        # promote best outfielder from bench
        outfield_bench = [pid for pid in current_bench if positions.get(pid) != "GK"]
        outfield_bench.sort(key=lambda pid: ep_by_player.get(pid, 0.0), reverse=True)
        for pid in outfield_bench:
            if pid not in current_start and len(current_start) < 11:
                current_start.append(pid)
                current_bench.remove(pid)
                break

    # Optimal XI and bench
    optimal_start, optimal_bench = choose_starting_xi(ep_by_player, positions)

    # Formation strings (exclude GK from outfield counts)
    formation_current = formation_str(current_start, positions)
    formation_optimal = formation_str(optimal_start, positions)

    ep_total_current = sum(ep_by_player.get(i, 0.0) for i in current_start)
    ep_total_optimal = sum(ep_by_player.get(i, 0.0) for i in optimal_start)
    ep_gain_lineup = ep_total_optimal - ep_total_current
    bench_ep_total = sum(ep_by_player.get(i, 0.0) for i in optimal_bench)

    # Choose captain/vice among optimal XI
    captain, vice = recommend_captain_from_ids(optimal_start, ep_by_player, ownership_idx, positions, mode=mode)

    # Chip evaluation
    chip_eval = evaluate_chips(ep_by_player, captain, optimal_bench)

    # Build machine-readable actions and summary
    # Current captain/vice from manager picks (if present)
    curr_cap = next((int(p.get("element")) for p in picks if p.get("is_captain")), None)
    curr_vc = next((int(p.get("element")) for p in picks if p.get("is_vice_captain")), None)

    # Greedy pairing of start_in vs bench_out by EP gain
    start_in = [pid for pid in optimal_start if pid not in current_start]
    bench_out = [pid for pid in current_start if pid not in optimal_start]
    pairs: List[Tuple[int, int, float]] = []  # (in, out, delta)
    for i in start_in:
        for o in bench_out:
            delta = ep_by_player.get(i, 0.0) - ep_by_player.get(o, 0.0)
            if delta >= 0.20:
                pairs.append((i, o, delta))
    pairs.sort(key=lambda t: t[2], reverse=True)
    # Greedy legality-preserving selection of swaps
    def is_legal_start(starters: List[int]) -> bool:
        if len(starters) != 11:
            return False
        g = sum(1 for pid in starters if positions.get(pid) == "GK")
        d = sum(1 for pid in starters if positions.get(pid) == "DEF")
        m = sum(1 for pid in starters if positions.get(pid) == "MID")
        f = sum(1 for pid in starters if positions.get(pid) == "FWD")
        if g != 1:
            return False
        if d < MIN_BY_POS["DEF"] or m < MIN_BY_POS["MID"] or f < MIN_BY_POS["FWD"]:
            return False
        if d > MAX_BY_POS["DEF"] or m > MAX_BY_POS["MID"] or f > MAX_BY_POS["FWD"]:
            return False
        return True

    chosen_pairs: List[Tuple[int, int, float]] = []
    used_in: set[int] = set()
    used_out: set[int] = set()
    trial_start = list(current_start)
    for i, o, d in pairs:
        if i in used_in or o in used_out:
            continue
        # apply tentative swap
        nxt = [pid for pid in trial_start if pid != o]
        nxt.append(i)
        if is_legal_start(nxt):
            chosen_pairs.append((i, o, d))
            used_in.add(i)
            used_out.add(o)
            trial_start = nxt

    # Name lookup map
    id_to_name: Dict[int, str] = {}
    for e in elements:
        try:
            pid = int(e.get("id"))
        except Exception:
            continue
        nm = e.get("web_name") or str(pid)
        id_to_name[pid] = nm

    actions: List[dict] = []
    incoming_names: List[str] = []
    outgoing_names: List[str] = []
    # Bundle id for lineup swaps
    bundle_id = f"lineup-{gw}-1"
    prio = 10
    for i, o, d in chosen_pairs:
        nm_in = id_to_name.get(i, str(i))
        nm_out = id_to_name.get(o, str(o))
        incoming_names.append(nm_in)
        outgoing_names.append(nm_out)
        ep_in = round(ep_by_player.get(i, 0.0), 2)
        ep_out = round(ep_by_player.get(o, 0.0), 2)
        # Factors from in player's context
        in_team = int(elem_by_id.get(i, {}).get("team", 0) or 0)
        in_fx = (fixtures_by_team.get(in_team) or [{}])[0] if fixtures_by_team.get(in_team) else {}
        in_home = in_fx.get("was_home")
        in_opp_str = in_fx.get("opponent_strength")
        try:
            in_form = float(elem_by_id.get(i, {}).get("form", 0.0) or 0.0)
        except (TypeError, ValueError):
            in_form = 0.0
        factors = {
            "home": bool(in_home) if in_home is not None else None,
            "opp_strength": int(in_opp_str) if in_opp_str is not None else None,
            "form": round(in_form, 1),
        }
        # Build fixture contexts (single representative fixture)
        out_team = int(elem_by_id.get(o, {}).get("team", 0) or 0)
        out_fx = (fixtures_by_team.get(out_team) or [{}])[0] if fixtures_by_team.get(out_team) else {}
        in_fixture = {
            "opponent_team_id": int(in_fx.get("opponent_team")) if in_fx.get("opponent_team") is not None else None,
            "opponent_strength": int(in_fx.get("opponent_strength")) if in_fx.get("opponent_strength") is not None else None,
            "was_home": bool(in_fx.get("was_home")) if in_fx.get("was_home") is not None else None,
        }
        out_fixture = {
            "opponent_team_id": int(out_fx.get("opponent_team")) if out_fx.get("opponent_team") is not None else None,
            "opponent_strength": int(out_fx.get("opponent_strength")) if out_fx.get("opponent_strength") is not None else None,
            "was_home": bool(out_fx.get("was_home")) if out_fx.get("was_home") is not None else None,
        }
        action = {
            "type": "swap",
            "action_group": "lineup",
            "priority": prio,
            "bundle_id": bundle_id,
            "in_player": int(i),
            "out_player": int(o),
            "ep_in": ep_in,
            "ep_out": ep_out,
            "delta_ep": round(float(d), 2),
            "reason_code": "higher_ep",
            "factors": {k: v for k, v in factors.items() if v is not None},
            "reason": f"EP_diff {ep_out:.2f} -> {ep_in:.2f}; form {in_form:.1f}",
            "in_fixture": {k: v for k, v in in_fixture.items() if v is not None},
            "out_fixture": {k: v for k, v in out_fixture.items() if v is not None},
        }
        actions.append(action)
        prio += 1

    if captain and captain != curr_cap:
        delta_cap = round(float(ep_by_player.get(captain, 0.0) - (ep_by_player.get(curr_cap, 0.0) if curr_cap else 0.0)), 2)
        actions.append({
            "type": "set_captain",
            "action_group": "captaincy",
            "priority": 50,
            "player": int(captain),
            "old_player": int(curr_cap) if curr_cap else None,
            "reason_code": "highest_captain_score",
            "reason": f"Highest captain score in mode={mode}",
            "ep_new": round(ep_by_player.get(captain, 0.0), 2),
            "ep_old": round(ep_by_player.get(curr_cap, 0.0), 2) if curr_cap else None,
            "delta_ep": delta_cap,
            "captain_mode": mode,
        })
    if vice and vice != curr_vc:
        actions.append({
            "type": "set_vice",
            "action_group": "captaincy",
            "priority": 60,
            "player": int(vice),
            "old_player": int(curr_vc) if curr_vc else None,
            "reason_code": "second_best_captain",
            "reason": "Second-best captain",
        })

    # Chip suggestion
    bench_boost_threshold = 12.0
    triple_captain_threshold = 4.0
    chip_type = "NONE"
    why_code = "below_threshold"
    if chip_eval.get("bench_boost_gain", 0.0) >= bench_boost_threshold:
        chip_type = "BB"
        why_code = "bench_boost_value"
    elif chip_eval.get("triple_captain_gain", 0.0) >= triple_captain_threshold:
        chip_type = "TC"
        why_code = "triple_captain_value"
    chip_action = {
        "type": "chip",
        "action_group": "chip",
        "priority": 90,
        "chip": chip_type,
        "reason": "Chip evaluation",
        "details": {
            "bench_boost_gain": round(float(chip_eval.get("bench_boost_gain", 0.0)), 2),
            "triple_captain_gain": round(float(chip_eval.get("triple_captain_gain", 0.0)), 2),
            "bench_boost_threshold": bench_boost_threshold,
            "triple_captain_threshold": triple_captain_threshold,
        },
    }
    if why_code == "below_threshold":
        chip_action["reason_code"] = "below_threshold"
    actions.append(chip_action)

    # Build concise summary
    parts: List[str] = []
    if incoming_names and outgoing_names:
        parts.append("Start " + ", ".join(incoming_names) + " and bench " + ", ".join(outgoing_names))
    elif incoming_names:
        parts.append("Start " + ", ".join(incoming_names))
    elif outgoing_names:
        parts.append("Bench " + ", ".join(outgoing_names))
    if captain:
        parts.append(f"Captain {id_to_name.get(captain, str(captain))} ({mode})")
    parts.append(f"Chip: {chip_type}")
    summary = ". ".join(parts) + "."
    # Long summary paragraph
    long_parts: List[str] = []
    for i, o, d in chosen_pairs:
        long_parts.append(
            f"Start {id_to_name.get(i, str(i))} for {id_to_name.get(o, str(o))} (+{round(d,2):.2f} EP)."
        )
    if captain and captain != curr_cap:
        long_parts.append(
            f"Captain {id_to_name.get(captain, str(captain))} over {id_to_name.get(curr_cap, str(curr_cap)) if curr_cap else 'none'} (+{round(delta_cap,2):.2f} EP) in {mode} mode."
        )
    bb_gain = round(float(chip_eval.get("bench_boost_gain", 0.0)), 2)
    tc_gain = round(float(chip_eval.get("triple_captain_gain", 0.0)), 2)
    if chip_type == "NONE":
        long_parts.append(
            f"No chip - bench adds +{bb_gain:.2f} EP below {bench_boost_threshold:.0f}."
        )
    elif chip_type == "BB":
        long_parts.append(
            f"Chip BB: bench adds +{bb_gain:.2f} EP (>= {bench_boost_threshold:.0f})."
        )
    else:  # TC
        long_parts.append(
            f"Chip TC: captain extra +{tc_gain:.2f} EP (>= {triple_captain_threshold:.0f})."
        )
    summary_long = " ".join(long_parts)

    # prune None values in actions
    pruned_actions: List[dict] = []
    for a in actions:
        pruned_actions.append({k: v for k, v in a.items() if v is not None})

    return {
        "formation_current": formation_current,
        "formation_optimal": formation_optimal,
        "current_start": current_start,
        "current_bench": current_bench,
        "optimal_start": optimal_start,
        "optimal_bench": optimal_bench,
        "captain": int(captain),
        "vice_captain": int(vice),
        "ep_total_current": float(ep_total_current),
        "ep_total_optimal": float(ep_total_optimal),
        "ep_gain_lineup": float(ep_gain_lineup),
        "bench_ep_total": float(bench_ep_total),
        "chip_eval": chip_eval,
        "per_player_ep": ep_by_player,
        "actions": pruned_actions,
        "summary": summary,
        "summary_long": summary_long,
    }


def template_vs_differential(
    picks: List[dict], ownership: Dict[int, float], threshold: float = 20.0
) -> dict:
    """Summarize template vs differential composition for a set of picks.

    - Counts picks with ownership >= threshold as template, otherwise differential.
    - Returns counts and the template ratio (template_count / total).
    """
    template_count = 0
    differential_count = 0
    for p in picks:
        pid = int(p.get("element"))
        own = _nz(ownership.get(pid, 0.0), 0.0)
        if own >= threshold:
            template_count += 1
        else:
            differential_count += 1

    total = template_count + differential_count
    ratio = (template_count / total) if total else 0.0
    return {
        "template_count": template_count,
        "differential_count": differential_count,
        "template_ratio": ratio,
    }


def link_fixtures_for_manager(
    gw: int,
    picks: List[dict],
    fixtures: List[dict],
    elements: List[dict],
    teams: List[dict],
) -> List[dict]:
    """Attach fixture context to manager picks for a given GW.

    For each pick:
    - Identify the player (`elements`) and their team id.
    - Find the team's fixture in `fixtures` for the given `gw`.
      If multiple (double GW), the first encountered is used (v1 heuristic).
    - Build a `fixture_row` with:
        - was_home (bool)
        - opponent_team (int | None)
        - opponent_strength (int | None)
    Returns a list of per-pick dicts including original pick fields plus `player` and `fixture_row`.
    """
    elem_by_id = {int(e.get("id")): e for e in elements}
    team_strength = {int(t.get("id")): int(t.get("strength", 3)) for t in teams}

    # Index fixtures by event and participating team id for quick lookup
    fixtures_by_event: Dict[int, List[dict]] = {}
    for f in fixtures:
        ev = f.get("event")
        if ev is None:
            continue
        fixtures_by_event.setdefault(int(ev), []).append(f)

    out: List[dict] = []
    gw_fixtures = fixtures_by_event.get(int(gw), [])
    for pick in picks:
        pid = int(pick.get("element"))
        player = elem_by_id.get(pid)
        if not player:
            out.append({**pick, "player": None, "fixture_row": {}})
            continue

        team_id = int(player.get("team", 0) or 0)
        chosen: Optional[dict] = None
        was_home = False
        opponent_team: Optional[int] = None
        opponent_strength: Optional[int] = None

        for f in gw_fixtures:
            th = int(f.get("team_h", -1))
            ta = int(f.get("team_a", -1))
            if team_id == th:
                chosen = f
                was_home = True
                opponent_team = ta
                break
            if team_id == ta:
                chosen = f
                was_home = False
                opponent_team = th
                break

        if opponent_team is not None:
            opponent_strength = team_strength.get(int(opponent_team))

        fixture_row = {
            "was_home": was_home,
            "opponent_team": opponent_team,
            "opponent_strength": opponent_strength,
        }

        out.append({**pick, "player": player, "fixture_row": fixture_row})

    return out


def ownership_index(elements: List[dict]) -> Dict[int, float]:
    """Build a mapping from element id -> selected_by_percent (float)."""
    idx: Dict[int, float] = {}
    for e in elements:
        pid = int(e.get("id"))
        raw = e.get("selected_by_percent")
        try:
            idx[pid] = float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            idx[pid] = 0.0
    return idx


def recommend_captain(
    pick_rows: List[dict], ownership_idx: Dict[int, float], mode: str
) -> Tuple[int, float]:
    """Recommend a captain from starting XI picks using `captain_score`.

    Expects `pick_rows` produced by `link_fixtures_for_manager`, so each row
    contains `player` and `fixture_row`.
    Returns (element_id, score) for the best candidate. If no candidates found,
    returns (0, 0.0).
    """
    best_elem = 0
    best_score = 0.0
    for row in pick_rows:
        if int(row.get("multiplier", 0)) <= 0:
            continue  # bench
        player = row.get("player")
        fixture_row = row.get("fixture_row", {})
        if not player or not fixture_row:
            continue
        pid = int(row.get("element"))
        own = ownership_idx.get(pid, 0.0)
        score = captain_score(player, fixture_row, own, mode=mode)
        if score > best_score:
            best_score = score
            best_elem = pid
    return best_elem, best_score


def suggest_transfers(
    pick_rows: List[dict],
    elements: List[dict],
    ownership_idx: Dict[int, float],
    mode: str = "aggressive",
    bank: int = 0,
    bank_allowance: int = 0,
) -> List[dict]:
    """Suggest FPL-legal transfers based on EPΔ and constraints.

    Rules:
    - Consider bottom-3 EPΔ from starting XI (multiplier > 0) as sell candidates.
    - For replacements, consider players not in current squad, same position, team cap (<=3),
      and budget: (in_cost - out_cost) <= bank + bank_allowance. `bank_allowance` can be 4
      when allowing a -4 hit, interpreted as 0.4m deficit in 0.1m units.
    - EPΔ for candidates is computed with neutral opponent strength=3 and minutes proxy.
    Returns a list of dicts with `out`, `in`, `epdelta_out`, `epdelta_in`, `reason`.
    """
    # Build quick indexes
    elem_by_id = {int(e.get("id")): e for e in elements}

    def player_meta(element_id: int) -> dict:
        e = elem_by_id.get(int(element_id), {})
        return {
            "now_cost": int(e.get("now_cost", 0) or 0),
            "element_type": int(e.get("element_type", 0) or 0),
            "team": int(e.get("team", 0) or 0),
            "form": e.get("form"),
            "minutes": e.get("minutes"),
        }

    def position_code(element_type: int) -> str:
        return {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(int(element_type), "MID")

    # Current squad state
    squad_ids = {int(p.get("element")) for p in pick_rows}
    team_counts: Dict[int, int] = {}
    for pid in squad_ids:
        tm = player_meta(pid)["team"]
        team_counts[tm] = team_counts.get(tm, 0) + 1

    # EPΔ for starting XI only
    current_scored: List[Tuple[int, float]] = []
    for row in pick_rows:
        if int(row.get("multiplier", 0)) <= 0:
            continue
        player = row.get("player")
        fx = row.get("fixture_row", {})
        if not player or not fx:
            continue
        opp = int(fx.get("opponent_strength") or 3)
        minutes_proxy = float(min(_nz(player.get("minutes"), 0.0), 180.0))
        epd = expected_points_delta(player, opp, minutes_proxy)
        current_scored.append((int(row.get("element")), epd))

    # Identify bottom 3 to replace
    current_scored.sort(key=lambda t: t[1])
    to_replace = [e for e, _ in current_scored[:3]]

    # Precompute candidate scores (neutral opponent)
    neutral_opp = 3
    candidate_scores: Dict[int, float] = {}
    for e in elements:
        pid = int(e.get("id"))
        if pid in squad_ids:
            continue
        minutes_proxy = float(min(_nz(e.get("minutes"), 0.0), 180.0))
        candidate_scores[pid] = expected_points_delta(e, neutral_opp, minutes_proxy)

    suggestions: List[dict] = []
    allowance = int(bank_allowance)
    for out_id in to_replace:
        out_meta = player_meta(out_id)
        out_pos = position_code(out_meta["element_type"])
        out_cost = out_meta["now_cost"]
        out_team = out_meta["team"]
        out_epd = next((v for pid, v in current_scored if pid == out_id), 0.0)

        # Filter legal candidates by constraints
        legal_candidates: List[Tuple[int, float]] = []
        for in_id, in_epd in candidate_scores.items():
            in_meta = player_meta(in_id)
            if position_code(in_meta["element_type"]) != out_pos:
                continue
            in_team = in_meta["team"]
            # Team cap check (allow swap within same team)
            team_count = team_counts.get(in_team, 0)
            if in_team != out_team and team_count >= 3:
                continue
            # Budget check
            in_cost = in_meta["now_cost"]
            if (in_cost - out_cost) > (int(bank) + allowance):
                continue
            # Prefer clear upgrades
            if in_epd <= out_epd:
                continue
            legal_candidates.append((in_id, in_epd))

        if not legal_candidates:
            continue
        # Choose best upgrade
        legal_candidates.sort(key=lambda t: t[1], reverse=True)
        in_id, in_epd = legal_candidates[0]

        # Reason string referencing opponent/minutes/form
        in_form = elem_by_id.get(in_id, {}).get("form")
        reason = f"Upgrade EPΔ {out_epd:.2f} -> {in_epd:.2f}; in-form {in_form}"
        suggestions.append({
            "out": int(out_id),
            "in": int(in_id),
            "epdelta_out": float(out_epd),
            "epdelta_in": float(in_epd),
            "reason": reason,
        })

        # Update squad state: replace out with in for subsequent checks
        squad_ids.discard(out_id)
        squad_ids.add(in_id)
        # Adjust team counts
        team_counts[out_team] = max(0, team_counts.get(out_team, 0) - 1)
        team_counts[in_meta["team"]] = team_counts.get(in_meta["team"], 0) + 1
        # Adjust bank
        bank = int(bank) - (in_meta["now_cost"] - out_cost)

    return suggestions
