---
name: genvid-scene-shot-design
description: Decompose scenes into beats and shots with your own directorial judgment, then compose the storyboard with OMC shot-direction and verbatim content anchors.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Scene and Shot Design

This is the production phase where the director's intent takes structural form. After breakdown has populated scenes and assets, **you** decompose each scene into beats and the shots that cover them — deciding shot sizes, camera angles, movement, framing, and cutting with your own judgment — and write that structure to the boundary. Every shot cites a verbatim line of the screenplay as its content anchor; the boundary validates the structure, resolves the citations, and records the result.

The boundary does not infer shots for you. It gives you the screenplay text and the deterministic coverage lints; the directorial decisions are yours.

For OMC terminology used throughout this skill, see `../../references/omc-vocabulary.md`. Always use the preferred terms — the avoid list is in that reference.

---

## Prerequisites — breakdown should come first

Scene and shot design is Phase C (production). It reads on the structured production data that Phase A **breakdown** produces: scenes populated with their cast, location, and prop assets. Before you compose, confirm breakdown has run — call `scenes_read(method="list", project_id=...)` and check the scenes carry the assets the screenplay implies (and, ideally, that Phase B visual-development asset images exist). If the screenplay has not been broken down yet — no scenes, or scenes with no linked assets — do that first with `genvid-screenplay-breakdown`, so shots are composed with full visual context.

This is advisory guidance, not a blocking check: the boundary does not reject a compose that runs before breakdown, and an agent or user who deliberately wants to storyboard first is free to. But the documented pipeline order is breakdown → visual development → storyboard, and composing after breakdown is what gives each shot its cast/location context.

---

## Step 1 — Read the screenplay and resolve identifiers

Read the screenplay verbatim, and read the scenes and shots you will build on:

```
screenplay_read(method="full", project_id=<project_id>)   # verbatim, scene-segmented text — the source of truth for quotes
scenes_read(method="list", project_id=<project_id>)        # scene ids and titles
shots_read(method="list", project_id=<project_id>)         # existing shots, if any
```

`screenplay_read`, `scenes_read`, and `shots_read` are `read_only` — they run immediately, free. The `full` screenplay read returns `scenes:[{scene (1-based ordinal), heading, text}]`; you copy spans of `text` verbatim into every shot's content anchor.

### Resolving identifiers — never parse from free text

**Always resolve scene and shot identifiers by listing, then use the returned identifier. Never infer an identifier from the human's description or from positional language like "the first shot" or "shot 3".**

The correct pattern:

1. Call `scenes_read(method="list", ...)` / `shots_read(method="list", ...)`.
2. Locate the intended record by matching against the human's description.
3. Use the `scene_id` / `shot_id` from the returned record in the subsequent write.

Free text is ambiguous — "the opening shot" or "scene two" does not reliably map to a stored identifier. Parsing an identifier from the human's words and acting on it is how you write the wrong entity. Listing first makes the identifier unambiguous before any write proceeds.

---

## Step 2 — Decompose scene → beat → shot (the directorial work)

Read each scene's screenplay `text` and break it down in three levels:

- **Scene** — a continuous unit of action in one location and time. Carries the mise-en-scène (interior/exterior, time of day, lighting style, weather).
- **Beat** — a coherent unit of dramatic action within the scene: an entrance, an exchange, a turn, a reveal. A scene is a sequence of beats.
- **Shot** — a single continuous camera setup that covers part of a beat, with its own OMC shot-direction.

