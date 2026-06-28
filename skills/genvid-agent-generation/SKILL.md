---
name: genvid-agent-generation
description: Generate media with your own provider (your key, on your machine) and bind it to an asset or shot in Genvid with attested provenance — no key ever reaches Genvid.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Agent-Side Generation

## What this skill teaches

You generate media with your own provider, using your own key, on your own machine — for example by wiring the provider's own MCP server (such as FAL's) into your client. The provider key never reaches Genvid. You then hand Genvid the finished bytes plus what you used to make them, and Genvid binds the media to an asset or shot and signs it with tamper-evident, attested provenance.

This is the bring-your-own-agent path: you run the generation, Genvid governs and certifies the result at the boundary. One tool does the bind: `ingest_generated_media`.

---

## Step 0 — Claim the matching task before you generate (required, every generation)

Generating media is a step in a tracked production workflow, not a free action. Whatever you are about to bind — an asset image, a shot's first/last frame or keyframe, a shot's video, a shot's dialogue — that resource's task must be **assigned to you** and **In progress** first, and claiming it is what records that progress. This is **required for every generation**, not merely a gate to satisfy. For most roles the boundary rejects `ingest_generated_media` until the task is claimed — but a privileged role (supervisor / admin) **bypasses that check and is still required to claim**. A bind that happens to succeed without a claim silently leaves the task showing as untouched: that is a workflow defect, not a shortcut.

Claim the task that matches what you are generating:

| What you're generating | `resource_type` | `task_type` |
|---|---|---|
| asset image (cast / location / prop / style / ...) | `asset` | `assetImage` |
| shot first frame, last frame, or keyframe | `shot` | `keyframe` |
| shot video | `shot` | `video` |
| shot dialogue (audio) | `shot` | `audio` |

For **each** resource you are about to generate for:

1. **Check the assignment.** `production_read(method="list_assignments", project_id=..., resource_type=<asset|shot>, resource_id=<id>)`. Find the matching task and check whether its `assigned_to` is you and its `workflow_status`.
2. **If it is not already assigned to you and In progress, claim and start it in one call.** `production_write(method="create_assignment", project_id=..., resource_type=<asset|shot>, resource_id=<id>, task_type=<from the table>, workflow_status="in_progress")` — omit `assigned_to_email` (or pass `"me"`) to assign yourself; `workflow_status="in_progress"` assigns AND starts the task atomically. (Requires the matching `assign` permission; if your role lacks it, ask a supervisor to assign you.)
3. **Now generate and bind.**

Do this as ONE `create_assignment` call per resource, not a separate assign-then-start pair: claiming and starting in a single atomic call is correct and avoids a read-after-write race. `workflow_status` is one of the contract's task statuses — `not_started`, `in_progress`, `in_review`, `rejected`, `approved`, `cancelled` — and you claim+start with `in_progress`; the later statuses (`in_review`, `approved`, `rejected`) are set by a human in content review, not by you. (`set_assignment_status` still exists for moving a task you have *already* claimed to a status you are permitted to set.) `production_read` is read-only and `create_assignment` is additive, so this preamble costs nothing and your client does not prompt for it. It keeps the resource's status accurate in the UI. Do it even if your role could bypass the gate: an unclaimed bind that happens to succeed is still wrong. When you generate across many resources — a whole scene's first frames, or every shot's video — claim+start each resource's task in the same loop as its bind, never a batch that skips straight to binding.

---

## Step 1 — Generate with your own provider

