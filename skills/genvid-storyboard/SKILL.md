---
name: genvid-storyboard
description: Compose each shot's first frame bring-your-own-model and bind it to the shot, signed with attested provenance.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Storyboard First Frames

Once the storyboard's shots exist, each shot gets a first-frame keyframe. On this path the first frames are **bring-your-own-model**: you run the generation with your own provider and key, and Genvid signs the binding with attested provenance. There is no platform "generate all keyframes" tool here — composing first frames is the bring-your-own-model flow, exactly like asset images.

For OMC terminology used throughout this skill, see `../../references/omc-vocabulary.md`. Always use preferred terms — the avoid list is in that reference.

---

## Prerequisites

**Shots and the storyboard must already exist.** First-frame composition operates on the shots already structured in the project's storyboard. If the storyboard has not been composed — scenes decomposed into beats and shots, each shot given its director intent (shot size, camera angle, camera movement, shot framing) — do that first with `storyboard_write(method="compose")`. See `genvid-scene-shot-design`.

First-frame composition uses *your own* provider and key, so it needs no Genvid generator connection. (Generator connections govern the paths where Genvid runs the generation on your behalf; see `genvid-generator-connections`.)

---

## Compose each shot's first frame (bring-your-own-model)

Compose first frames with **your own** provider and bind them — Genvid governs and signs the result. You run the generation with your key; Genvid certifies the binding and the provenance. There is no platform generation call and nothing billed by Genvid on this path.

For each shot that needs a first frame:

1. **Claim the keyframe task** — `production_write(method="create_assignment", project_id=..., resource_type="shot", resource_id=<shot_id>, task_type="keyframe", workflow_status="in_progress")`. Required on **every** render, per shot (same rule as asset images): most roles have the bind rejected until the shot's keyframe task is assigned to you and In progress, and a supervisor / admin bypasses that check but must still claim — an unclaimed bind that succeeds leaves the shot's keyframe task showing untouched, which is a workflow defect. Claim each shot before you bind it, in the same per-shot loop; never batch the binds and skip the claims.
2. **Read the shot's composition context** — `shots_read(method="get", project_id=..., shot_id=...)` for `castMembers`, `location`, and `shot_direction`.
3. **Pull the images you'll condition on** — resolve each cast member / the location to its approved image (`assets_read`), then `media_read` each to get a signed URL and download the bytes. Prefer `certified` inputs.
4. **Compose the first frame I2I** with your own provider.
5. **Bind it** — `ingest_generated_media(project_id=..., link_type="shot_firstframe", shot_id=..., render_type="I2I", model_provider=..., model_name=..., prompt=..., params=..., source_url=<provider result>, input_media_ids=[<image media ids>], input_link_type="firstframe_source_image")`.

The full step-by-step is in `genvid-agent-generation` → **"Worked example — compose a shot's first frame"**. The bound first frame is signed (`externally_attested`) and carries the certified-inputs roll-up `input_certification` (`all_certified` if every cast/location image you used was certified). The bind is additive and not gated by an allow-prompt; the keyframe-task claim in step 1 is required for workflow accuracy whether or not your role could skip the gate.

First-frame composition is **not** billed by Genvid — you spend on your own provider; Genvid only signs the bound result.

---

## Resolving a pasted frame citation

Someone may hand you a frame citation — a token copied from the Storyboard grid's citation button that pins one exact keyframe, not "whatever the shot currently shows":

```
genvid://ref/v1/{project_id}/{shot_id}/{media_id}
```

All three segments matter: `project_id` and `shot_id` scope the read, `media_id` pins the exact media the citation was copied against — even if the shot's firstFrame is later regenerated or replaced, the citation still resolves to the keyframe someone actually looked at.

A citation always references a whole media record — an image, or a video as a single unit. There is no point-in-time-within-a-video form in v1; treat a token with extra segments as malformed rather than guessing.

To resolve one:

1. Parse the grammar — `v1` is the citation format's own version, independent of `boundary_compat`; a pasted citation should not break because an unrelated tool-contract bump happened after it was copied. Extract `project_id`, `shot_id`, `media_id`.
2. `media_read(project_id, media_id)` — get the signed URL and trust state (`c2pa_status`, `certified`) for the cited media. This is the bytes for your multimodal input.
3. `shots_read(method="get", project_id, shot_id)` — get the shot's narrative/cinematography context (`shot_direction`, `action`, `dialog`). A "like this, but tighter" instruction needs this alongside the pixels — the citation is a pointer into the shot's creative intent, not just an image reference.
4. Feed the signed URL into your own generation step, conditioning on it the same way you would any other reference image (see `genvid-agent-generation`).

If `media_read` can't serve the bytes directly — the media is at the `connected` or `registered` residency tier (see `genvid-media-registration`) — fall back to `resolve_media(project_id, media_id)` to resolve access instead.

No new boundary tool exists for citations — resolution is composed entirely from `media_read` and `shots_read`, both already at boundary v0.5.0.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Design the shots before composing their first frames | `genvid-scene-shot-design` |
| Understand how provenance is captured and what gets signed | `genvid-generate-with-provenance` |
| Understand how billable/destructive calls are controlled | `genvid-boundary-gate` |
| Understand registered connections and routing | `genvid-generator-connections` |
| Full tool list and classifications | `../../references/boundary-tools.md` |
| OMC terminology reference | `../../references/omc-vocabulary.md` |
