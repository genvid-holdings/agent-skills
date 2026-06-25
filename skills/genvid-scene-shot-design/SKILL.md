---
name: genvid-scene-shot-design
description: Design shots within a scene using OMC shot-direction vocabulary.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Scene and Shot Design

The scene and shot design workflow is the production phase where the director's intent takes structural form. After breakdown has populated scenes from the screenplay, this skill guides you through reading and updating those scenes and the shots within them — applying OMC shot-direction attributes to give each shot a precise visual specification.

For OMC terminology used throughout this skill, see `references/omc-vocabulary.md`.

---

## Reading scenes and shots

### Read a scene

Use `scenes_read` to fetch or list scenes for a project.

```
scenes_read(method=<method>, project_id=<project_id>, scene_id=<scene_id>)
```

| Parameter | What to supply |
|---|---|
| `method` | The read operation to perform — `list` returns all scenes for the project; `get` returns the full record for a specific scene |
| `project_id` | The identifier of the project whose scenes you are reading |
| `scene_id` | Required when `method=get` — the identifier of the scene to fetch |

`scenes_read` is a `read_only`-classified tool. It runs immediately, free.

### Read shots within a scene

Use `shots_read` to fetch or list shots for a project.

```
shots_read(method=<method>, project_id=<project_id>, shot_id=<shot_id>)
```

| Parameter | What to supply |
|---|---|
| `method` | The read operation to perform — `list` returns all shots for the project; `get` returns the full record for a specific shot |
| `project_id` | The identifier of the project whose shots you are reading |
| `shot_id` | Required when `method=get` — the identifier of the shot to fetch |

`shots_read` is a `read_only`-classified tool. It runs immediately, free.

---

## Resolving identifiers — never parse from free text

**Always resolve scene and shot identifiers by listing, then using the returned identifier. Never infer or parse an identifier from the user's description or from positional language like "the first shot" or "shot 3".**

The correct pattern:

1. Call `shots_read(method=list, project_id=...)` to retrieve the full list of shots.
2. Locate the intended shot in the returned records by matching against the user's description.
3. Use the `shot_id` from the returned record in the subsequent `shots_write` call.

The same applies to scenes: list with `scenes_read(method=list, ...)` and use the `scene_id` from the response — do not derive it from the user's words.

Why this matters: free text is ambiguous. A user saying "the opening shot" or "scene two" does not reliably map to a specific identifier in the data model. Parsing a shot index from the user's description and acting on it is how you update the wrong entity. Listing first makes the identifier unambiguous before any write proceeds.

---

## Updating scenes and shots

### Update a scene

Use `scenes_write` to modify a scene's properties.

```
scenes_write(method=<method>, project_id=<project_id>, scene_id=<scene_id>)
```

| Parameter | What to supply |
|---|---|
| `method` | The write operation to perform — typically `update` to modify scene fields |
| `project_id` | The identifier of the project |
| `scene_id` | The identifier of the scene to update — resolved by listing, not inferred from free text |

`scenes_write` is a `destructive`-classified tool — it overwrites existing scene state. Call it normally; your MCP client prompts you to allow it and the backend enforces permission. See `genvid-boundary-gate`.

### Update a shot

Use `shots_write` to modify a shot's properties, including its shot-direction attributes.

```
shots_write(method=<method>, project_id=<project_id>, shot_id=<shot_id>)
```

| Parameter | What to supply |
|---|---|
| `method` | The write operation to perform — typically `update` to modify shot fields |
| `project_id` | The identifier of the project |
| `shot_id` | The identifier of the shot to update — resolved by listing, not inferred from free text |

`shots_write` is a `destructive`-classified tool — it overwrites existing shot state. Call it normally; your MCP client prompts you to allow it and the backend enforces permission. See `genvid-boundary-gate`.

---

## Shot-direction vocabulary

Each shot carries OMC shot-direction attributes that specify its visual composition. Use these preferred terms when setting or describing shot properties:

| Attribute | Preferred term | What it describes |
|---|---|---|
| `shot_size` | shot size | How much of the scene is visible in the frame (distance of framing) |
| `camera_angle` | camera angle | The vertical angle of the camera relative to the subject (angle of framing) |
| `camera_movement` | camera movement | How the camera moves during the shot (mobile framing) |
| `shot_framing` | shot framing | How subjects are arranged in the frame |

Scene-level visual context that conditions how shots read includes: atmosphere, lighting style, lighting notes, time of day, interior/exterior, weather, ambient sound, and director's notes.

For the full set of preferred terms, value lists, and the complete avoid → use mapping, see `references/omc-vocabulary.md`. Do not apply banned terms even when quoting a user's description back — translate to the preferred term.

---

## Destructive call protocol

Both `scenes_write` and `shots_write` are `destructive` when they overwrite existing data (see `genvid-boundary-gate`): call the tool normally. Your MCP client shows its allow-prompt before the call runs, and the backend enforces the acting user's permission — there is no separate step and no approval id. If the backend returns a permission error, surface it; the write did not happen. The action is recorded in the `entity_events` audit log.

Read-only calls (`scenes_read`, `shots_read`) run freely.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Generate keyframes for the shots you have designed | `genvid-storyboard` |
| Understand how `scenes_write` / `shots_write` are controlled | `genvid-boundary-gate` |
| Full tool list and classifications | `references/boundary-tools.md` |
| OMC terminology reference | `references/omc-vocabulary.md` |