**Need existing Genvid media as an input?** For I2I composition (a shot's first frame conditioned on its cast and location images, an edit of an existing render, …) pull each input with `media_read(project_id=..., media_id=...)`. It returns a short-lived **signed URL** you download and hand to your own provider, plus the media's trust state (`certified`, `c2pa_status`, `input_certification`) so you know what you are using. Reading is never gated — it returns any media you can see — but if you compose from uncertified inputs that is recorded honestly on the result (see the trust label below). Keep the `media_id`s you used: pass them as `input_media_ids` when you bind, so the provenance graph shows they led to your output.

Wire your provider's own MCP server (or any local generation tool) into your client and generate the media there, with your own key. Genvid is not involved in this step and never sees your key. The output you need is **the provider's hosted result URL** (the link the provider's tool returns — e.g. a `fal.media` URL) and the values you generated with: the model, the prompt, and the parameters.

Hold onto those values exactly as you used them. They become the signed provenance in the next step.

---

## Step 2 — Bind it to Genvid with provenance

Call `ingest_generated_media` with the result and what you used. Supply the media **one of two ways — `source_url` or `image_base64` — never both**:

- **`source_url` (use this).** Pass the provider's hosted result URL. Genvid downloads the bytes itself, SSRF-fenced to the attested provider's result CDN. This is the right path for a real image: you never have to move the bytes through a tool call, where a large base64 blob is infeasible to emit and a single corrupted character ruins the file. URL ingest is supported for providers whose result CDN Genvid has vetted (e.g. `fal`).
- **`image_base64` (fallback).** Only for a genuinely small payload, or a provider that returns bytes rather than a URL. The base64-encoded bytes; Genvid signs them verbatim.

| Parameter | What to supply |
|---|---|
| `project_id` | The project the media belongs to |
| `link_type` | The slot the media fills: a shot slot (`shot_firstframe` / `shot_keyframe` / `shot_lastframe` / `shot_video`) or an asset image slot (`cast_member_image` / `location_image` / `prop_image` / ...) |
| `shot_id` *or* `asset_id` | The anchor — provide exactly one |
| `source_url` *or* `image_base64` | The result — the provider's hosted URL (preferred), or the base64 bytes for a small payload. Exactly one |
| `filename` | A filename whose extension sets the content type (e.g. `flux.png`) |
| `model_provider` | The provider you generated through (e.g. `fal`), as you used it — also selects the vetted CDN allowlist for `source_url` |
| `model_name` | The model you generated with (e.g. `fal-ai/flux/schnell`), as you used it |
| `render_type` | The generation mode of the media (`T2I`, `I2V`, ...) |
| `prompt` | The prompt you used, as you used it |
| `params` | The params you used, as a JSON object string (e.g. `{"seed": 7, "steps": 4}`) |
| `input_media_ids` | Optional: existing Genvid media ids you used as references/inputs — recorded as signed ingredient provenance |
| `input_link_type` | How those inputs contributed, as a `media_media_link_type_enum` value: `firstframe_source_image` for I2I first-frame composition (the usual case), `edited_from` for an edit, `reference_image` for style/guidance only. Drives the C2PA action and the certified-inputs roll-up. Omit to accept the default (`firstframe_source_image`). |

`ingest_generated_media` is classified `additive`: it adds a new media and link alongside whatever is already there, without overwriting or removing anything and without incurring cost. Your own request to generate for this asset is the authorization, and your client does not prompt to allow an additive call. The media appears bound to the target as soon as the call returns.

---

## Worked example — compose a shot's first frame (bring-your-own-model)

Composing a shot's first frame is the canonical I2I case: you condition on the shot's cast and location images and bind the result to the `shot_firstframe` slot. Like an asset image, **the shot's keyframe task must be assigned to you and In progress before you bind, and you claim it whether or not your role could skip the gate** — Step 0 applies to shots too. For most roles the boundary rejects the bind until you claim; a supervisor / admin bypasses that check but is **still required** to claim, because the point is to keep the shot's workflow status accurate, not just to pass the gate. First frames, keyframes, and last frames all gate on the shot's `keyframe` task; `shot_video` gates on the `video` task.

1. **Claim the keyframe task (required, per shot).** `production_write(method="create_assignment", project_id=..., resource_type="shot", resource_id=<shot_id>, task_type="keyframe", workflow_status="in_progress")` — assigns it to you AND starts it in one atomic call (omit `assigned_to_email` or pass `"me"`). Do this even if you are a supervisor whose bind would be accepted without it: an unclaimed first frame leaves the keyframe task showing untouched. When you render a whole scene or sequence, claim+start **each** shot's keyframe task before binding that shot — once per shot, in the same loop as the bind, never a batch render that skips straight to binding. `create_assignment` is additive, so your client does not prompt for it.
2. **Read the shot's composition context.** `shots_read(method="get", project_id=..., shot_id=...)` → `castMembers`, `location`, `shot_direction` (and `image_status` / `firstFrame` to see whether one already exists). `media_selection(project_id=..., shot_id=...)` tells you `has_firstframe` quickly.
3. **Resolve each cast member + the location to its approved image.** `assets_read(method="list", project_id=...)` maps the names from `castMembers`/`location` to `asset_id`s; `assets_read(method="get", asset_id=...)` returns that asset's media. Pick the approved one — if unsure, `media_read` each candidate and prefer `certified: true` (and `c2pa_status: "signed"`). Hold onto each chosen `media_id`.
4. **Pull the input bytes.** `media_read(project_id=..., media_id=...)` for each chosen image → download its `signed_url` and hand the bytes to your own provider.
5. **(Optional) enrich the prompt.** `enhance_prompt(context_type="shot_keyframe", project_id=..., id=<shot_id>, model_id=<your I2I model>)` returns a production-context-aware prompt.
6. **Compose with your own provider** (I2I), conditioning on the cast/location images + the shot direction.
7. **Bind to the shot.** `ingest_generated_media(project_id=..., link_type="shot_firstframe", shot_id=..., render_type="I2I", model_provider=..., model_name=..., prompt=..., params=..., source_url=<provider result url>, input_media_ids=[<the image media_ids>], input_link_type="firstframe_source_image")`.

The bound first frame is signed and carries `input_certification` — `all_certified` if every cast/location image you used was certified, `mixed`/`none_certified` otherwise. That is the honest record of what you composed from; nothing blocks an uncertified compose, it is just labelled.

**Binding a first frame also selects it for the slot.** `shot_firstframe` (like `shot_lastframe` and `shot_video`) is a single-cardinality slot, so binding to it marks the new media as the selected media for that slot — a middle `shot_keyframe`, which allows several, does not and leaves selection to a human. This is **slot selection, not certification**: the frame now fills the slot, but it remains *uncertified* until a human approves the shot's task in the content-review workflow (see `genvid-generate-with-provenance` Step 5). Do not read the auto-selection as approval, and do not expect a tool to "approve" or "certify" it — there is none; certification is a human step outside this skill.

---

## Generating a shot's video

Video follows the same shape as a first frame, with two differences: you bind to the `shot_video` slot, and in Step 0 you claim the shot's **`video`** task, not `keyframe`. `ingest_generated_media(project_id=..., link_type="shot_video", shot_id=..., render_type=<T2V | I2V | KF2V | ...>, model_provider=..., model_name=..., prompt=..., params=..., source_url=<provider result url>, input_media_ids=[<the keyframe media_ids you conditioned on, if any>])`. Claim+start the `video` task for **each** shot before binding its video; when you render a scene's worth of shots, do it per shot in the same loop, never a batch that binds first and claims later (or never). The same Step 0 rule covers a shot's dialogue against the **`audio`** task once a dialogue bind path is available to you.

---

## What Genvid attests, and what it does not

Genvid signs the media with a C2PA manifest carrying your attested `model_provider`, `model_name`, `prompt`, and `params`, plus a `genvid.attestation` mark with level `externally_attested`. That mark is the honest statement of the trust model: Genvid certifies the binding and your attestation, and that it received these bytes at this time bound to this target. It does **not** claim to have witnessed the generation, because it did not run it.

Said plainly: the manifest records "the producing agent asserts this was made with model X, prompt Y, params Z," signed and tamper-evident from that point on. That is the correct, honest bar for media a customer generated themselves and brought in.

---

## The provenance trust label

Genvid records two honest, independent things about what you composed from:

- **Were the inputs cryptographically signed?** When you pass `input_media_ids`, Genvid signs your output by chaining each input's own Content Credentials into the result's manifest — so a validator can see, per ingredient, whether that input carried a valid signature. This is the native C2PA validation; read it via the media's `c2pa` endpoint.
- **Were the inputs certified (workflow-approved)?** Genvid rolls up whether every pixel-contributing input was *certified* — the immutable, billed approval — into `input_certification`: `all_certified`, `mixed`, `none_certified`, or `no_inputs`. It is recorded in the manifest (`genvid.provenance`) and on the media, and surfaced by `media_read`.

Nothing here blocks you: you may compose from uncertified or unsigned inputs (an admin override, a freshly generated candidate). The result simply states what it used. To produce an `all_certified` result, generate from inputs whose tasks have been approved.

## Where to go next

| What you want to do | Skill |
|---|---|
| Propagate a change across a whole closure | `genvid-propagate-change` |
| Understand the boundary's read/control model | `genvid-orientation` |
| See the full tool list and classifications | `references/boundary-tools.md` |
