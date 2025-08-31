from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel
from typing import Any, Literal, Union, Optional


class HealthResponse(BaseModel):
    status: Literal["ok"]


class BootstrapPlayer(BaseModel):
    """Subset of player fields used by this service.

    Note: FPL API returns some numeric-looking fields as strings (e.g., form, ict_index).
    """

    id: int
    web_name: str
    now_cost: int
    form: str
    ict_index: str
    minutes: int
    team: int


class BootstrapTeam(BaseModel):
    id: int
    name: str
    strength: int


class Fixture(BaseModel):
    id: int
    event: Optional[int] = None
    team_h: int
    team_a: int


class ManagerPick(BaseModel):
    element: int
    is_captain: bool
    is_vice_captain: bool
    multiplier: int


class ManagerPicks(BaseModel):
    picks: list[ManagerPick]
    picks_expanded: list[PicksExpandedItem] | None = None


class BootstrapSlim(BaseModel):
    """Slim view of bootstrap data with only the fields we use."""

    teams: list[BootstrapTeam]
    players: list[BootstrapPlayer]


class FixturesResponse(BaseModel):
    fixtures: list[Fixture]


class PickNote(BaseModel):
    element: int
    is_captain: bool
    is_vice_captain: bool


class CaptainCandidate(BaseModel):
    element: int
    score: float


class TemplateDifferential(BaseModel):
    template_count: int
    differential_count: int
    template_ratio: float


class GWManagerSummary(BaseModel):
    gw: int
    picks: list[PickNote]
    template_vs_differential: TemplateDifferential
    captain_candidates: list[CaptainCandidate]
    picks_expanded: list[PicksExpandedItem] | None = None
    captain_candidates_expanded: list[CaptainCandidateExpanded] | None = None


class PlayerRefExpanded(BaseModel):
    id: int
    name: str | None = None
    team_id: int | None = None
    team_name: str | None = None
    position: str | None = None
    now_cost: int | None = None
    ownership_pct: float | None = None


class FixtureCtxExpanded(BaseModel):
    opponent_team_id: int | None = None
    opponent_team_name: str | None = None
    opponent_strength: int | None = None
    was_home: bool | None = None


class PicksExpandedItem(BaseModel):
    player: PlayerRefExpanded
    is_captain: bool
    is_vice_captain: bool
    fixture: FixtureCtxExpanded | None = None


class CaptainCandidateExpanded(BaseModel):
    player: PlayerRefExpanded
    score: float


class EPDeltaExpandedRow(BaseModel):
    player: PlayerRefExpanded
    epdelta: float
    fixture: FixtureCtxExpanded | None = None


class TransferSuggestionExpanded(BaseModel):
    out: PlayerRefExpanded
    in_: PlayerRefExpanded
    reason: str
    epdelta_gain: float


class ActionBase(BaseModel):
    type: Literal["swap", "set_captain", "set_vice", "chip"]
    action_group: Literal["lineup", "captaincy", "chip"]
    priority: int
    bundle_id: str | None = None


class CompactFixtureCtx(BaseModel):
    opponent_team_id: int
    opponent_strength: int
    was_home: bool


class SwapAction(ActionBase):
    type: Literal["swap"] = "swap"
    action_group: Literal["lineup"] = "lineup"
    in_player: int
    out_player: int
    ep_in: float
    ep_out: float
    delta_ep: float
    why: str | None = None
    reason_code: Literal["higher_ep"] = "higher_ep"
    factors: dict | None = None  # {home:bool, opp_strength:int, form:float}
    in_fixture: CompactFixtureCtx | None = None
    out_fixture: CompactFixtureCtx | None = None


class SetCaptainAction(ActionBase):
    type: Literal["set_captain"] = "set_captain"
    action_group: Literal["captaincy"] = "captaincy"
    player: int
    old_player: int | None = None
    ep_new: float
    ep_old: float | None = None
    delta_ep: float
    captain_mode: Literal["safe", "aggressive"]
    reason_code: Literal["highest_captain_score"] = "highest_captain_score"


class SetViceAction(ActionBase):
    type: Literal["set_vice"] = "set_vice"
    action_group: Literal["captaincy"] = "captaincy"
    player: int
    old_player: int | None = None
    reason_code: Literal["second_best_captain"] = "second_best_captain"


class ChipAction(ActionBase):
    type: Literal["chip"] = "chip"
    action_group: Literal["chip"] = "chip"
    chip: Literal["BB", "TC", "FH", "WC", "NONE"]
    # reason_code optional; when chip == NONE should be 'below_threshold'
    reason_code: Optional[Literal["below_threshold"]] = None
    details: dict | None = None  # {bench_boost_gain, triple_captain_gain, bench_boost_threshold, triple_captain_threshold}


