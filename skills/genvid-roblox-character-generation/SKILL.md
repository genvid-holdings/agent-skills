---
name: genvid-roblox-character-generation
description: Generation recipes for a rigged, textured, in-game-ready Roblox character via the MCP-first path — plate craft that conditions Cube's GenerateModelAsync, the retired Meshy operational record, the Mixamo-to-R15 rig recipe and skinned-rig wiring, world-space animation transfer and asset-naming provenance rules, and the governance calls (register_media/finalize_media_registration, record_approved_corrections) that make the output governed. Illustrated throughout with a real production's giant characters as the worked example. Does not cover Studio/MCP transport or session mechanics — see genvid-roblox-studio-ops.
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

**Worked example:** every recipe below is illustrated with one production's
four elemental giant characters. That production is undisclosed, so its
characters appear here only under neutral stand-ins — a size word (`Small`,
`Large`), a height in studs, an element — never under its own type keys, and
`<Name>` marks a slot its naming would fill. Those four are **the example
customization**,
not the subject of this skill:
the recipe is a general Roblox character-generation pipeline, and code/asset
names below drawn from that build (`animSpeedScale`, `HipHeightStuds`
on a character template, its own spawn function, and so on) are simply that
production's naming, carried
through because the underlying technique they illustrate is what this skill
teaches. Where a step below is witnessed only in that build and has not
been generalized beyond it, the text says so explicitly rather than implying
it holds for every character.

Knowledge below was copied out of a retired fal-chain pipeline repo (built
originally for a different, human-scale character) and
out of the worked example's own build. Citations carry `path@retired-2026-08`
— that repo is read-only source material, not something this pack depends on
at runtime. It is that production's own repo, so it is not named here. Items marked **[mining]** were recovered from working-session
transcripts, not re-witnessed in a file; treat them as reliable operational
lore, not verified fact, and do not upgrade the label if you re-encounter the
claim elsewhere.

---

## 0. Bind every plate to a governed asset — before you generate

**Concept plates are governed media, not scratch files.** A plate is the thing a
human approves, and approval is the gate the whole rest of this skill hangs off:
it conditions `GenerateModelAsync`, so it decides what the mesh looks like.
Leaving candidates as local PNGs means the decision happens somewhere with no
provenance, no review workflow, and no record of what was rejected.

Do this **before** the first generation call, not after:

1. **Find or create the asset.** `assets_read(method="list", project_id=...)`
   to see whether the character already exists; otherwise
   `assets_write(method="create", project_id=..., name=..., asset_type=...)`.
   The asset is the character, not the plate — every candidate plate binds to
   the same asset. **The `description` you create it with names the
   production**, e.g. `"<production title> character: <name>"`. That title is
   the production's, not this pack's: the runner reads it from the manifest's
   `production_title` field (§7) and **refuses the bind** when the field is
   missing rather than defaulting to anything. Supply the real title; never a
   placeholder, because a description is governed content written once and read
   by humans afterwards.
2. **Claim its image task.**
   `production_write(method="create_assignment", project_id=..., resource_type="asset",
   resource_id=<asset_id>, task_type="assetImage", workflow_status="in_progress",
   assigned_to_email=<reviewer email>)`.
   Required even for a role that could bypass the gate — an unclaimed bind
   leaves the task showing untouched. See `genvid-agent-generation` Step 0.
   Pass the reviewer's own email explicitly, never "me": on a
   runner/orchestrator chain "me" resolves to whichever agent holds the MCP
   session, and the task lands assigned to nobody and never in_progress.
3. **Generate, then bind each candidate** with `ingest_generated_media`
   (`link_type="cast_member_image"`, `asset_id=<asset_id>`), carrying the model,
   prompt, and params you actually used.

**The claim law covers every bind, not only the one that creates the asset.**
Steps 1-2 above (find/create the asset, claim its image task) gate the FIRST
write against a NEW asset. A later stage that binds more media to an asset
that already exists — a second mesh, a re-rig, a re-textured surface pass, a
published clip — is exactly as capable of writing to an unclaimed asset, and
of hitting the boundary's 409 on one the reviewer already approved, as the first
bind was. Check the claim before that write too: list the asset's
assignments, claim the assetImage task if none exists, and reopen it to
`in_progress` if it is `approved` (witnessed 2026-09-07: the boundary answers
409 to a bind on an approved task) — reopen `in_review` the same way
on the same reasoning, though its 409 is not itself separately witnessed. The
runner's own `genvid_bind.ensure_claim` is this check for every site that
binds to an asset it did not just create (`plate bind --only front/all` on an
existing asset, `plate bind --only views`, `mesh.bind`, `rig.bind`,
`rig.surface_prep`, `clips.bind`, `biome bind` on an existing asset, `biome
sky-bind`, `biome kit-bind`, `biome kit-model-bind`); do the same
read-then-claim-or-reopen before any bind you run by hand against an asset you
did not just create. Writing the reopen payload is not enough on its own: the
reopen has to have *run* before the bind, or the bind still lands on the
`approved` task and 409s — a fire-and-forget reopen followed by the bind on
the next line is the same race. The runner enforces this by refusing to bind
until you record the task's post-reopen `workflow_status` on the manifest.

