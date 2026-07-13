---
name: genvid-budgeting
description: Build and export a production budget from a project's scenes and shots.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Production Budgeting

The production budgeting workflow builds a structured budget and shoot schedule from the project's existing breakdown and storyboard, then lets you explore what-if scenarios and export to EP MMB for use in standard production tools. This skill contains no rate tables, no tenant-specific pricing, and no budget math — all computation lives inside the governed boundary, which applies the inputs you provide and returns computed results.

For OMC terminology used throughout this skill, see `../../references/omc-vocabulary.md`.

---

## Before you start — read the breakdown

Budget lines are grounded in the production breakdown. Before creating a budget, read the scenes and shots that breakdown has produced.

```
scenes_read(method=list, project_id=<project_id>)
shots_read(method=list, project_id=<project_id>)
```

Use the scene count, location spread, and storyboard to inform which budget accounts need lines and at what scale. Never invent budget structure independent of the breakdown — the breakdown is the authoritative scope of the production.

---

## Creating the budget

### Initialize the budget header

Use `create_production_budget` to set up the budget for a project. Each project has at most one budget.

```
create_production_budget(project_id=<project_id>, base_currency=<currency>, contingency_rate=<rate>)
```

| Parameter | What to supply |
|---|---|
| `project_id` | The identifier of the project |
| `base_currency` | ISO 4217 currency code — e.g. `"USD"`, `"EUR"`. Defaults to `"USD"` if omitted |
| `contingency_rate` | Contingency as a decimal fraction (0–1) — e.g. `0.10` for 10 %. Defaults to `0.0` |

`create_production_budget` is an `additive`-classified tool. Call it normally; your MCP client prompts you to allow it. See `genvid-boundary-gate`.

### Create the shoot schedule

The shoot schedule is the spine of a production budget — "the schedule is the budget." Create it right after the budget header so below-the-line labor lines can reference the computed shoot-day count.

```
create_shoot_schedule(project_id=<project_id>, base_currency=<currency>, budget_id=<budget_id>)
```

| Parameter | What to supply |
|---|---|
| `project_id` | The identifier of the project |
| `base_currency` | ISO 4217 currency code — match the budget's currency. Defaults to `"USD"` |
| `budget_id` | The `id` returned by `create_production_budget`. Linking the schedule to the budget emits the `SHOOT_DAYS` global, which labor lines reference |

The shoot-day count is computed by the boundary from the project's scenes — you do not supply it. A project with no scenes yields `total_days = 0`; that is expected, not an error.

After creating the schedule, read it back with `get_shoot_schedule(project_id=<project_id>)` to surface `total_days`, the ordered shoot days, and the `company_moves` count to the user.

`create_shoot_schedule` is an `additive`-classified tool; `get_shoot_schedule` is `read_only`. Use `update_shoot_schedule(project_id=<project_id>, base_currency=<currency>)` only to change the schedule's currency. See `genvid-boundary-gate`.

### Add budget lines

Use `add_budget_lines` to populate the budget with detail lines. Pass one or more lines in a single call.

```
add_budget_lines(project_id=<project_id>, lines=[<line>, ...])
```

Each entry in the `lines` array:

| Field | What to supply |
|---|---|
| `account_id` | The budget account to add the line under. Call `get_production_budget` after header creation to see account IDs in the rollup |
| `description` | Human-readable label for this line |
| `amt` | Amount / quantity (e.g. number of days, units) |
| `x` | First multiplier (e.g. number of crew members) |
| `rate` | Unit rate — sourced from publicly available references or user-confirmed figures; see Data boundary below |
| `x4` | Secondary multiplier (e.g. shoot weeks) |
| `fringeable` | Marks the line as *eligible* for fringe (defaults `true`). Eligibility alone adds nothing — fringe is applied only to the specific fringes you attach via `fringe_ids` below. Never fold fringe into the `rate` by hand |
| `fringe_ids` | IDs of budget fringes to attach to this line (employer burden, union pension & health, etc.). The boundary computes each attached fringe against the line subtotal and sums them into the line's fringe total. All IDs must belong to this budget. Omit for a non-fringed line |
| `source_note` | Where the rate figure comes from (e.g. `"IATSE Local 600 Basic Agreement 2025"`) |
| `confidence` | Estimate confidence: `"firm"`, `"quoted"`, `"estimated"`, or `"allowance"` |

