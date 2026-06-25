---
name: genvid-storyboard
description: Break a screenplay into a storyboard (billable) and compose each shot's first frame bring-your-own-model, signed with attested provenance.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Storyboard Generation

The storyboard workflow produces a visual breakdown of a project's screenplay into individual shots — `breakdown_storyboard`, a `billable` platform call that routes through the provenance boundary under budget enforcement — then **you** compose a first-frame keyframe for each shot with your own model and bind it. The breakdown is platform-generated; the first frames are bring-your-own-model: you run the generation with your own provider and key, and Genvid signs the binding with attested provenance (see Step 2).

For OMC terminology used throughout this skill, see `references/omc-vocabulary.md`. Always use preferred terms — the avoid list is in that reference.

---

## Prerequisites

Before breaking down the storyboard:

1. **Shots must be designed first.** `breakdown_storyboard` operates on the shots already in the project. If shots have not been structured and given director intent — shot size, camera angle, camera movement, and shot framing — do that work first. See `genvid-scene-shot-design`.

2. **A generator connection must be registered for the breakdown's render type.** `breakdown_storyboard` routes through the boundary's generation layer, which selects the enabled connection registered for its `render_type` automatically — there is no select step. Make sure a matching connection exists and is enabled; registration is done through the Genvid REST API or console, not an MCP call. See `genvid-generator-connections`. (First-frame composition in Step 2 uses *your own* provider, so it needs no Genvid connection.)

---

## Step 1 — Break down the storyboard

Use `breakdown_storyboard` to generate the visual breakdown of the project's screenplay into shot-level storyboard entries. This populates the storyboard with scene assignments, location context, and shot composition metadata derived from the screenplay and existing shot design.

| Parameter | What to supply |
|---|---|
| `project_id` | The project whose screenplay to break into a storyboard |

`breakdown_storyboard` is `billable`. Call it normally; your MCP client prompts you to allow it and the backend enforces the project budget (see `genvid-boundary-gate`).

---

## Step 2 — Compose each shot's first frame (bring-your-own-model)

Compose first frames with **your own** provider and bind them — Genvid governs and signs the result. There is no platform "generate all keyframes" tool on this path: composing first frames is the bring-your-own-model flow, exactly like asset images. You run the generation with your key; Genvid certifies the binding and the provenance.

For each shot that needs a first frame:

1. **Claim the keyframe task** — `production_write(method="create_assignment", project_id=..., resource_type="shot", resource_id=<shot_id>, task_type="keyframe", workflow_status="in_progress")`. Required on **every** render, per shot (same rule as asset images): most roles have the bind rejected until the shot's keyframe task is assigned to you and In progress, and a supervisor / admin bypasses that check but must still claim — an unclaimed bind that succeeds leaves the shot's keyframe task showing untouched, which is a workflow defect. Claim each shot before you bind it, in the same per-shot loop; never batch the binds and skip the claims.
2. **Read the shot's composition context** — `shots_read(method="get", project_id=..., shot_id=...)` for `castMembers`, `location`, and `shot_direction`.
3. **Pull the images you'll condition on** — resolve each cast member / the location to its approved image (`assets_read`), then `media_read` each to get a signed URL and download the bytes. Prefer `certified` inputs.
4. **Compose the first frame I2I** with your own provider.
5. **Bind it** — `ingest_generated_media(project_id=..., link_type="shot_firstframe", shot_id=..., render_type="I2I", model_provider=..., model_name=..., prompt=..., params=..., source_url=<provider result>, input_media_ids=[<image media ids>], input_link_type="firstframe_source_image")`.

The full step-by-step is in `genvid-agent-generation` → **"Worked example — compose a shot's first frame"**. The bound first frame is signed (`externally_attested`) and carries the certified-inputs roll-up `input_certification` (`all_certified` if every cast/location image you used was certified). The bind itself is additive and not gated by an allow-prompt; the keyframe-task claim in step 1 is required for workflow accuracy whether or not your role could skip the gate.

---

## Billable call protocol (the breakdown)

`breakdown_storyboard` is `billable` (see `genvid-boundary-gate`): call it normally. Your MCP client shows its allow-prompt before the call runs, and the backend enforces the acting user's permission and the project budget — a run that would exceed the budget is refused pre-spend with HTTP 402. There is no separate step and no approval id. Tell the human what the call will do and that it will spend, so the client allow-prompt is informed. If the backend returns an error (402 over-budget, permission denied), surface it; the call did not run.

First-frame composition is **not** billed by Genvid — you spend on your own provider; Genvid only signs the bound result.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Understand how provenance is captured and what gets signed | `genvid-generate-with-provenance` |
| Understand how billable/destructive calls are controlled | `genvid-boundary-gate` |
| Design shots before running the storyboard breakdown | `genvid-scene-shot-design` |
| Understand registered connections and routing | `genvid-generator-connections` |
| Full tool list and classifications | `references/boundary-tools.md` |
| OMC terminology reference | `references/omc-vocabulary.md` |