# Expanded action variants
class SwapActionExpanded(ActionBase):
    type: Literal["swap"] = "swap"
    action_group: Literal["lineup"] = "lineup"
    in_player: PlayerRefExpanded
    out_player: PlayerRefExpanded
    ep_in: float
    ep_out: float
    delta_ep: float
    reason_code: Literal["higher_ep"] = "higher_ep"
    factors: dict | None = None
    in_fixture: FixtureCtxExpanded | None = None
    out_fixture: FixtureCtxExpanded | None = None


class SetCaptainActionExpanded(ActionBase):
    type: Literal["set_captain"] = "set_captain"
    action_group: Literal["captaincy"] = "captaincy"
    player: PlayerRefExpanded
    old_player: PlayerRefExpanded | None = None
    ep_new: float
    ep_old: float | None = None
    delta_ep: float
    captain_mode: Literal["safe", "aggressive"]
    reason_code: Literal["highest_captain_score"] = "highest_captain_score"


class SetViceActionExpanded(ActionBase):
    type: Literal["set_vice"] = "set_vice"
    action_group: Literal["captaincy"] = "captaincy"
    player: PlayerRefExpanded
    old_player: PlayerRefExpanded | None = None
    reason_code: Literal["second_best_captain"] = "second_best_captain"


class ChipActionExpanded(ActionBase):
    type: Literal["chip"] = "chip"
    action_group: Literal["chip"] = "chip"
    chip: Literal["BB", "TC", "FH", "WC", "NONE"]
    reason_code: Optional[Literal["below_threshold"]] = None
    details: dict | None = None


class GWPlannerLite(BaseModel):
    gw: int
    picks_gw_used: int | None = None
    formation_current: str
    formation_optimal: str
    current_start: list[int]
    current_bench: list[int]
    optimal_start: list[int]
    optimal_bench: list[int]
    captain: int
    vice_captain: int
    ep_total_current: float
    ep_total_optimal: float
    ep_gain_lineup: float
    bench_ep_total: float
    chip_eval: dict
    per_player_ep: dict[int, float]


class PlannerAction(BaseModel):
    type: Literal["start", "bench", "set_captain", "set_vice", "chip", "swap"]
    # Generic fields for actions
    player: int | None = None
    old_player: int | None = None
    in_player: int | None = None
    out_player: int | None = None
    chip: Literal["BB", "TC", "FH", "WC", "NONE"] | None = None
    reason_code: str | None = None
    reason: str
    why: str | None = None
    delta_ep: float | None = None
    ep_in: float | None = None
    ep_out: float | None = None
    ep_new: float | None = None
    ep_old: float | None = None
    factors: list[str] | None = None


class PlannerPlayerSlot(BaseModel):
    player: PlayerRefExpanded
    fixture: FixtureCtxExpanded | None = None
    epdelta: float
    is_captain: bool
    is_vice_captain: bool


ActionCompact = Union[SwapAction, SetCaptainAction, SetViceAction, ChipAction]
ActionExpanded = Union[
    SwapActionExpanded,
    SetCaptainActionExpanded,
    SetViceActionExpanded,
    ChipActionExpanded,
]


class GWPlannerResponse(BaseModel):
    schema_version: str | None = None
    generated_at: str | None = None
    meta: dict[str, Any] | None = None
    data: GWPlannerLite
    # top-level actions and summaries
    actions: list[ActionCompact] | None = None
    actions_expanded: list[ActionExpanded] | None = None
    summary: str | None = None
    summary_long: str | None = None
    current_expanded: list[PlannerPlayerSlot] | None = None
    optimal_expanded: list[PlannerPlayerSlot] | None = None
    bench_expanded: list[PlannerPlayerSlot] | None = None
    transfer_suggestions: list[TransferSuggestion] | None = None
    transfer_suggestions_expanded: list[TransferSuggestionExpanded] | None = None


class NamesIndexPlayer(BaseModel):
    name: str | None = None
    team_id: int | None = None
    team_name: str | None = None
    position: str | None = None


class NamesIndex(BaseModel):
    players: dict[int, NamesIndexPlayer]
    teams: dict[int, str | None]


class EPDeltaRow(BaseModel):
    element: int
    epdelta: float
    opponent_team: Optional[int] = None
    opponent_strength: Optional[int] = None
    was_home: Optional[bool] = None


class TransferSuggestion(BaseModel):
    out_element: int
    in_element: int
    reason: str
    epdelta_gain: float


class GWManagerAnalysis(BaseModel):
    gw: int
    recommended_captain_safe: CaptainCandidate
    recommended_captain_aggressive: CaptainCandidate
    epdeltas: list[EPDeltaRow]
    transfer_suggestions: list[TransferSuggestion]
    epdeltas_expanded: list[EPDeltaExpandedRow] | None = None
    recommended_captain_safe_expanded: CaptainCandidateExpanded | None = None
    recommended_captain_aggressive_expanded: CaptainCandidateExpanded | None = None
    transfer_suggestions_expanded: list[TransferSuggestionExpanded] | None = None
