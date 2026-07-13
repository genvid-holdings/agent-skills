---
name: genvid-screenplay-breakdown
description: Read a screenplay, author the assets it implies with your own judgment, and cite each asset to its scene with a verbatim content anchor.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Screenplay Breakdown

Breakdown is Phase A of the production pipeline: it turns a written screenplay into the structured production data everything downstream (visual development, storyboard, generation) depends on. Nothing downstream can proceed until the screenplay's scenes are populated with assets.

In this pack **you** do the breakdown. You read the screenplay, decide with your own judgment which cast members, locations, props, and costumes it contains, author an asset record for each, and then link each asset to the scenes it belongs to — citing a verbatim line of the screenplay as the reason. The boundary does not infer assets for you; it validates and records what you author, and it resolves your citations against the real screenplay text.

For OMC terminology used throughout this skill, see `../../references/omc-vocabulary.md`.

---

## Precondition — a screenplay must exist

Breakdown reads an existing screenplay. Before you start, confirm the project has screenplay content: call `screenplay_read(method="get", project_id=...)` and check that `exists` is true. If there is no screenplay yet, write one with `screenplay_write(method="update", project_id=..., content=...)` — or have the human author it in the Genvid web app — before proceeding.

---

## Step 1 — Read the screenplay verbatim

Use `screenplay_read` to fetch the screenplay. It has three methods:

```
screenplay_read(method=<method>, project_id=<project_id>)
```

| `method` | What it returns |
|---|---|
| `get` | Overview — word count, page estimate, `exists`, and a short preview |
| `analyze` | Structural parse — scene list with headings and word counts, and detected character names |
| `full` | **Scene-segmented verbatim text** — `scenes:[{scene (1-based ordinal), heading, text}]`. This is the source of truth for content-anchor quotes. |

`screenplay_read` is `read_only` — it runs immediately, free.

**Always read with `method="full"` before you author.** The `full` response gives you the exact screenplay text, segmented by scene ordinal. You will copy spans of this text verbatim into the content anchors you attach in Step 3. Do not work from memory, from an earlier `analyze` overview, or from the human's paraphrase — copy from the `full` text you just read.

---

## Step 2 — Author the assets

Read each scene's `text` and decide, with your own judgment, which assets it introduces — cast members, locations, props, costumes, vehicles, and so on. This is the part that needs taste: the screenplay names some entities explicitly and implies others, and you decide what is worth tracking as a production asset.

For each asset, create a record:

```
assets_write(method="create", project_id=<project_id>, name=<name>, asset_type=<type>, description=<optional>)
```

| Parameter | What to supply |
|---|---|
| `name` | The asset's name (for example a character's name, or a location) |
| `asset_type` | One of: `cast_member`, `location`, `prop`, `costume`, `inspiration`, `extra`, `set_dressing`, `makeup_hair`, `vehicle`, `livestock`, `greenery` |
| `description` | Optional — a short description of the asset |

`assets_write(method="create")` is **additive** — it adds new state without overwriting or spending, so it runs freely (see `genvid-boundary-gate`). Use `method="update"` with an `asset_id` to revise an asset you already created.

---

## Step 3 — Link each asset to its scenes with a content anchor

An asset earns its place in a scene because the screenplay puts it there. Record that: for each scene, replace its asset links with the set of assets that belong to it, and cite the verbatim line that justifies each link.

First resolve scene identifiers by listing — never infer a `scene_id` from the human's words or from positional language:

```
scenes_read(method="list", project_id=<project_id>)
```

Then update each scene:

```
scenes_write(
  method="update",
  project_id=<project_id>,
  scene_id=<scene_id>,
  linked_assets=[
    {
      "asset_id": <asset_id>,
      "link_type": <role of the asset in the scene>,
      "provenance": {
        "quote": "<verbatim span copied from screenplay_read full>",
        "scene": <1-based scene ordinal>
      }
    },
    ...
  ]
)
```

- `linked_assets` is a **replacement** list — sending it replaces all of the scene's links, so include every asset that belongs to the scene in one call.
- `provenance` is the **content anchor**. `quote` is verbatim screenplay text, at least 8 characters, copied exactly from the `full` read; `scene` is the 1-based scene ordinal the quote lives in. `occurrence` is only needed when the same quote legitimately repeats within the scene.
- Raw `block_ids` are **not** accepted — you never handle opaque identifiers. You cite human-legible screenplay text and the boundary resolves it.

`scenes_write(method="update")` is `destructive` — it overwrites the scene's existing state (see `genvid-boundary-gate`).

---

## The re-read-before-write rule

The boundary resolves each `quote` against the real screenplay and **fails fast**: a paraphrase, an approximate quote, or a span that matches no scene text — or matches ambiguously — rejects the whole `scenes_write` update. Nothing is half-written.

So before every write that carries a content anchor, re-read the screenplay with `screenplay_read(method="full")` and copy the quote **verbatim** from the returned text. If the screenplay may have changed since your last read, read it again. Quoting from memory is the most common way to get an update rejected.

---

## Control protocol for destructive and billable tools

`screenplay_write` and `scenes_write` are `destructive`; `assets_write(method="create")` is additive and runs freely. For a controlled call you call the tool normally — your MCP client shows its allow-prompt before the call runs, and the backend enforces the acting user's permission. There is no separate approval step and no approval id. If the backend returns a permission error, surface it; the call did not run. Every destructive action is recorded in the `entity_events` audit log.

Read-only calls (`screenplay_read`, `scenes_read`) run freely.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Design the shots that cover each scene | `genvid-scene-shot-design` |
| Understand how generated media is signed with attested provenance | `genvid-generate-with-provenance` |
| Understand how `screenplay_write` / `scenes_write` are controlled | `genvid-boundary-gate` |
| Full tool list and classifications | `../../references/boundary-tools.md` |
| OMC terminology reference | `../../references/omc-vocabulary.md` |
