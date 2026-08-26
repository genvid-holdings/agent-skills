---
name: genvid-roblox-character-generation
description: Generation recipes for a rigged, textured, in-game-ready Roblox character via the MCP-first path — plate craft that conditions Cube's GenerateModelAsync, the retired Meshy operational record, the Mixamo-to-R15 rig recipe and skinned-rig wiring, world-space animation transfer and asset-naming provenance rules, and the governance calls (register_media/finalize_media_registration, record_approved_corrections) that make the output governed. Illustrated throughout with a real production's titan characters as the worked example. Does not cover Studio/MCP transport or session mechanics — see genvid-roblox-studio-ops.
compatibility: Drives the Genvid boundary (register_media, finalize_media_registration; record_approved_corrections is status:designed, not yet on prod) together with Roblox Studio's generation surfaces (generate_mesh, GenerationService:GenerateModelAsync) reached over Studio's own MCP server per genvid-roblox-studio-ops. See pack.json boundary_compat.
---

# Roblox Character Generation

The generation *recipes* for turning a concept plate into a rigged, textured,
in-game-ready Roblox character — plate craft, mesh generation, rigging,
animation transfer, wiring, and the governance calls that make the result
governed. This is the generation-recipe half of a two-skill pair:
**`genvid-roblox-studio-ops`** teaches the transport/session mechanics
(bridge failure modes, `execute_luau` patterns, payload streaming,
verification limits, crash hygiene, the two generation surfaces' egress
asymmetry, importer limits, and the Auto-Setup retirement record) — read it
first if you have not driven a Studio MCP session before. This skill does
not repeat any of that; it teaches the craft on top of it.

**Worked example:** every recipe below is illustrated with the
Escape-from-Titans production's four elemental titan characters (Ice,
Large, Small, Lightning). The titans are **the example customization**,
not the subject of this skill:
the recipe is a general Roblox character-generation pipeline, and code/asset
names below that say "titan" (`spawnTitan`, `animSpeedScale`, `HipHeightStuds`
on a titan template, and so on) are simply that production's naming, carried
through because the underlying technique they illustrate is what this skill
teaches. Where a step below is witnessed only in the titan build and has not
been generalized beyond it, the text says so explicitly rather than implying
it holds for every character.

Knowledge below was copied out of the retired `roblox-avatar-test` repo (a
fal-chain pipeline originally built for a different, non-titan character) and
out of the titan production's own build. Citations carry `path@retired-2026-08`
— that repo is read-only source material, not something this pack depends on
at runtime. Items marked **[mining]** were recovered from working-session
transcripts, not re-witnessed in a file; treat them as reliable operational
lore, not verified fact, and do not upgrade the label if you re-encounter the
claim elsewhere.

---

## 1. Plate craft (LIVE — plates condition `GenerateModelAsync`)

This stage is not retired: Studio's `GenerationService:GenerateModelAsync` is
image-conditioned (see `genvid-roblox-studio-ops` for the surface comparison),
so the plate you feed it still drives the result the way it always did.

- **Always inspect and re-roll the plate before spending on 3D.** A-pose with
  clear limb gaps.
- **[mining]** **The element-body trick** — build the creature *out of* its
  element (ice, lightning, stone, ...) while keeping the two-arm/two-leg body
  plan intact. In the worked example, this is the move that cleared Jacob's
  approval gate on a titan concept — keep that approval-evidence clause when
  you carry this rule forward.
- **[mining]** **Variant-editing from an approved plate** is the cheap way to
  fork A/B options — edit the already-approved plate rather than generating a
  fresh one from scratch, so approval risk on the base concept is spent once.

**Worked example, carried verbatim** (`PLAYBOOK.md:57-79@retired-2026-08`) —
this particular prompt predates the titan production and was written for a
different, non-elemental character, but the pose/gap discipline it encodes is
exactly what the element-body trick above depends on, and a pack consumer
cannot retrieve the read-only source, so the prompt itself is reproduced
rather than described:

**Goal:** strip everything Auto-Setup rejects while keeping identity, and
normalize the pose. **Model:** `fal-ai/nano-banana-2/edit` (Gemini 3.1 Flash
Image / "Nano Banana 2"). Start from a full-body, front-facing image on a
plain background.