**Bind every variant you would show a human, including the ones you expect to
lose.** A/B forks are the point of plate craft (see the variant-editing rule in
§1), and the rejected candidates are what make an approval legible later.

**Keep the provider's result URL.** Hosted providers (fal and most others)
return a result URL; pass it as `source_url` and Genvid pulls the bytes itself.
A runner that downloads the image and discards the URL forces you onto the
local-file path for no reason. If you *do* only have a local file, bind it with
`genvid import-generated-media <project-id> -c multipart 'rendered_output: @<path>, ...'`
— **never `image_base64`**, which silently truncates a full-resolution image and
leaves Genvid signing a corrupt file that looks successful.

> **[mining]** Standing direction on the worked example's production
> (2026-08-25): generated assets are tracked in Genvid, never only locally, and
> review happens in the Genvid interface rather than on files handed over in a
> terminal. Recorded here because it generalizes — any production driving this
> skill wants the approval gate inside the governance boundary, not beside it.

**You may reject previously-selected media under a conversation decision — you
may never approve, and never delete.** Approval is a human act: a task's
`workflow_status` moves to `approved` only in content review (see
`genvid-agent-generation` Step 0). Media selection is a separate, narrower
ladder — `approve_media`'s `selection_status` (`selected` / `pending` /
`discard`) — and it has one carve-out for the agent: when a decision made *in
conversation with the production owner* supersedes an already-selected
candidate — a re-roll the owner asked for, a rejected model whose plate stays
selected, a mesh replaced on the owner's explicit instruction — flip that
media with `approve_media(project_id=..., media_id=..., selection_status="discard")`.
This is reversible and it is not a rejection you originate; it transcribes one
the owner already made. Never call it with `selection_status="selected"` on
your own judgment — selecting is still exclusively a human act. If the
covering task is already `approved`, the boundary refuses the selection
change until the task is reopened to `in_progress` first — the same
claim-or-reopen `set_assignment_status` step this section already describes
for an unclaimed bind (attested from the platform's own approval-guard
behavior, not separately witnessed).