Deciding the beats and how to cover each one is the taste this skill exists for. Apply a working coverage-and-continuity grammar (the deterministic subset is enforced by the boundary's lints — see Step 4):

**Coverage (Katz).** Give each beat enough setups to cut. Establish the space before you go tight: open a scene or a new location with a wider setup so the viewer is oriented, then move into the coverage — singles, over-the-shoulders, reverses — that carries the beat. Do not leave a beat uncovered: a scene that has zero shots is a coverage gap the boundary will flag.

**Size-and-angle (Mascelli).** Between two adjacent shots in the same scene, change the **shot size or the camera angle** (ideally both). Cutting between two shots that share the same size *and* the same angle reads as a jump cut. The one deliberate exception is a `MATCH CUT`, where the matched framing is the point.

**Continuity.** Hold screen direction and eyelines consistent across a cut — keep the camera on one side of the action's axis so characters do not swap sides frame to frame, and keep a moving subject travelling the same way across the cut.

**Dialog.** Cover an exchange as shot/reverse-shot: an over-the-shoulder or single on each speaker, grouped so the cutting follows who is speaking. Use a two-shot to hold both when the beat wants them together.

**Transitions.** Default to `CUT TO` between shots inside a scene. Use `DISSOLVE` for a soft time or place change, `FADE IN` / `FADE OUT` to open or close a sequence, and `MATCH CUT` deliberately when two framings rhyme. Set the transition explicitly when it is not a plain cut.

---

## Step 3 — Write the storyboard

There are two write paths. Use **`compose`** for the full storyboard before certification — it stages a pending review rather than writing live — and **`insert`** for a change-order after certification, applied live.

### Compose — the full storyboard (pre-certification)

`storyboard_write(method="compose", ...)` authors the complete `Scene → Beat → Shot` structure. On a project that already has a storyboard, it stages the result for review: the composed storyboard lands as a pending diff (response `status: "pending_review"` with a `diff_summary`) and is not live until it is Accepted — promote it with the storyboard approve action, `POST /projects/{id}/storyboard/actions/approve`. On an empty project, the first compose lands directly (response `status: "applied"`). It is `destructive` (it replaces any pending storyboard; see `genvid-boundary-gate`).

```
storyboard_write(
  method="compose",
  project_id=<project_id>,
  scenes=[
    {
      "scene_index": 1,                     # 1-based
      "scene_title": "...",                 # optional
      "interior_exterior": "INT",           # optional mise-en-scène (canonical enum values)
      "time_of_day": "NIGHT",
      "lighting_style": "LOW_KEY",
      "weather": "RAIN",
      "beats": [
        {
          "beat_index": 1,                  # 1-based
          "beat_title": "...",              # optional
          "beat_description": "...",        # optional
          "shots": [
            {
              "shot_index": 1,
              "shot_direction": {
                "shot_size": "WIDE SHOT",
                "camera_angle": "EYE LEVEL",
                "camera_movement": "STATIC",
                "shot_framing": "TWO SHOT"
              },
              "transition": "CUT TO",       # optional
              "action": [                   # optional action / dialog beats
                {"speaker": "...", "dialog": "...", "direction": "..."}
              ],
              "subject_names": ["..."],     # optional cast/asset names in frame
              "provenance": {
                "quote": "<verbatim span copied from screenplay_read full>",
                "scene": 1                  # optional in compose — defaults to the enclosing scene_index
              }
            }
          ]
        }
      ]
    }
  ]
)
```

- The nesting is **Scene → Beat → Shot**. Beats are their own level between the scene and its shots.
- Mise-en-scène and shot-direction fields take canonical enum values (see the vocabulary section below).
- `provenance` is **required on every shot**. In `compose` you may omit `provenance.scene` and it defaults to the enclosing `scene_index`; set it only when the quote lives in a different scene.
- Compose is **atomic**: a single paraphrased, unresolvable, or ambiguous quote rejects the entire compose. Nothing is half-written.
- Compose stages a review, it is not live on save (except the first storyboard on an empty project). Read the response status: `pending_review` means a human (or you, via the approve action) must Accept the diff before it reaches production; `applied` means it landed directly (empty project, or the composition matched production exactly — nothing to review). Do not assume a compose is live — re-read with `get_storyboard` if you need to confirm production state.

### Insert — a change-order (post-certification)

`storyboard_write(method="insert", ...)` appends one or more authored, cited shots into one scene's existing or new beat. It is **additive** — a post-certification change-order that adds coverage without replacing what is certified.

```
storyboard_write(
  method="insert",
  project_id=<project_id>,
  scene_id=<scene_id>,                       # target existing scene (from scenes_read)
  beat={"beat_id": <beat_id>, "at": {"after_shot_id": <shot_id>}},   # existing beat; omit "at" to append
  # -- or a new beat --
  # beat={"title": "...", "description": "...", "among": {"after_beat_id": <beat_id>}},
  shots=[
    {
      "shot_direction": { ... },
      "transition": "CUT TO",
      "action": [ ... ],
      "subject_names": ["..."],
      "provenance": {
        "quote": "<verbatim span copied from screenplay_read full>",
        "scene": <1-based scene ordinal>     # REQUIRED on insert
      }
    }
  ]
)
```

- On `insert`, `provenance.scene` is **required** — there is no enclosing `scene_index` to default from.
- Target an existing beat by `beat_id` (with an optional `at` position), or create a new beat with a `title`/`description` and place it `among` the scene's beats.

### The re-read-before-write rule

Every shot's `provenance` is a **content anchor**: `quote` is verbatim screenplay text, at least 8 characters, copied exactly from `screenplay_read(method="full")`; `scene` is the 1-based scene ordinal. `occurrence` is only needed when the quote legitimately repeats within the scene. You never handle opaque `block_ids` — you cite human-legible text and the boundary resolves it.

The boundary resolves each quote against the real screenplay and **fails fast** on a paraphrase, an approximate quote, or an unresolvable/ambiguous span. So re-read the screenplay with `screenplay_read(method="full")` before every write and copy each quote verbatim. Quoting from memory is the most common way to get a write rejected.

---

## Step 4 — Read the coverage lints and revise

The boundary computes a **deterministic** subset of the coverage-and-continuity grammar over the full storyboard and returns it as advisory `lints` — never generated content, and it never acts on them for you. The `storyboard_write(method="insert")` response carries the recomputed `lints` array; read it and revise. You can also call `get_storyboard(project_id=...)` any time — not just right after a write — to fetch the current storyboard plus the same recomputed `lints`, e.g. to check coverage after a `compose` or to re-check state later in a session. (These are the enforced floor; the directorial grammar in Step 2 is yours to apply beyond it.)

| Lint code | Scope | What it means | How to revise |
|---|---|---|---|
| `MASCELLI_SIZE_ANGLE` | shot pair | Two adjacent shots in the same scene share both `shot_size` and `camera_angle`, and the cut between them is not a deliberate `MATCH CUT` — a possible jump cut. | Change the size or angle of one shot, or set the transition to `MATCH CUT` if the matched framing is intended. |
| `BEAT_NO_COVERAGE` | scene | A scene is present with zero shots — a coverage gap. | Add coverage for that scene: `compose` a corrected structure, or `insert` the missing shots into a beat. |

Treat lints as signals, not commands: you decide the fix. When a `MATCH CUT` is deliberate, the size-and-angle lint is exempt by design.

---

## Shot-direction vocabulary

Each shot carries OMC shot-direction attributes. Use these preferred terms and canonical values:

| Attribute | What it describes | Canonical values |
|---|---|---|
| `shot_size` | How much of the scene is visible (distance of framing) | `EXTREME CLOSE UP`, `CLOSE UP`, `MEDIUM CLOSE UP`, `MEDIUM SHOT`, `MEDIUM LONG SHOT`, `WIDE SHOT`, `LONG SHOT`, `EXTREME WIDE SHOT` |
| `camera_angle` | Vertical angle relative to the subject (angle of framing) | `EYE LEVEL`, `LOW ANGLE`, `HIGH ANGLE`, `DUTCH ANGLE`, `OVERHEAD`, `WORMS EYE` |
| `camera_movement` | How the camera moves (mobile framing) | `STATIC`, `PAN`, `TILT`, `TRACKING`, `DOLLY`, `CRANE`, `STEADICAM`, `HANDHELD`, `ZOOM` |
| `shot_framing` | How subjects are arranged in the frame | `SINGLE`, `TWO SHOT`, `THREE SHOT`, `GROUP SHOT`, `OVER THE SHOULDER`, `POV SHOT` |
| `transition` | How a shot connects to the next | `CUT TO`, `FADE IN`, `FADE OUT`, `DISSOLVE`, `SMASH CUT`, `MATCH CUT`, `JUMP CUT`, `WIPE` |

Scene-level mise-en-scène that conditions how shots read: `interior_exterior` (`INT`, `EXT`, `INT_EXT`), `time_of_day` (`DAY`, `NIGHT`, `DAWN`, `DUSK`, `MORNING`, `AFTERNOON`, `EVENING`, `CONTINUOUS`, `LATER`, `MOMENTS_LATER`), `lighting_style` (`HIGH_KEY`, `LOW_KEY`, `AVAILABLE_LIGHT`, `SILHOUETTE`, `CHIAROSCURO`), and `weather` (`CLEAR`, `OVERCAST`, `RAIN`, `STORM`, `SNOW`, `FOG`, `WIND`, `HAZE`).

For the full set of preferred terms and the complete avoid → use mapping, see `../../references/omc-vocabulary.md`. Do not apply banned terms even when quoting a human's description back — translate to the preferred term.

---

## Destructive and additive call protocol

`storyboard_write(method="compose")` is `destructive` — it replaces the storyboard, staged as a pending review for Accept (live immediately only for a first storyboard on an empty project). `storyboard_write(method="insert")` is additive — it adds coverage without overwriting. For a controlled call you call the tool normally; your MCP client shows its allow-prompt before the call runs, and the backend enforces the acting user's permission. There is no separate step and no approval id. If the backend returns a permission error, surface it; the write did not happen. Every action is recorded in the `entity_events` audit log.

Read-only calls (`screenplay_read`, `scenes_read`, `shots_read`, `get_storyboard`) run freely.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Compose each shot's first frame (bring-your-own-model) | `genvid-storyboard` |
| Understand how generated media is signed with attested provenance | `genvid-generate-with-provenance` |
| Understand how `storyboard_write` is controlled | `genvid-boundary-gate` |
| Full tool list and classifications | `../../references/boundary-tools.md` |
| OMC terminology reference | `../../references/omc-vocabulary.md` |
