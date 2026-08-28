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

### Reconcile before you create

A project usually already has assets before breakdown runs — most often because the
show bible was ingested first, and **those** are the assets carrying the user's
reference images. If you author a second copy, the shots you link later point at
your copy, which has no media, and the user's references sit orphaned on a
duplicate the production never uses.

So read what already exists first:

```
assets_read(method="list", project_id=<project_id>)
```

Match each asset you are about to author against that list by name and type, and
reuse the existing `asset_id` when it is the same entity. Names differ
cosmetically — the bible's `The Boy` and your `Boy` are one character.

The boundary enforces this as a backstop. `assets_write` create and create_batch
reconcile against the project's existing assets before writing:

- **Name and type match an existing asset** — the call attaches to it and returns
  that asset's `asset_id` with `matched_existing: true`. Nothing is duplicated.
- **`cast_member` and `extra` on the same name** — these two are one identity,
  not a clash: `cast_member` is a superset of `extra` (it carries every slot
  `extra` does, plus dialog). An arriving `extra` that matches an existing
  `cast_member` (say `Hermit Crab`) just attaches to it. An arriving
  `cast_member` that matches an existing `extra` attaches to it AND upgrades
  it to `cast_member` — it gains the dialog slot, loses nothing. The reverse
  never happens automatically: an existing `cast_member` is never downgraded
  to `extra`, since that could orphan dialog media — only a human decides that.
- **Any other cross-type clash is ambiguous** — the same name under a
  different, non-superset type (`Beach` as both `location` and `prop`), or a
  near-name variant of the same type (`Beach Shoreline` against an existing
  `Beach`) — the call is rejected and names the candidates. Nothing is
  written. Resolve it: reuse the existing asset, correct its type with
  `method="update"`, or, if it genuinely is a distinct asset, re-send with
  `allow_duplicate=true`.

For each asset that is genuinely new, create a record:

```
assets_write(method="create", project_id=<project_id>, name=<name>, asset_type=<type>, description=<optional>)
```

| Parameter | What to supply |
|---|---|
| `name` | The asset's name (for example a character's name, or a location) |
| `asset_type` | One of: `cast_member`, `location`, `prop`, `costume`, `inspiration`, `extra`, `set_dressing`, `makeup_hair`, `vehicle`, `livestock`, `greenery` |
| `description` | Optional — a short description of the asset |

`assets_write(method="create")` is **additive** — it runs freely, without a gate prompt (see `genvid-boundary-gate`). The one write it can trigger against an asset that already exists — the `extra` -> `cast_member` upgrade above — is a lossless superset change, not an overwrite or a spend, so it stays additive too. Use `method="update"` with an `asset_id` to revise an asset you already created some other way.

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