Pair every discard with a `record_decision` call so the supersession has a
durable record independent of chat history — never discard silently. The
boundary hard-requires `project_id` and `decision` on every `record_decision`
call (missing either raises `MISSING_PARAM`), and a supersession is itself a
rejection of that specific candidate, so `decision="reject"` is the correct
verdict — recording that this media lost out, not that the agent approved
anything. A `reject` verdict additionally requires at least one
`critique_tags` entry naming an *active* `critique_taxonomy_class.code`; an
invented or free-text tag (e.g. `"composition"`) is refused with an unknown
taxonomy code error — this already happened on this production (a biome
prop's glow-puddle discard, 2026-09-08). There is no MCP-facing list call for the
taxonomy today; pick the `critique_taxonomy_class.code` whose seeded v1
description actually matches the owner's stated reason —
`prompt_adherence`, `subject_set_violation`, `character_canon_consistency`,
`rendering_style_drift`, `composition_framing_scale`, `motion_physics`,
`temporal_continuity`, `hallucinated_objects_anatomy`,
`burned_in_text_artifacts`, `audio_voice_fit`, `lipsync_face`,
`pacing_duration` (attested from the boundary's seed vocabulary, 2026-09-08;
the vocabulary is versioned and additions are possible, so treat this as the
current list, not a closed guarantee). If none of these actually describes
the reason, do not coin or force-fit a tag: there is no valid `reject` call
without one, so the discard itself waits — hold the media `selected` (or
`pending`), give the owner the precise reason and ask them to name a tag or
have one added to the vocabulary, and only flip `selection_status="discard"`
once you have a code you can honestly record. An unrecordable discard is
never performed silently; it is not performed at all until it can be
recorded. The exact call shape:

```
review_write(
    method="record_decision",
    project_id=...,
    decision="reject",
    media_id=...,
    critique_tags=["composition_framing_scale"],
    note=<cites the specific conversation decision>,
)
```

And never delete media for any reason: a rejected or superseded row is
provenance, not clutter. When you bind the replacement, put
`supersedes_media_id: <old media_id>` in the new row's `params` so the
lineage from candidate to candidate is on the graph, not only in the discard
note.

**Every generated kit/prop asset description carries the biome's colour
references.** When an asset belongs to a biome (a kit item, a prop, any
set-dressing/greenery asset), put that biome's palette hex list in the
asset's own description — not only in the one-off generation prompt — so a
later re-roll built from the asset (rather than from the original prompt) is
still conditioned on the right palette. Missing this is exactly what
happened on 30 prop assets across two biomes (caught and fixed 2026-09-08);
treat the hex list as a required field of the description, not decoration.

---

## 1. Plate craft (LIVE — plates condition `GenerateModelAsync`)

This stage is not retired: Studio's `GenerationService:GenerateModelAsync` is
image-conditioned (see `genvid-roblox-studio-ops` for the surface comparison),
so the plate you feed it still drives the result the way it always did.

- **Always inspect and re-roll the plate before spending on 3D.** A-pose with
  clear limb gaps.
- **[mining]** **The element-body trick** — build the creature *out of* its
  element (ice, lightning, stone, ...) while keeping the two-arm/two-leg body
  plan intact. In the worked example, this is the move that carried a giant-
  character concept through its approval gate.
- **[mining]** **Variant-editing from an approved plate** is the cheap way to
  fork A/B options — edit the already-approved plate rather than generating a
  fresh one from scratch, so approval risk on the base concept is spent once.

**Worked example, carried verbatim** (`PLAYBOOK.md:57-79@retired-2026-08`) —
this particular prompt predates the worked example's production and was written for a
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
For an elemental character like the worked example's four, adapt the
"remove detachable gear" clause to the element-body trick above — the intent
(a clean, symmetric A-pose with clear limb gaps and no clutter) is what to
carry forward for any character concept, not this prompt's specific wardrobe.

---

## 2. Retired-path operational record (Meshy) — HISTORICAL

Meshy (`fal-ai/meshy/v6/image-to-3d`) was the image-to-3D backend before the
Cube/MCP pivot. It is not the live path — Cube's `GenerateModelAsync` is —
but the operational facts below are worth keeping because the skinned-rig
recipe in §3–4 was built and proven against Meshy output on the worked
example's characters, and anyone still holding a Meshy-rigged GLB for any character
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

Other operational facts, gathered while building the worked example's characters:

- **[mining]** The **rigged-export polygon cap is exactly 20,000** triangles.
- **[mining]** Rigging jobs run **silent for 10–20 minutes** — a long
  unresponsive job is expected behavior, not a hang.
- **[mining]** `enable_rigging: true` **destroys non-humanoid silhouettes.**
  In the worked example, a cloud-float, lightning-bodied character needed the *unrigged*
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
of its characters:

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
  this — it is a search over candidates, not an analytic pick. **The pick is
  only trustworthy on a walk.** The score compares foot trajectories against a
  walk-shaped truth, and on the leg B rig it chose the wrong frame for every
  non-walk clip (a fall and a stomp both landed on a map with up pointing
  forward, witnessed 2026-09-08) while the walk and idle on the same skeleton
  agreed. The map is a property of the source skeleton, not of the clip:
  transfer the walk first, read its pick from the poses doc (`g`), and pass
  `--g=<that name>` for every other clip on that skeleton (`poses.py` records
  `g` and `g_forced` on every doc so a review can tell which it was).

**The transfer law:** in the worked example, ALL of the production's clips were
transferred onto the Meshy-skeleton rigs by `stage_h_poses.py`'s world-space
transfer (`docs/animation-provenance.md@retired-2026-08`); the native-Meshy
walks that predate this are recorded there as **SUPERSEDED**, not
as a live alternative. `stage_h_anim.py:1-19@retired-2026-08` is cited here
**only** for one fact — the standard R15 walk track retargets badly (hip keys
land at 90+ degrees, legs fold to head height) onto Meshy's Mixamo-convention
skeletons — and that fact is labeled as the **retired native-clip route**.
Its own recipe (Meshy's own walking clip needs no retargeting because it was
authored on that exact skeleton) is the **superseded path**, not the current
law; do not read `stage_h_anim.py` as describing how production animation
transfer works today, for the worked example's characters or any other.

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
own character-visual-identity task, hence the name). Steps 1 and 8, and each
clause below marked individually, come from working-session transcripts
rather than a committed file; the full recipe was then re-witnessed end to
end, which is what the **[mining, full recipe re-witnessed]** tag records:

1. **[mining, full recipe re-witnessed]** **Strip the
   importer's avatar-scaling metadata, then REBUILD it.** The importer's own
   scaling metadata silently reverts hand-done `HumanoidRootPart` surgery if
   left in place, so it has to be stripped and then explicitly rebuilt: the 6
   `Humanoid` NumberValues, per-`Bone` `OriginalPosition`, and
   `AvatarPartScaleType = "Classic"`.
2. Rebuild `HumanoidRootPart` as a torso box at the `LowerTorso` bone.
3. `WeldConstraint` the mesh to it (`CanCollide = false`, `Massless = true`).
4. Upright `AlignOrientation` (`OneAttachment`, `PrimaryAxisOnly`, axis `Y`,
   rigid). **[mining, full recipe re-witnessed]**
   `AlignOrientation`'s `PrimaryAxis` **defaults to `X`** — leaving the
   default silently floats the rig horizontal instead of upright; it must be
   set to `Y` explicitly.