> Edit this character into a clean, scan-ready base body for 3D reconstruction. Keep the
> same woman — face, skin tone, tattoos, body proportions, and outfit colors. Remove ALL
> detachable gear so the body surface is smooth and continuous: remove the pink hair
> flower, earrings, necklace, the shoulder harness straps and chest buckles, every belt
> pouch, the thigh holster and side pouches, the fingerless gloves (show bare hands), and
> the knee pads. Simplify to just a form-fitting pink sports top, plain green cargo pants,
> and plain black boots. Pull all hair into a tight smooth bun close to the scalp — no
> loose strands, nothing covering the neck or shoulders; keep the neck fully visible and
> distinct from the shoulders. Keep a symmetric A-pose, standing straight, facing camera
> directly; arms straight and angled away from the torso with a clear gap on both sides;
> fingers relaxed and together, not spread; legs straight, feet shoulder-width apart, not
> touching. Full body head-to-feet, centered, plain flat neutral gray background, even
> studio lighting, no floor shadow.

Params: `resolution: "2K"`, `aspect_ratio: "3:4"`, `thinking_level: "high"`.
For an elemental character like the worked example's titans, adapt the
"remove detachable gear" clause to the element-body trick above — the intent
(a clean, symmetric A-pose with clear limb gaps and no clutter) is what to
carry forward for any character concept, not this prompt's specific wardrobe.

---

## 2. Retired-path operational record (Meshy) — HISTORICAL

Meshy (`fal-ai/meshy/v6/image-to-3d`) was the image-to-3D backend before the
Cube/MCP pivot. It is not the live path — Cube's `GenerateModelAsync` is —
but the operational facts below are worth keeping because the skinned-rig
recipe in §3–4 was built and proven against Meshy output on the titan
characters, and anyone still holding a Meshy-rigged GLB for any character
needs them.

**The eight params that worked** (`PLAYBOOK.md:111-115@retired-2026-08`),
carrying the block's own framing (`PLAYBOOK.md:109-110`): **rigging was
deliberately OFF** — the intent was the raw body so *Roblox* builds the R15
rig, not Meshy's non-R15 skeleton. Read this framing before the block below,
or it misreads as the rigged-export parameter set, which inverts its intent.

```json
{ "image_url": "<cleaned plate>", "pose_mode": "a-pose",
  "symmetry_mode": "auto", "should_texture": true, "enable_pbr": true,
  "enable_rigging": false, "target_polycount": 30000, "topology": "triangle" }
```

Other operational facts, gathered while building the titan characters:

- **[mining]** The **rigged-export polygon cap is exactly 20,000** triangles.
- **[mining]** Rigging jobs run **silent for 10–20 minutes** — a long
  unresponsive job is expected behavior, not a hang.
- **[mining]** `enable_rigging: true` **destroys non-humanoid silhouettes.**
  In the worked example, a cloud-float Lightning titan needed the *unrigged*
  path plus a hand-built armature — rigging a body that isn't roughly
  humanoid-shaped wrecks it.
- Meshy wires the **same atlas into Base Color AND Emission**
  (`stage_f_rig.py:88-92`) — leaving that link intact makes the body render
  self-lit; strip the Emission link/strength explicitly.
- **The texture must ride the FBX.** Nothing at runtime re-textures a skinned
  `MeshPart` — the Roblox importer packages the texture into the mesh asset
  itself, and `SurfaceAppearance`/`TextureID` overrides never take
  (`stage_f_rig.py:12-18`).

---

## 3. The rig recipe

Converting a Meshy-rigged, Mixamo-convention skeleton into an R15-compatible
skinned FBX for Studio's 3D Importer (`stage_f_rig.py@retired-2026-08`) —
this conversion is character-agnostic; the worked example ran it on all four
titans:

- **Mixamo→R15 rename table + leaf-up bone fold** (`stage_f_rig.py:25-53`):
  the 15 keeper bones get renamed to their R15 names directly; the 9 extra
  bones get their skin weights folded into an R15 neighbor, merged **leaf-up**
  (children reparent to the removed bone's parent first) so chains reparent
  cleanly.
- **Armature-origin-at-root-bone + mesh-vertex-shift**
  (`stage_f_rig.py:178-213`): the root bone must sit at the torso, not at the
  world origin — the importer maps it to `HumanoidRootPart` and hangs every
  child bone's rest offset off it, so an origin-rooted skeleton floats the
  whole visual mesh a full body-height above the ground. Relocate the
  armature origin to the root bone, then shift the raw mesh vertex data by
  the same offset (Roblox's far-LOD draws the raw mesh anchored at the root
  bone node, so unshifted vertex data floats the far-distance visual by the
  hip height even though the skinned close-range render is unaffected).
- **`HumanoidRootNode` naming** — keep the note at the definition
  (`stage_f_rig.py:182`): naming it `Root` instead fails the R15 guideline
  check; `HumanoidRootNode` is the name the Roblox avatar template expects.
- **World-space rotation-delta transfer** (`stage_h_poses.py:21-27`): do not
  play a clip's local rotations as `Bone.Transform` — Roblox re-orients bone
  local frames per bone at FBX import, so source-local rotations land on the
  wrong axes (knee flexion becomes knee twist, the "marionette" walk).
  Transfer **world-space rotation deltas** instead, with the global axis
  conversion chosen **EMPIRICALLY** (`stage_h_poses.py:28-30`): the candidate
  whose predicted foot trajectory best matches the authored clip (lateral vs.
  forward swing, height range) wins. There is no closed-form derivation for
  this — it is a search over candidates, not an analytic pick.

**The transfer law:** in the worked example, ALL production titan clips were
transferred onto the Meshy-skeleton rigs by `stage_h_poses.py`'s world-space
transfer (`docs/animation-provenance.md@retired-2026-08`); the native-Meshy
Lightning walks that predate this are recorded there as **SUPERSEDED**, not
as a live alternative. `stage_h_anim.py:1-19@retired-2026-08` is cited here
**only** for one fact — the standard R15 walk track retargets badly (hip keys
land at 90+ degrees, legs fold to head height) onto Meshy's Mixamo-convention
skeletons — and that fact is labeled as the **retired native-clip route**.
Its own recipe (Meshy's own walking clip needs no retargeting because it was
authored on that exact skeleton) is the **superseded path**, not the current
law; do not read `stage_h_anim.py` as describing how production animation
transfer works today, for titans or any other character.

- **[mining]** **Treadmill method for `animSpeedScale`**: offline estimates
  of the right speed-scale value are untrustworthy — measure it in-engine,
  live, rather than computing it from clip metadata. (`animSpeedScale` is
  the worked example's dial name.)

---

## 4. The skinned-rig wiring recipe, full form

Wiring a rigged, R15-skinned import into a working in-game rig (importer
physics are not usable as-is), applicable to any character on this pipeline.
The base recipe order and the config values below are `docs/HANDOFF.md`'s
T13 recipe (steps 2, 3, 5, 7 in full, plus the base clauses of steps 4 and 6,
at `docs/HANDOFF.md:210-214@retired-2026-08` — T13 was the worked example's
own titan-visual-identity task, hence the name). Steps 1 and 8 exist only in
session transcript, not in any committed file, and so does each clause below
marked individually — carrying **[mining, full recipe re-witnessed at
distilled 7374]**:

1. **[mining, full recipe re-witnessed at distilled 7374]** **Strip the
   importer's avatar-scaling metadata, then REBUILD it.** The importer's own
   scaling metadata silently reverts hand-done `HumanoidRootPart` surgery if
   left in place, so it has to be stripped and then explicitly rebuilt: the 6
   `Humanoid` NumberValues, per-`Bone` `OriginalPosition`, and
   `AvatarPartScaleType = "Classic"`.
2. Rebuild `HumanoidRootPart` as a torso box at the `LowerTorso` bone.
3. `WeldConstraint` the mesh to it (`CanCollide = false`, `Massless = true`).
4. Upright `AlignOrientation` (`OneAttachment`, `PrimaryAxisOnly`, axis `Y`,
   rigid). **[mining, full recipe re-witnessed at distilled 7374]**
   `AlignOrientation`'s `PrimaryAxis` **defaults to `X`** — leaving the
   default silently floats the rig horizontal instead of upright; it must be
   set to `Y` explicitly.
5. `RequiresNeck = false`, fall states off.
6. `AutomaticScalingEnabled = false`, **then** pin `HipHeight` — Play-start
   recomputes `HipHeight` to garbage if scaling is still enabled when it's
   set. **[mining, full recipe re-witnessed at distilled 7374]** The
   `HipHeight` formula is `hip = (rootY − feetPlane) − rootSize.Y / 2`; a
   fixed `12.5` figure recorded from an early session on one titan
   (`archive/2026-08-retirement/sdd-ledger/progress.md:145@retired-2026-08`)
   is **not canonical for any character** — it changed on every import and
   was specific to that run's geometry. Use the formula, not the number.
7. Release the rig via `ChangeState(GettingUp)`.
8. **[mining, full recipe re-witnessed at distilled 7374]** **Spawn placement
   reads the `HipHeightStuds` attribute**, not the part bounding box — part
   bboxes lie on these rigs, so your character-spawn code must read the
   attribute, not `GetBoundingBox` (in the worked example, this is
   `spawnTitan`).

**Two-point scale calibration is cross-referenced only, not repeated here.**
It shipped in `genvid-roblox-studio-ops/SKILL.md:126` as part of that
skill's Auto-Setup retirement record (per plan §5.1/§6); copying it into this
skill would duplicate content across the pair. Use it as written there.

- **[mining, spot-checked]** **Roblox render law:** skinned meshes render two
  different ways depending on distance — close-range is bone-deformed
  (skinning active), far-range (LOD) draws the raw mesh file anchored at the
  root bone, ignoring part position entirely. Verify posture/placement work
  from **both** distances; a fix that looks right up close can still be wrong
  at the LOD distance.

---

## 5. Governance integration

Three MCP tools make a character's generation and hand-tuning **governed**,
not just functional. This section states the exact shipped call shapes —
read it before wiring a capture, the two payload-encoding rules below are
easy to get backwards.

### 5.1 Capture at call time: `register_media` → `finalize_media_registration`

There is no after-the-fact discovery path for a generated Roblox asset (see
`genvid-roblox-studio-ops` for why) — capture has to happen at the moment of
the call. The finalize step's shape, exactly as shipped
(`finalize_media_registration.py`):

- `storage_class = "platform"`, `locator_type = "platform_asset"` — the
  `locator` is the platform's own URI, e.g.
  `rbxassetid://123456789012345` (synthetic example).
- Durable identifiers are roblox.com-scoped, using all four prefixes:
  `asset_id:`, `mesh_id:`, `texture_id:`, `generation_uuid:`.
- `generation` is passed as a **RAW JSON OBJECT** (`finalize_media_registration.py:152-154`)
  — **not** a string. This is the opposite encoding from the corrections
  payload in §5.2 below; see the asymmetry callout there.
- `generation.connection_name` (nested inside the `generation` object, NOT
  the tool's own top-level `connection_name` field — that flat field names an
  org **storage** connection and is meaningless for a platform-tier capture)
  **defaults to `"roblox-studio-cube"`** — the seeded name for the
  Studio/Cube MCP integration. Only set it explicitly if your org registered
  the generator under a different name (note the single-seeded-name
  limitation this implies).
- On finalize, set `target` / `stage` for asset anchors: `target = "roblox"`,
  `stage = "roblox/r15-rigged"` for rigged meshes. This is what makes the
  artifact conformance-checkable afterwards with `check_conformance`.
- **One media row per `generate_mesh` part.** A multi-part generation call
  produces several parts; capture each as its own media row.
- **Upload a GEOMETRY proxy, not a render.** `proxy_filename` decides what
  Genvid holds, and for a platform-tier capture it is the **only** thing Genvid
  will ever hold: the `locator` is an `rbxassetid://` identifier, so no party
  holds bytes anyone can fetch later. Export a reduced `.glb`/`.fbx` and PUT it
  to the `proxy_upload_url`. With an image proxy — or with no proxy at all,
  which the platform tier permits — the media is permanently un-previewable in
  Genvid's 3D viewer, and there is nothing to derive a proxy from after the
  fact. Keep it under 40 MB (decimate; parse cost tracks vertex count, not
  bytes). At the `registered` tier the same proxy must be a DERIVED mesh — one
  byte-identical to the original is rejected at finalize (ADR-022).
- **The duplicate-identifier retry law** (`finalize_media_registration.py:150`):
  a retried capture of the **same platform asset** will hit a loud `(org,
  scope, value)` rejection on **artifact-scoped** identifiers
  (`asset_id:`/`mesh_id:`/`texture_id:`) — expected behavior on the
  moderation-retry path `genvid-roblox-studio-ops` teaches, not a bug to work
  around. A shared `generation_uuid:` is different: it is expected to repeat
  freely across every part-media row from **one** call.

### 5.2 Hand-tuned values: `record_approved_corrections`

Full call shape: `project_id`, `asset_id`, `target`, `stage`, `media_id`,
**`link_type`** (must match an existing asset↔media link — the staleness
anchor is `media_id` + `link_type` together, not `media_id` alone), **`payload`
as a JSON-object-encoded STRING**, `note`. The tool returns `state`.

`payload` is a string, not a raw object, because the correction payload's
keys are target-defined and dynamic (e.g. per-bone posture-tweak names) — a
plain object field would emit an open (`additionalProperties: true`) JSON
Schema shape that fails strict-mode grammar compilation, per the tool's own
docstring. It mirrors `finalize_media_registration`'s
`pre_signed_c2pa_manifest` field exactly.

**Encoding asymmetry, stated explicitly so it doesn't get flipped:**
`record_approved_corrections`'s `payload` = a JSON-object-encoded **string**.
`finalize_media_registration`'s `generation` = a **raw object**. These are
the same pack's two closest-looking parameters and they take opposite
encodings — check which tool you're calling before formatting the value.

**Not yet on prod:** `record_approved_corrections` is published in
`boundary-tools.md` at `status: designed` — documented and described in this
pack's reference material, but not yet deployed to production as of this
pack bump.

### 5.3 Staleness read paths, cheapest first

Three ways to check whether a recorded correction is still fresh against the
current media, in order of what they cost to call:

1. **The write tool's own returned `state`.** Covers the re-approval flow —
   calling `record_approved_corrections` again with a new `media_id` after a
   correction has gone stale returns the flipped-back-to-`fresh` state
   directly, with no extra read needed.
2. **`export_provenance_report`** — project-wide, but **active rows only**;
   it carries no correction history, only the currently-active row per
   `(asset, target, stage)` axis.
3. **The `genvid` CLI's `getAsset` operation** — the per-asset detail read.
   `getAsset` is `x-genvid-cli-tier 2` (listed in `cli-operationids.lock`),
   and `include_correction_history` is a query param on that same operation
   — set it to see superseded rows, not just the active one. The CLI
   authenticates via its own OAuth 2.1 + PKCE browser login
   (`context/api/cli-usage.md`), a separate credential from the MCP session —
   an agent cannot extract and reuse its MCP session's server-side bearer
   token for this; the CLI does its own login. This is the same CLI-only
   routing this pack already uses elsewhere for reads MCP doesn't (yet)
   surface — `assets_read` MCP wiring for this staleness read is deferred.

### 5.4 Provenance rules for animation asset naming

From `docs/animation-provenance.md@retired-2026-08` (rules recorded against
the titan animation set):

- **Never put a source brand name in a Roblox asset's title.** A submission
  was rejected over exactly this. The rejection was over the brand name
  appearing **in the asset title**, not over the motion itself — the source
  clip's license permits using the animations in games. Scrub names to a
  convention like `SmallWalk_v1`, not `MixamoWalk_v1`.
- **Approved sources:** CMU Motion Capture Database (free for any use,
  including commercial), Quaternius (CC0).
  **Forbidden sources:** Ubisoft LaFAN1 and Bandai Namco motion datasets
  (non-commercial licenses); Roblox catalog animations are also out —
  **except** onto a true R15 rig, where catalog anims do retarget cleanly
  (they only fail to retarget cleanly onto the Meshy-convention skeletons
  this pipeline otherwise uses).
- **The Mixamo download rule**, with its actionable half: **select the stock
  X Bot character FIRST**, under Mixamo's Characters tab, before downloading
  a clip. Character selection is the whole mechanism here — downloading a
  clip while an uploaded custom rig is the current character silently drops
  the head/hand/foot channels and freezes the hips, and there is no
  "remove uploaded character" option to undo that after the fact; you must
  not have uploaded a character in the first place. Download settings: FBX,
  30 fps, keyframe reduction **none**, **In Place**.

---

## 6. Cross-references — where the rest of this lives

| What you want | Where |
|---|---|
| Studio MCP transport, session mechanics, moderation-retry discipline, two-point scale calibration | `genvid-roblox-studio-ops` |
| Posture-tuning method (pelvis rule, sign convention, per-foot dials, the zoo tuning toolkit — recorded against the titan build) | `docs/posture-tuning-method.md@retired-2026-08` |
| Tier reconciliation — why platform-tier captures (this skill) don't go through `genvid-media-registration`'s archival flow | `genvid-media-registration` (scoped note there); platform tier has no ingest path — no party holds bytes to hash, so there is nothing to register through that skill's flow |
| Conformance checking a captured artifact | `check_conformance` — correctly refuses on platform-custodied media: it measures the artifact's bytes, and a platform-custodied asset has none for it to read |