The boundary computes the line total from the values you pass; returned line records carry the boundary's computed values, which are canonical.

**Fringe application is explicit, not automatic.** A `fringeable=true` line with no `fringe_ids` contributes **zero** fringe to the topsheet — `fringeable` is an eligibility gate, not an auto-applier. Attach the fringes that apply to each labor line (e.g. FICA/Medicare, union pension & health) via `fringe_ids`, or the budget will silently under-represent employer burden. **Known V0 limitation:** the boundary does not yet expose a read tool for a budget's seeded fringe library, so the fringe IDs required by `fringe_ids` are not currently discoverable through the skill — until that lands (#1825), fringe totals reflect only fringes attached out-of-band.

`add_budget_lines` is an `additive`-classified tool. Call it normally; your MCP client prompts you to allow it. See `genvid-boundary-gate`.

---

## Reading the topsheet

Use `get_production_budget` to retrieve the fully-computed topsheet after lines are added or updated.

```
get_production_budget(project_id=<project_id>)
```

| Parameter | What to supply |
|---|---|
| `project_id` | The identifier of the project whose budget to read |

`get_production_budget` is a `read_only`-classified tool. It runs immediately, free.

Present the topsheet to the user with:
- Section totals: ATL (above-the-line), BTL (below-the-line), POST, and OTHER
- Contingency amount and grand total
- Per-account rollups — for each account, surface the account name, subtotal, fringe total, and account total alongside the `source_note` and `confidence` values from the lines beneath it

Always present `source_note` and `confidence` alongside dollar figures so the user can distinguish firm quotes from allowances at a glance.

---

## What-if scenarios — budget levers

Use `apply_budget_lever` to answer "what happens if" questions about contingency or currency without requiring the user to manually re-read the topsheet afterward.

```
apply_budget_lever(project_id=<project_id>, contingency_rate=<rate>, base_currency=<currency>)
```

| Parameter | What to supply |
|---|---|
| `project_id` | The identifier of the project |
| `contingency_rate` | New contingency rate (0–1). Omit to leave unchanged |
| `base_currency` | New ISO 4217 currency code. Omit to leave unchanged |

At least one of `contingency_rate` or `base_currency` must be provided. `apply_budget_lever` applies the lever and returns the fully-recomputed topsheet in a single call — no separate `get_production_budget` call is needed afterward.

`apply_budget_lever` is a `destructive`-classified tool — it modifies the stored budget header. Call it normally; your MCP client prompts you to allow it and the backend enforces the acting user's permission. See `genvid-boundary-gate`.

Offer levers proactively when the user asks comparison questions: "What if contingency is 15 %?", "Show me this in EUR." Present the returned topsheet the same way as `get_production_budget`.

---

## Exporting to EP MMB

Use `export_production_budget` when the user wants the budget in EP MMB format.

```
export_production_budget(project_id=<project_id>)
```

| Parameter | What to supply |
|---|---|
| `project_id` | The identifier of the project whose budget to export |

`export_production_budget` is a `read_only`-classified tool. It runs immediately, free.

The tool returns the MMB XML as a string along with the suggested filename and byte size. Surface the filename and size to the user and confirm the export is ready. A budget must exist before exporting — if `create_production_budget` has not been called for the project, call it first.

---

## Data boundary

This skill contains no rate tables, no tenant-specific pricing, and no budget math. All computation — line totals, fringe application, account rollups, contingency, and currency handling — runs inside the governed boundary. The `amt`, `x`, `rate`, and `x4` values you pass to `add_budget_lines` are inputs to the boundary's calculation engine; the engine computes and returns the results.

When the user needs a rate figure, source it from publicly available references (guild rate cards, industry production surveys, studio manuals) or ask the user to confirm it directly. Pass the confirmed figure as the `rate` value. Do not embed any rate schedule, pricing table, or tenant budget data in agent instructions, system prompts, or extensions of this skill.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Run breakdown to populate the scenes and storyboard this skill reads | `genvid-screenplay-breakdown` |
| Design shots within scenes before budgeting | `genvid-scene-shot-design` |
| Understand how `additive` and `destructive` tools are controlled | `genvid-boundary-gate` |
| Full tool list and classifications | `../../references/boundary-tools.md` |
| OMC terminology reference | `../../references/omc-vocabulary.md` |