5. `RequiresNeck = false`, fall states off.
6. `AutomaticScalingEnabled = false`, **then** pin `HipHeight` — Play-start
   recomputes `HipHeight` to garbage if scaling is still enabled when it's
   set. **[mining, full recipe re-witnessed]** The
   `HipHeight` formula is `hip = (rootY − feetPlane) − rootSize.Y / 2`; a
   fixed `12.5` figure recorded from an early session on one character
   (`archive/2026-08-retirement/sdd-ledger/progress.md:145@retired-2026-08`)
   is **not canonical for any character** — it changed on every import and
   was specific to that run's geometry. Use the formula, not the number.
7. Release the rig via `ChangeState(GettingUp)`.
8. **[mining, full recipe re-witnessed]** **Spawn placement
   reads the `HipHeightStuds` attribute**, not the part bounding box — part
   bboxes lie on these rigs, so your character-spawn code must read the
   attribute, not `GetBoundingBox` (in the worked example, this is that
   production's own spawn function).

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
the worked example's animation set):

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
| Posture-tuning method (pelvis rule, sign convention, per-foot dials, the zoo tuning toolkit — recorded against the worked example's build) | `docs/posture-tuning-method.md@retired-2026-08` |
| Tier reconciliation — why platform-tier captures (this skill) don't go through `genvid-media-registration`'s archival flow | `genvid-media-registration` (scoped note there); platform tier has no ingest path — no party holds bytes to hash, so there is nothing to register through that skill's flow |
| Conformance checking a captured artifact | `check_conformance` — correctly refuses on platform-custodied media: it measures the artifact's bytes, and a platform-custodied asset has none for it to read |

---

## 7. The zero-touch runner

`runner/cli.py`, under `skills/genvid-roblox-character-generation/runner/`, is a
stdlib-only Python package invoked as `python3 runner/cli.py <group> <cmd> ...`.
Each group — `init`, `plate`, `mesh`, `rig`, `studio`, `clips`, `eval`,
`record`, `biome` — is its own module exposing `register(subparsers)`; `cli.py` imports
each lazily and skips one that fails to import rather than breaking the rest.

**Nothing bound to one title lives here.** A title's own chains, its Studio
steps, its attribute names, its world design and its eval thresholds belong in a
per-title skill
that DEPENDS on this pack; the dependency is one-way and this pack never imports
one. Three manifest fields carry the production's own identity into the work this
pack does, and **none of them has a default**: `project_id`
(`runner init --project`, `runner biome init --project`),
`production_title` (`--production-title` on both), the string every asset
description this chain creates is built from — `plate bind --create-asset`,
`biome bind --create-asset` and `biome kit-bind`'s prop batch all read it
through `manifest.production_title()`, which raises rather than guessing — and
`design`, the title's own **design document**:

```json
"design": {
  "palettes":     {"<biome name>": ["#RRGGBB", "..."]},
  "hud_tokens":   {"<role>": "#RRGGBB"},
  "kit_props":    ["<prop name>"],
  "style":        "<prompt fragment naming the art direction>",
  "hud_style":    "<prompt fragment describing the HUD's own layout>",
  "luau_modules": {"design_tokens": "<module name>", "lighting": "<module name>"}
}
```

Which biomes a title has and what colour each one is, what its HUD shows and in
what token hexes, which props its set-dressing kit contains, the words that name
its art direction, and the names of its own design Luau modules are all design
decisions owned by that title — never general technique, so none of them is a
constant here. `runner/design.py` is the only reader: `design.load(m)` and its
typed accessors (`palette`, `biome_names`, `hud_tokens`, `kit_props`, `style`,
`hud_style`, `luau_module`) **raise naming the missing key** rather than
substituting anything, because a placeholder would silently condition a paid
generation and the governed `params` row that records it. `biome init --biome`
therefore has no fixed choice list: the names come from the document.
**The per-title skill stamps it**, next to the park folder and the title, and
`biome init --design <file.json>` is the other way in for a caller driving this
pack directly — optional there and only there, so the stamping seam still works.
A per-title skill stamps all three. `studio.register_steps(template_dir, stage_of=, render_defaults=,
ingest_handlers=)` is the seam: the directory is searched for `<step>.luau`
before this package's own, `stage_of` puts the new steps in `STEPS` and names the
manifest stage each ingest lands on, `render_defaults` merge into
`RENDER_DEFAULTS`, and `ingest_handlers` maps a step to
`handler(m, result, out_dir)` that `studio.ingest` calls instead of its own
branches. Two template parameters exist for the same reason: `PARK_FOLDER`, the
Luau expression for the folder a wired template is parked under and every later
step reads it back from, and `HIP_ATTR`, the attribute the ground-fit hip is
written to. Their defaults here are neutral
(`game:GetService("ServerStorage").Assets.Characters` and `HipHeightStuds`); a
manifest overrides the folder per character with `m["studio"]["park_folder"]`
(`studio.set_park_folder`), which beats any registered default. A per-character `manifest.json` gates the chain: a stage
counts as done only once it carries a Genvid media id, so a failed run leaves a
governed partial record instead of an ungoverned pile of local files.

**Two environment variables are required, with no defaults.** `GAME_ANIMS_DIR` is
the directory a title's Rojo project maps its animations from, where `clips build`
writes a KeyframeSequence `.rbxmx`; `ANIM_LIBRARY_ROOT` is the animation archive
tree `clips transfer` resolves its `mixamo-archive` / `quaternius` candidates in
(`--anims-dir` and `--archive-root` override them per run). Both belong to the
title, so `clips.anims_dir()` and `clipsources.archive_root()` raise naming the
variable instead of guessing a checkout. A wrong guess is worse than a refusal in
both cases: a `.rbxmx` written where nothing syncs never reaches Studio, and an
archive root that misses reads exactly like a clip with no archive fallback, which
pushes a caller onto a paid vendor leg it did not need. A per-title skill exports
both from its own config.

**Stage order.** A skinned-rig character runs `plate -> mesh -> rig -> rest ->
groundfit -> clips -> wire -> record`. A static model with no Humanoid and no rig
skips straight to `plate -> mesh -> wire -> record`: there is no rig, ground-fit,
or clip stage for something that never gets a skeleton. A biome/location plate or
the HUD viz-dev asset carries its own shorter stage order on the manifest itself.
A variant that is the same rig at a different scale under a second template name
re-runs only the scale-dependent tail (`scale`, `dump_rest`, `groundfit`, `wire`,
`park`) against a second manifest, copying the winner's plate/mesh/rig stages
across so the original manifest is never touched; that chain and the static
model's two title-specific steps live in a per-title skill, not here.

**Studio steps.** Studio-side work is Luau templates under `runner/luau/` the
driving agent renders with `runner studio emit <step>`, executes over the
Studio MCP, and feeds back with `runner studio ingest <step>`. Ground-fit is
five steps, not the three the interface contract's single formula suggests,
because a standing Humanoid hovers above its own `HipHeight` by a per-rig
constant, and the loop's exit test has to be a measurement, not an assumption:

    studio emit groundfit ...; ingest groundfit ...    # EDIT: measures SoleOffsetStuds
    studio emit settle ...   ; ingest settle ...       # PLAY: measures the hover constant
    studio emit sethip ...   ; ingest sethip ...       # EDIT: writes the corrected HipHeight
    studio emit settle ...   ; ingest settle ...       # PLAY: verifies the fix
    studio emit probe_feet ...; ingest probe_feet --lod close|far ...

Two hip numbers come out of this loop for two different consumers.
`SoleOffsetStuds` is the raw geometric distance from the HumanoidRootPart's
bottom to the rest pose's lowest vertex — `(rootY - feetPlane) - rootSize.Y/2`
— and is what an anchored, non-Humanoid placement (ZooGen) reads. `HipHeightStuds`
is what `Humanoid.HipHeight` needs so a *live* rig's soles actually touch the
ground: `SoleOffsetStuds` minus the hover constant. Using one where the other
is wanted floats or sinks the rig by exactly that constant. The bake-off's
second settle measured the constant at 0.45 / 0.89 / 1.03 studs on its three
legs and the corrected loop converged all three to within +-0.006 studs,
standing and mid-walk (witnessed 2026-09-04).

`build_kfs` and `publish_clip` are the two Studio steps that close the clips
stage with no Save-to-Roblox click: `build_kfs` builds the KeyframeSequence in
Studio from a poses JSON the runner serves over local HTTP (no Rojo sync
needed to evaluate a clip), and `publish_clip` calls
`AssetService:CreateAssetAsync` on it directly — confirmed on the bake-off run
to return a real Roblox asset id from the MCP bridge's Edit context; an
earlier record that `CreateAssetAsync` rejects a MeshPart/Model never covered
a KeyframeSequence (witnessed 2026-09-04). `wire` (same stage as `park` and
`capture_ids`) also has to force `Humanoid.RigType` to R15 and destroy any
`AnimationController` the 3D Importer parked beside the Humanoid the runner
creates: both were found, on the bake-off run, to silently stall every
animation track's `TimePosition` at zero — an R6 Humanoid never advances an
R15 KeyframeSequence, and a live `AnimationController` competes with the
Humanoid's own Animator so neither one advances (witnessed 2026-09-04).

**Clip transfer laws (witnessed 2026-09-08 on the leg B rig, pack 0.9.5).**
Four things have to be true at once for a library clip that moves the hips
(a stomp, a kneel, a knockback, a fall) to read correctly in the game; each
was found by a bench that samples the LowerTorso bone's world position while
the published clip plays, and each cost a publish-and-bind round:

1. *Root motion is emitted.* `poses.py` writes the root bone's translation per
   frame under `frames[i].r` (the hips' world delta, mapped by the same `g` as
   the rotations, scaled by rig/clip height, expressed in the root bone's
   rest frame); `kfs.write` and `build_kfs` put it in the LowerTorso pose
   position. A rotation-only transfer plays every crouch as legs folding under
   a pelvis pinned at standing height and a fall as a torso rotating around
   hips that stay in the air (`--no-root` keeps that output; the accepted walk
   and idle were built on it and are not rebuilt).
2. *The axis map is forced to the walk's* (`--g=`, above). The tangled legs on
   the stomp were wrong rotations, not only missing translation. This rule is
   for the EMPIRICAL branch, which vendor-library and rig-authored donors take.
   A native Mixamo donor (the archive packs) carries a toe bone, so `poses.py`
   takes its ANALYTIC branch -- facing measured from the rest skeleton, clip
   independent -- where `--g=` is not consulted (it only stamps `g_forced`);
   walk and death then share the map by construction. Confirm it: all the
   runs on one rig print the same `analytic g (clip faces (...))` line
   (witnessed 2026-09-10 on two adopted rigs).
3. *The pose tree mirrors the real bone chain.* The Animator matches rotations
   by pose name whatever the tree, but it applies a TRANSLATION only when the
   tree is `HumanoidRootPart > HumanoidRootNode > LowerTorso` (four variants
   tried; only that one moved the hips). `kfs.write` always writes the node
   pose; `build_kfs` inserts it when the template carries that bone.
4. *The translation is divided by the model scale.* The Animator multiplies a
   pose translation by `Model:GetScale()` (a 20-stud pose moved a 0.53-scale
   giant 10.6 studs; the same 20 on `Bone.Transform` moved 19.4). `build_kfs`
   reads `template:GetScale()`; `kfs.write` takes `root_scale`, which
   `clips build` feeds from `stages.wire.result.scale`.

5. *A clip is bound to the skeleton it was built for.* A clip built on the
   16-bone runner rig plays NOTHING useful on a 15-bone old-pipeline rig
   (the hips and head never moved in 22 s; one foot lifted), because those
   rigs hang `LowerTorso` straight under `HumanoidRootPart` with no
   `HumanoidRootNode` for the translation to ride on. Transfer onto that
   rig's own rest dump instead: with the tree `HumanoidRootPart > LowerTorso`
   (no node, which `build_kfs` inserts only when the template has the bone)
   the translation DOES apply on those rigs (witnessed 2026-09-10: the
   8.7-hip rig's hips moved -7.9, the 15.0-hip rig's -13.9).
6. *Cadence follows the square root of height.* `timing.scale_time` stretches
   a clip by `sqrt(height / 8)`, so a clip authored at height H plays on a
   rig of height h at speed `sqrt(H / h)`; the game's `deathAnimSpeed` dial
   is exactly that number when one rig borrows another's clip (a 50-stud rig
   plays a 95-stud rig's death at 1.378 = sqrt(95 / 50)). `build_kfs` needs the same
   factor as `{{SCALE}}` (`1 / timing.cadence(height)`: 1.58 at 20 studs,
   2.09 at 35, 2.5 at 50, 3.45 at 95).

And one reference rule: root motion is measured from the clip's FIRST FRAME
(`--root-ref=first`, the default), because library clips do not all start at
the bind pose (Meshy's stun and slam start 17 to 43 studs from the T-pose
hips at giant-character scale, which bind-relative motion turned into a mesh sitting
off its collider for the whole clip and snapping back at the end);
`--root-ref=bind` is for a clip that starts mid-air or crouched and should
read that way. Check `frames[0].r` and `frames[-1].r` before publishing: an
Action clip the game holds (a stun, a death) keeps its last-frame offset for
as long as it is held, and a clip that blends back to idle snaps from it. A
repeating library clip (Angry_Stomp is eight seconds of stomping in place)
is trimmed to one action before building, and its impact is the first foot
landing after the peak lift, not the global minimum the default detector
finds across hands and feet.

**Bench before you publish, sample the right property.** The bench that
proves a clip is a Play clone with the published id (a parked, unpublished
sequence never advances) sampling `Bone.TransformedWorldCFrame` for the
hips, head and a foot against the sole plane. `Bone.WorldPosition` /
`WorldCFrame` EXCLUDE the bone's own animated `Transform`, so a sampler on
them reads every root-motion hip as 0 and the clip as "nothing moves"
(false negative witnessed 2026-09-10).

**Binding a published clip (shape witnessed 2026-09-10 on two bound clips).**
`register_media` at `storage_class="platform"` with `kind="animation-clip"`,
`link_type="cast_member_model"`, a `.glb` filename and
`mime_type="model/gltf-binary"` as the media-type hint (a `.rbxmx` name is
rejected; no proxy), then `finalize_media_registration` with
`locator="rbxassetid://<id>"`, `locator_type="platform_asset"`, the
`roblox.com` `asset_id:` identifier, `size_bytes` measured from the poses
file (stated in `generation.params`), `duration_seconds` = the scaled
length, and NO `target`/`stage` (the keyframesequence stage is refused).
`clips bind` writes exactly this. Attested cost is 0 only when no vendor
call was made (local Blender + Studio publish) -- say why in params.

**Adopting a rig that already exists (`runner rig adopt`).** A parked template
with no manifest — the four old-pipeline characters, or a rig handed over as a
bare template — gets a manifest whose chain starts at `rest`; plate/mesh/rig
are not on it and are not pretended. The whole sequence for one new clip:

    runner rig adopt --name Small --template <StudioTemplateName> --height 20 --project-id <project-id> \
        --asset-id <cast-member uuid> --assignee <reviewer email> \
        --production-title '<production title>' --out-dir out/small-adopted
    runner rig adopt-emit --manifest out/small-adopted/manifest.json adopt_inspect   # Edit
    runner studio ingest adopt_inspect --manifest ... <result>                        # fills wire: scale, hip, root-node flag
    runner rig adopt-emit --manifest ... dump_rest                                    # Edit, against the parked template
    runner studio ingest dump_rest --manifest ... <result>
    runner clips transfer --manifest ... --clip Death --candidate 1                   # archive fall (no vendor rig task on an adopted rig)
    runner clips build-kfs --manifest ... --clip Death   # serve <out_dir> on 127.0.0.1:8765 first; Edit
    runner clips publish-clip --manifest ... --clip Death                             # Edit
    runner studio ingest publish_clip --manifest ... --clip Death <result>
    runner clips bench --manifest ... --clip Death                                    # PLAY, Server; blocks ~clip length
    runner studio ingest bench_clip --manifest ... --clip Death <result>
    runner clips bind --manifest ... --ids Death=<roblox id>                          # then the orchestrator runs the two payloads

`name` is the brand-free stem the titles are built from; `--template` is the
Studio name and is what every Studio step targets, under the park folder
(`--park-folder`, or `PARK_FOLDER`'s default), not workspace.
`--production-title` is required here for the same reason it is on `init`: this
chain ends in `clips bind`, which writes governed media under an asset whose
description carries the title, and there is no default to fall back to. Demanding
it at adoption fails before any Studio step runs rather than at the first bind.

**Bench a published clip (`clips bench`).** Play mode, Server datamodel, one
blocking bridge call: a clone of the template plays the published id and the
step reports `hipsDrop`, `hipsBack`, `headEndAboveSole` (sole plane =
`HIP_ATTR` + half the root height below the root centre), `heldAtEnd`,
and files the timeline. A death clip passes when the hips drop by about the
hip height, the head ends above the sole plane, and the end pose holds. Pass
`--speed` for a walk (animSpeedScale) or a borrowed clip (law 6). `frozen` is
the field that says whether those numbers mean anything: the step schedules
the game's own end-pose hold (`AdjustSpeed(0)` just before the clip ends);
when `frozen` is false the track ran out first, the Animator blended the
clone back to its bind pose, the numbers describe that standing pose, and the
bench must be re-run. Every Studio step prints its result as one
`RUNNER_RESULT <json>` console line; `execute_luau` returns only a script's
return value, so read the line with `get_console_output` (expensive on a
chatty place) or wrap the rendered step to capture `print` and return it.

**Steps a per-title skill adds.** A title that needs a Studio step of its own —
parking a static model in its own folder, or killing a live character through its
own remote to record a death timeline — registers the step rather than adding it
here. Such a step renders through this renderer with the title's own defaults and
ingests through its own handler, so its attribute names, its remotes and the
manifest keys it writes stay out of a pack that is mirrored publicly.

**Eval matrix.** `runner eval` prints and writes the eval-matrix table, rows
E1-E29, reading only files on disk plus the manifest — it never imports another
stage module, so it runs standalone regardless of which stages exist yet. A gate
row with no evidence on disk reports FAIL, never PASS and never silently skipped;
a non-gate row with no evidence reports PENDING; rows that measure a Studio
artifact the runner cannot itself produce (E13/E14 far-LOD grounding, E24 the walk
probe, E25 the aim-down-at-players capture) read whatever `studio.py`'s
probe/capture ingests wrote into `<out>/eval.json`, never a value this module
computes. Every row scores a stage this pack owns, which is why the matrix lives
here rather than in a per-title skill; what IS per-title is the calibration of a
few thresholds, and each of those carries the measurement it came from --
for example, E17/E18's knee-twist threshold of 0.25 is what separates a
library-authored walk (0.042 knee twist) from an archive retarget of the
same motion (0.25-0.31). A per-title skill runs this group against its own
manifest instead of shipping a copy.

**Platform-tier clip registration.** A published clip is platform-custodied
media — the bytes live only as the Roblox asset id `publish_clip` returns —
and the boundary rejects a direct multipart upload of the `.rbxmx` file
outright (witnessed 2026-09-04). So `clips.bind()` writes
`register_media` (`storage_class="platform"`,
`kind="animation-clip"`, `link_type=cast_member_model`) and
`finalize_media_registration` (`locator="rbxassetid://<id>"`,
`locator_type="platform_asset"`) payloads for the orchestrator to run for
real, and `clips registered --clip <name> --media-id <id>` records the
finalized Genvid id once it does. Two boundary facts the payloads do not yet
encode (witnessed 2026-09-08, binding a clip by hand needs both edits):
`register_media` refuses a `.rbxmx` filename
("Cannot determine media type"), so the name carrier is `<title>.fbx` with
`mime_type="model/fbx"` and the real container is noted in the generation
params; and `target="roblox"` / `stage="roblox/keyframesequence"` is not a
known destination and stage, so a clip finalizes without target/stage.
Supersession is carried in the generation params (`supersedes_media_id`) and
in `input_media_ids`, never by deleting the earlier row. `record.run()` refuses an unregistered clip
unless run with `--allow-unregistered`, and eval row E27 reads PEND, never
PASS, while any clip is still only "payload written."

**Budget gate and cost attestation.** Every spending stage — plate, mesh, rig,
clips, and the biome plate/sky/kit stages — calls the same `budget_gate()`:
it writes a `check_generation_budget` MCP payload and raises rather than
spending until the orchestrator has recorded a `fits: true` verdict back onto
the manifest. Every Genvid bind separately requires a non-empty
`attested_cost_usd` decimal string; a stage with nothing to attest raises
rather than binding silently.

`vendors/pricing.py` splits the two numbers that used to be one. `estimate_of()`
feeds the pre-spend gate: it runs before the vendor call, has no response to
read, and may therefore assume a quantity — it is never attested. `cost_of()`
derives what the vendor actually charged for a call that already happened, and
**raises `CostNotObserved` rather than estimating**, in the same register as a
stage with nothing to attest. An attested cost is a claim the customer makes
and it is signed into a C2PA manifest; a guess must not be signed as an
observation, and a warning note next to a guess is not a fix. Three consequences
worth stating plainly, each of them paid for once:

- **Unit prices come from the vendor's BILLING EXPORT, not its pricing API.**
  A reconciliation on 2026-09-08 found `meshy/v7/multi-image-to-3d` pinned per
  compute second, where the export bills it per generation at $0.80 — 143x
  under, and no better quantity corrects a wrong axis. A pricing API is a
  second-best source for the RATE and no source at all for the per-call
  QUANTITY: it reports `tripo3d/h3.1/*` at "$0.01 per credit" and never that a
  call consumes 30 of them. Each `PRICES` entry names the axis the export bills
  on. Entries with no billing row are labelled `(assumption)`.
- **No cost literal lives outside `pricing.py`** — not in a stage, and above all
  not in an ad-hoc driver written for one production. A driver that wrote
  `"cost_usd": "0.2000"` inline attested 62 media, 62% of that project's whole
  attested total, at a number that never touched a unit price; the vendor
  response with the real figure in it was in hand and discarded. Call
  `pricing.cost_of(endpoint, response)` and let it raise. A bind with no vendor
  call behind it (a local Blender render, a re-bind of bytes another stage
  already paid for) attests `pricing.NO_VENDOR_CALL`, by name.
- **Project spend attested this way is a FLOOR, not a total.** Attestation is
  anchored to bound media, and only media the boundary sees can carry a
  cost: rerolled generations, rejected candidates, and intermediate calls
  that produce no bound row (background removal, a discarded mesh) are real
  money that no attested figure includes. One month's reconciliation of a
  single production put $19.54 of attested fal spend against $32.90 billed;
  $4.50 of that gap was 15 mesh generations — rerolls — that were paid for
  and never ingested, and so could not have been attested by any correct
  code. Eval row E29 checks a run's summed attested cost against its budget
  ceiling; whatever that sum comes to is a floor, on the same basis the
  platform rules orphan charges on deleted media: **for a true total,
  reconcile against the vendor's billing export.** Do not present an
  attested total as a complete one.

    python3 runner/cli.py init --name Large --height 50 --vendor meshy --out out/Large \
        --project <project-id> --production-title '<production title>'
    python3 runner/cli.py plate sheet --manifest out/Large/manifest.json --plate plate.png --plate-url <hosted>
    python3 runner/cli.py plate bind --manifest out/Large/manifest.json --create-asset
    python3 runner/cli.py mesh gen|prep|bind --manifest ...
    python3 runner/cli.py rig gen|r15|bind --manifest ...
    python3 runner/cli.py studio emit dump_rest --manifest ...   # then execute_luau, then studio ingest
    python3 runner/cli.py studio emit groundfit|settle|sethip --manifest ...
    python3 runner/cli.py clips transfer|build --manifest ... --clip Walk
    python3 runner/cli.py clips build-kfs|publish-clip --manifest ... --clip Walk   # each emits a Studio step: execute_luau it
    python3 runner/cli.py clips bind --manifest ... --ids Walk=<RobloxAssetId>       # the id publish-clip returned
    python3 runner/cli.py studio emit wire|park|capture_ids --manifest ...
    python3 runner/cli.py record run --manifest ...
