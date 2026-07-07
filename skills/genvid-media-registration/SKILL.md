---
name: genvid-media-registration
description: Register files that already live in YOUR OWN storage into the Genvid graph without uploading them — index a directory the human names, hash and fingerprint and proxy each file locally, propose OMC bindings, and register the approved ones with register_media. Genvid never sees the original bytes.
compatibility: Requires a Genvid governed boundary with register_media (registered residency tier); see pack.json boundary_compat.
---

# Registering Media You Already Hold

## What this skill teaches

A studio points you at a directory of files that already exist in its own storage — dailies, plates, renders, reference stills, a show bible — and wants them represented in the Genvid graph **without moving the bytes**. You are the studio's own agent. You walk only the directory the human names, compute each file's identity and technical metadata **locally**, generate a small viewable proxy **locally**, read any embedded content-credential manifest, and then **propose an index**: which files belong to this project, what OMC anchor each one binds to, which are duplicates, which are versions of each other. A human reviews that proposed index. Only after they approve do you register the approved bindings with `register_media` — handing Genvid a hash, a fingerprint, technical metadata, the proxy, and the binding, but **never the original file**.

This is the registered residency tier. Genvid records a registry entry at the `registered` attestation tier: the claim is signed, the bytes are never verified. It is the honest, day-one-frictionless way to bring an existing catalog under governance — the same index-in-place pattern a storage-gateway appliance provides, except it runs as this skill inside your own agent, so no appliance has to be deployed. The division of labor is deliberate: **you compute identity and proxies locally and reason over them; Genvid governs and certifies the binding.** Exact-duplicate grouping and provenance chaining are reliable precisely because the skill computes them locally and hands the boundary the result.

`register_media` is the one tool this skill drives. It is the sibling of `ingest_generated_media`: same backend path, different attestation. Use `ingest_generated_media` only for media you **just generated** (it carries a generation record — model, prompt, params — signed at the `verified` tier). Use `register_media` for an **existing / archival** file (hash, fingerprint, metadata; no generation record — one would be unverifiable). Never dress up an old file as a fresh generation, and never register through `ingest_generated_media`.

---

## The scoping rule (do this first, without exception)

**Enumerate ONLY the directories the human explicitly names. Never walk the filesystem, never read outside the named tree, never explore parent or sibling directories.** The one exception is a local extraction table you generated for that same tree. This mirrors the boundary-gate discipline the rest of the pack follows: the human authorizes a scope, and you stay inside it. A studio running its own agent against its own storage accepts that the agent reads local bytes — so keep that reading confined to exactly what was authorized.

If the human names several directories, treat each as its own tree and index them separately. If a file inside the tree references something outside it, do not follow the reference.

---

## Step 1 — Extract locally (identity, metadata, provenance, proxy)

Before you reason about anything, run a local extraction pass over every file in the named tree. This is local file I/O in your own process; no bytes leave the machine, and Genvid is not involved.

For each file, compute and record:

- **`content_hash`** — the **SHA-256** hex digest (64 chars) of the original bytes. This is the exact-identity layer. Identical hashes are the same bytes, full stop.
- **`fingerprint_iscc`** — the composite **ISCC** code (Data + Instance) of the original. The byte-similarity layer; it survives a re-encode that changes the hash. Compute the media-decoded **ISCC Content-Code** too where the media subtype supports it (the transcode-surviving layer). Omit a fingerprint you cannot compute rather than guessing.
- **Technical metadata** — `mime_type` (IANA type of the original), `size_bytes`, and, for time-based media, `duration_seconds` and start `timecode`. Read these from the file, not from its name.
- **Embedded C2PA manifest** — if the file already carries a content-credential manifest, read it and keep it as a JSON-object string. You will chain it, not discard it (Step 4).
- **A local proxy** — generate a small viewable thumbnail or keyframe with a local tool (`ffmpeg` for video/audio, an image resize for stills). This is the ONLY media Genvid will store; the original never moves. Keep proxies small (a few hundred KB).

Record all of this as a local **extraction table**, one record per file. You reason over this table in Step 2 — hashes and provenance flags come from here, never from a filename alone.

---

## Step 2 — Propose an index (the binding contract is load-bearing)

Now decide, per file, what it is and where it belongs — against this project's OMC anchor graph. Read the project's OMC context first (`assets_read`, `scenes_read`, `shots_read`, and any bible/screenplay in the tree) so you know the real anchor IDs before you classify against them. **You PROPOSE only. Nothing is registered, nothing is written to any backend, no bytes are uploaded, until a human reviews your proposed index.**

The single most important rule in this skill is the **binding contract**. An under-specified contract makes an agent over-bind from story inference — in the validation spike, binding "every character the screenplay puts in the scene" collapsed asset precision to ~0.10; the one-paragraph contract below took it to ~1.00. A registry binding is a claim you are asking a human to certify, so bind conservatively. Carry this contract as written:

> **Binding contract — bind only what a file DIRECTLY represents, and only bindings you could verify from evidence in the directory:**
> - A live-action **camera / dailies clip** (and its proxies/copies) binds to its **scene** and that scene's **physical location** asset. Do **not** tag every character who happens to appear in that scene — cast presence is derived from the scene, is not verifiable from a dailies slate, and is not a per-file binding.
> - A **VFX plate / render / comp** binds to its **shot** and **scene**.
> - A **reference / character / location still** binds to the specific **character or location it depicts**.
> A registry binding is a claim you are asking a human to certify — bind what the file *is*, not everything the story around it contains. When in doubt, prefer fewer, defensible bindings and `flag_hitl` the rest.

### The per-file proposal record

For every file in the tree, produce one record:

- **`disposition`** — `bind` (you are confident it belongs to this project and you can place it), `flag_hitl` (it may belong but you are not confident enough to bind — a human should decide), or `reject` (it is not part of this production).
- **`anchors`** — the OMC anchor IDs it binds to, split by type: `{"asset": [...], "scene": [...], "shot": [...]}`. Use only IDs that exist in the project's OMC graph. Leave empty for `flag_hitl` / `reject`.
- **`dup_group`** — your own stable label shared by every file that is **the same captured content** — the same frame/clip, whether byte-identical or the same source re-encoded to another codec/resolution. Genuinely different content gets a distinct label (or `null` if unique). **A duplicate group is NOT a version chain:** iterations of an evolving work (`v001`, `v002`, …) are *different* content and must NOT share a `dup_group` — record them under `version`.
- **`dup_kind`** — `original`, `exact_copy` (byte-identical), `rename` (byte-identical, renamed), `transcode` (same content re-encoded to another codec/resolution), or `none`.
- **`version`** — if the file is one iteration in an evolving succession of the same work (each iteration supersedes the last), record `{"chain": "<label>", "index": <int>, "head": <bool>}` where `head` marks the latest iteration; otherwise `null`.
- **`provenance`** — `{"c2pa": <bool>, "decision": "chain" | "re_root" | "none"}`. If a file already carries an embedded content-credential manifest, the correct handling is to **extend** its provenance chain (`"chain"`), never to discard and re-originate it (`"re_root"`). `"none"` when it carries no manifest.
- **`confidence`** — 0.0–1.0.
- **`rationale`** — one line: the evidence you used (a filename, a folder, a metadata join, the hash, the bible, the proxy image).

### How to work

- Use the extraction table for hashes and provenance flags. Identical hashes are the same bytes. Different hashes may still be the same content (a re-encode) — reason from names, folders, and metadata sidecars.
- Metadata is often **aggregate**, not per-file: per-roll `.ale`, per-reel/pull `.edl` / `.aaf`, and per-folder `.mhl` sidecars. To place a camera clip you will generally have to **join** its filename to an ALE row (scene/take) and/or an EDL/AAF reference — no single file hands you the answer. Sidecars (`.ale`, `.edl`, `.aaf`, `.mhl`) and context documents are not themselves bindable media; `reject` them with a note, or omit them.
- You may open the proxy to classify what a file depicts; a bible describes each character and location.
- **When the evidence does not support a confident anchor, `flag_hitl` — do not guess.** Never invent an anchor ID that is not in the project's graph. Files that are clearly not part of this production get `reject`ed.

---

## Step 3 — Human review before ANY bind (mandatory, not optional)

Hand the human the full proposed index and **wait**. Nothing binds until they approve it. This is a hard gate the tier is built around, not a courtesy step:

