---
name: genvid-screenplay-breakdown
description: Ingest and structure a screenplay, then run breakdown to populate scenes and elements.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Screenplay Breakdown

The screenplay breakdown workflow takes a written screenplay and transforms it into the structured production data the rest of the pipeline depends on. It has two stages: reading and writing the screenplay text, then running breakdown to extract scenes and elements. Breakdown is Phase A of the production pipeline — nothing downstream (visual development, storyboard, generation) can proceed until the screenplay has been broken down and scenes are populated.

For OMC terminology used throughout this skill, see `references/omc-vocabulary.md`.

---

## Reading and writing the screenplay

### Read the screenplay

Use `screenplay_read` to fetch or analyze a project's screenplay content.

```
screenplay_read(method=<method>, project_id=<project_id>)
```

| Parameter | What to supply |
|---|---|
| `method` | The read operation to perform — `get` retrieves the raw screenplay text; `analyze` returns a structured analysis of the screenplay's narrative content |
| `project_id` | The identifier of the project whose screenplay you are reading |

`screenplay_read` is a `read_only`-classified tool. It runs immediately, free.

### Write the screenplay

Use `screenplay_write` to update a project's screenplay content.

```
screenplay_write(method=<method>, project_id=<project_id>, content=<content>)
```

| Parameter | What to supply |
|---|---|
| `method` | The write operation to perform — typically `update` to replace the screenplay text |
| `project_id` | The identifier of the project whose screenplay you are updating |
| `content` | The screenplay text to write |

`screenplay_write` is a `destructive`-classified tool — it overwrites the stored screenplay. Call it normally; your MCP client prompts you to allow it and the backend enforces permission. See `genvid-boundary-gate`.

---

## Running breakdown

Once the screenplay is in place, run breakdown to extract scenes and production elements from it.

```
breakdown_assets(project_id=<project_id>)
```

| Parameter | What to supply |
|---|---|
| `project_id` | The identifier of the project to break down |

`breakdown_assets` is a `billable`-classified tool. It consumes pipeline resources and populates the project's scenes and elements from the screenplay. Call it normally; your MCP client prompts you to allow it and the backend enforces the project budget. See `genvid-boundary-gate`.

What breakdown does:

- Parses the screenplay and creates a scene record for each scene
- Extracts characters, props, and locations from each scene into structured elements
- Links elements to the scenes they appear in
- Produces the storyboard scaffold that the production phase builds on

A logline written in the screenplay is preserved and surfaced at the project level. Scenes that span a continuous unit of action in one location and time are each broken out as discrete scene records. A sequence is a coherent grouping of consecutive scenes — breakdown establishes the scene-level records that sequences are later organized across.

---

## Control protocol for destructive and billable tools

Both `screenplay_write` (destructive) and `breakdown_assets` (billable) are controlled (see `genvid-boundary-gate`): call the tool normally. Your MCP client shows its allow-prompt before the call runs, and the backend enforces the acting user's permission and — for `breakdown_assets` — the project budget, refusing pre-spend with HTTP 402 if a run would exceed it. There is no separate step and no approval id. If the backend returns an error (402 over-budget, permission denied), surface it; the call did not run. Both actions are recorded in the `entity_events` audit log.

Read-only calls (`screenplay_read`) run freely.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Design shots within the scenes breakdown produced | `genvid-scene-shot-design` |
| Understand how `screenplay_write` / `breakdown_assets` are controlled | `genvid-boundary-gate` |
| Full tool list and classifications | `references/boundary-tools.md` |
| OMC terminology reference | `references/omc-vocabulary.md` |
