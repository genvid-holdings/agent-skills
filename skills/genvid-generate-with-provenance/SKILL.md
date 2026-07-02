---
name: genvid-generate-with-provenance
description: Generate a keyframe or asset through the boundary with signed provenance, and verify the C2PA manifest.
compatibility: Requires a Genvid governed boundary; see pack.json boundary_compat.
---

# Generate with Provenance

## Submit is the provenance commit point — get it right the first time

Whatever model, parameters, and prompt you pass at the submit call is exactly what gets signed and certified. The boundary creates a submit-record at the moment you submit the generation request, and that record is what the C2PA Content Credentials are bound to. The asynchronous completion callback cannot amend it — a completion payload that claims a different model does not change the signed attribution. There is no later correction path. The result becomes a billable, certified asset tied permanently to the values you passed at submit time. Verify your model ID and parameters before calling.

---

## Step 1 — Have a generator connection registered

This path is for when you want **Genvid** to run the generation. It routes through a registered generator connection — but there is no select step and no "active connection" to set. The boundary automatically picks the enabled connection registered for the generation's `render_type` at dispatch. You just need a matching connection to exist and be enabled; registration is an administrative step done through the Genvid REST API or console, not an MCP call. See `genvid-generator-connections`.

If instead your own agent generated the media locally, you do not use this path at all — bind the result through `genvid-agent-generation`.

On this path you do not pass model identifiers — the boundary writes the provider/model of the **enabled connection** it selects for the `render_type` into the signed submit-record. Make sure the right connection is registered and enabled before you call; there is no correction path once the submit-record is written.

---

## Step 2 — Call a generation tool

The platform generation tools are classified `billable` (see `genvid-boundary-gate`). Call them normally; your MCP client shows its allow-prompt before the call runs, and the backend enforces the project budget — a run that would exceed it is refused pre-spend with HTTP 402. There is no separate step and no approval id. Tell the human it will spend so the client allow-prompt is informed.

A billable generation routes through the enabled connection registered for its `render_type` (Step 1): you supply the `project_id` and the generation's inputs, and the boundary selects the connection and writes its provider/model into the signed submit-record. The specific billable tools and their parameters are listed in `references/boundary-tools.md`.

Composing the screenplay into a storyboard (Scene → Beat → Shot) is **not** a billable platform generation on this path — that structure is **agent-authored**, written through `storyboard_write(method='compose')` with your own directorial judgment and verbatim content anchors. See `genvid-scene-shot-design`. Likewise a shot's **first frame** is the bring-your-own-model path: generate with your own provider and bind with `ingest_generated_media`. See `genvid-agent-generation` and `genvid-storyboard`.

---

## Step 3 — What provenance capture means

When the generation call succeeds, the boundary automatically captures provenance. You do not instrument this yourself — it is enforced at the boundary layer.

Concretely: the boundary writes a submit-record at request time containing the model, parameters, and prompt. It then applies a C2PA Content Credentials signature binding the generated media to its OMC entity. That signature is derived from the submit-record, not the completion payload. If the async completion returns a response that differs from what was submitted, the signed attribution does not change. The submit-record is the canonical attribution; the completion payload is delivery only.

This is the provenance moat: certified attribution is frozen at submit, before any downstream processing or callback can influence it.

---

## Step 4 — Verify the C2PA manifest

After generation, verify the Content Credentials on the returned media. Inspect the signed manifest and confirm the model and attribution match exactly what you passed at submit time. Mismatches between the manifest and your submit-time values indicate a boundary integrity issue and should be treated as a hard stop — surface it to the human rather than presenting the media as accepted.

No fabricated verify tool is used here. Manifest verification is a step in reading the result: the boundary returns the generated media with its Content Credentials attached. Inspect the manifest as part of your acceptance check before forwarding the result to the human.

---

## Step 5 — Certification happens at content review

Provenance is signed at submit. Certification is completed when a human reviews and approves the generated content — a later step outside this skill. Do not treat generation completion as certification completion. The asset is signed but not yet certified until it is approved in the content-review workflow. (Spend is metered by the backend at the billable call itself, against the project budget; see `genvid-boundary-gate`.)

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Understand how a billable generation call is controlled | `genvid-boundary-gate` |
| Generate locally with your own provider and bind the result | `genvid-agent-generation` |
| Understand registered connections and routing | `genvid-generator-connections` |
| Understand the full tool surface and classifications | `references/boundary-tools.md` |
| OMC vocabulary reference | `references/omc-vocabulary.md` |