- **A `flag_hitl` is a success, not a gap.** The spike deliberately planted an ambiguous prop plate (a set-dressing still with no matching asset ID). Every run flagged it for HITL rather than binding it — and that conservative restraint is exactly the behavior this skill wants. A miss that a human recovers at review is cheap; a false bind that a human has to *notice and unwind* is expensive. Bias toward flagging.
- **Version-chain proposals are HITL-confirm — never auto-bind.** Lineage reconstruction is the least stable thing you do (the spike's single softest metric). Present the chain and its proposed head; let the human confirm the ordering before anything about it registers.
- **Cross-scene reuse under-tags, and that is fine.** A plate reused across two scenes may come back with only one scene tagged. That is a recall gap a human closes by adding the missing tag — nothing wrong bound. Do not compensate by speculatively adding scene tags you cannot defend from the file.

Present the index so a human can act on it: group by disposition, show each file's anchors, dup group, version, provenance decision, confidence, and rationale. Let them approve, edit anchors, or reclassify. **Only the files the human approves as `bind` proceed to Step 4.**

---

## Step 4 — Register the approved bindings with register_media

For each approved `bind` file, call `register_media` once, binding it to the **one** anchor it represents. Genvid stores the proxy + the claim; the original stays where it is.

| Parameter | What to supply |
|---|---|
| `project_id` | The project the media belongs to |
| `link_type` | The slot the media fills — see the anchor mapping below |
| `shot_id` *or* `asset_id` | The anchor — provide **exactly one** |
| `content_hash` | The SHA-256 you computed locally (64-char hex) |
| `fingerprint_iscc` | The composite ISCC (Data+Instance); omit if unavailable |
| `fingerprint_iscc_content` | The media-decoded ISCC Content-Code; omit if unavailable for this subtype |
| `filename` | The **original's** display filename (its extension sets `media_type`) — not a Genvid path; the original lives offsite |
| `mime_type` | IANA MIME type of the original |
| `size_bytes` | Size of the original, measured locally |
| `duration_seconds` / `timecode` | For time-based media; omit for stills |
| `locator` | Path/key of the original **relative to the customer storage root** (a SAN path or S3 key) — never a Genvid path |
| `locator_type` | `customer_path` (SAN) or `customer_s3` |
| `proxy_base64` | The local proxy, base64-encoded — the only media Genvid stores |
| `proxy_filename` | Filename for the proxy (its extension sets the proxy's content type) |
| `pre_signed_c2pa_manifest` | The original's embedded C2PA manifest as a JSON-object string, **if** you read one — chained by reference, never re-rooted. Omit when there is no manifest |
| `input_media_ids` | Existing Genvid media IDs that are provenance inputs (rare for an archival original; usually empty) |

### Mapping a proposed anchor to the register_media call

`register_media` binds a file to **one shot or one asset**, and its slots are typed: a **shot** slot (`shot_keyframe` / `shot_firstframe` / `shot_lastframe` for a still frame, `shot_video` for moving-image) or an **asset image** slot (`cast_member_image` / `location_image` / `prop_image` / …, for a still). A scene is not a direct registry slot — it is captured in the proposed index for review and is expressed through the shot that lives in it or the asset the file depicts. **Match the slot to the file's media kind: a video original goes in a video slot, a still goes in an image slot** — the boundary does not reject a video bound into an image slot, so getting this right is on you. Resolve each approved binding this way:

- **VFX plate / render / comp → its shot.** `shot_id` + `link_type` = `shot_keyframe` for a still frame (or `shot_firstframe` / `shot_lastframe` for a designated frame role, `shot_video` for a moving-image render). The scene rides along through the shot's own membership.
- **Reference / character / location still → the asset it depicts.** `asset_id` + the asset-type image slot: `cast_member_image` for a character, `location_image` for a location, `prop_image` for a prop, and so on. The `link_type` must match the asset's type. These are **image** slots — only bind a still here.
- **Camera / dailies clip.** The binding contract anchors it to its **scene** and that scene's **physical-location** asset in the *proposed index* — that records what it depicts, for the human. But a raw dailies clip is a **video**, and its only defensible anchors are a scene (no registry slot) and a location asset (image-only slot). There is no clean per-file registry slot for it, so **`flag_hitl` the moving-image original** — do **not** force a video into an image-typed asset slot (`location_image`), and do **not** speculatively assign it to a specific `shot_video` slot it was never cut to (dailies predate shot assignment; that is a rebind the precision-first contract avoids). A human decides at review whether it ties to a known shot. A representative **still** that depicts the location may separately bind to the location asset via `location_image`.
- Resolve the OMC anchor IDs in your proposal to the project's real `shot_id` / `asset_id` with `shots_read` / `assets_read` before you call — `register_media` rejects an anchor that does not exist.

### Duplicates and versions at registration

- **Register each distinct captured content once** — the `original` of a `dup_group`. Exact copies, renames, and transcodes of it are already recorded in the proposal (via `dup_group`) for the human; do not silently register every rendition as if it were separate content. If the human wants a specific alternate rendition registered too, that is their call at review.
- **Register only the version-chain iteration the human confirmed** (normally the `head`). Prior iterations stay in the proposal as history unless the human asks to register them.

### What the tool is classified as

`register_media` is `additive`: it adds a new registry media + link without overwriting or removing anything, and without spending. Your own request to register this directory is the authorization; your MCP client does not prompt for an additive call. The media appears bound to its anchor — at the `registered` tier — as soon as the call returns.

---

## What the registered tier attests, and what it does not

Genvid signs the **claim** you registered — the hash, the fingerprint, the technical metadata, the binding, and (chained by reference) any embedded C2PA manifest — at the `registered` attestation tier. It does **not** verify the bytes, because it never held them: the tier's whole premise is that the original stays in your storage.

Said plainly: a registered media's hash is a **customer claim**, honestly labeled as such. That label travels in the registry claim and on any certification of registered media. If a studio later wants **verified-tier** certification for a specific asset, that is the moment Genvid must touch bytes to sign at full strength — the asset is flipped to the connected tier, or its bytes are handed over once, transiently, at approval time. Capture and registration never require the bytes; certification at full strength does. Keeping that two-tier distinction visible is the point — a registered claim that is quietly treated as verified would be a silent hole in the trust model.

---

## Where to go next

| What you want to do | Skill |
|---|---|
| Understand the boundary's read/control model and the three residency classes | `genvid-orientation` |
| Generate new media with your own provider and bind it (verified tier) | `genvid-agent-generation` |
| Run a controlled (billable or destructive) call | `genvid-boundary-gate` |
| Full tool list and parameter reference | `references/boundary-tools.md` |
| OMC vocabulary quick reference | `references/omc-vocabulary.md` |
