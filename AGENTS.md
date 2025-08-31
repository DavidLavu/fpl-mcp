# MCP Planner

This service exposes a Gameweek Planner endpoint that optimizes your XI, bench, and captain/vice for a given gameweek.

## Endpoint

- GET `/tools/get_gameweek_planner/{tid}/{gw}`
  - Query params:
    - `expand` (bool, default `false`): Include LLM-ready player slots.
    - `mode` (`safe`|`aggressive`, default `safe`): Captain preference.
    - `include_transfers` (bool, default `true`): Attach legal transfer suggestions.
    - `allow_hit` (bool, default `false`): Allow up to 0.4m budget deficit (simulating -4).
    - `bank_override` (int, optional): Override bank in 0.1m units.

## Examples

- Compact:
  - `/tools/get_gameweek_planner/1654757/3`
- Expanded, aggressive, include transfers, no hit:
  - `/tools/get_gameweek_planner/1654757/3?expand=true&mode=aggressive&include_transfers=true&allow_hit=false`

The expanded payload includes denormalized player and fixture context for each slot and expanded transfer suggestions.
