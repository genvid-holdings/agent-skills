---
name: genvid-roblox-character-generation
description: Generation recipes for a rigged, textured, in-game-ready Roblox character via the MCP-first path — plate craft that conditions Cube's GenerateModelAsync, mesh output checks, the Mixamo-to-R15 rig recipe and skinned-rig wiring, world-space animation transfer and asset-naming provenance rules, and the governance calls (register_media/finalize_media_registration, record_approved_corrections) that make the output governed. Does not cover Studio/MCP transport or session mechanics — see genvid-roblox-studio-ops.
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
asymmetry, importer limits, and the Auto-Setup route) — read it
first if you have not driven a Studio MCP session before. This skill does
not repeat any of that; it teaches the craft on top of it.

**Placeholders.** Examples below use neutral stand-ins for a character — a
size word (`Small`, `Large`), a height in studs — and `<Name>` for
a slot a production's own naming fills. `animSpeedScale` and `HipHeightStuds`
on a character template are the runner's own manifest keys, not a production's
naming; a title's own spawn function is, and the technique it illustrates is
what this skill teaches.

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
`in_progress` if it is `approved` or `in_review` (the boundary answers 409 to a
bind on an approved task). The
runner's own `genvid_bind.ensure_claim` is this check for every site that
binds to an asset it did not just create (`plate bind --only front/all` on an
existing asset, `plate bind --only views`, `mesh.bind`, `rig.bind`,
`rig.surface_prep`, `clips.bind`, and any per-title group that binds to an
existing asset); do the same
read-then-claim-or-reopen before any bind you run by hand against an asset you
did not just create. Writing the reopen payload is not enough on its own: the
reopen has to have *run* before the bind, or the bind still lands on the
`approved` task and 409s — a fire-and-forget reopen followed by the bind on
the next line is the same race. The runner reads the task itself with
`genvid list-tasks` (the project's organization id from `genvid get-project`)
and stores the command, the raw response and the time next to the status in
the manifest's `claims`. After a reopen it refuses the bind until a fresh read
answers `in_progress`: run the reopen payload, then re-run the stage. Nobody
records a status by hand.

**Bind every variant you would show a human, including the ones you expect to
lose.** A/B forks are the point of plate craft (see the variant-editing rule in
§1), and the rejected candidates are what make an approval legible later.

**Bind the artifact the next stage consumed.** When the provider's bytes are
the artifact and Genvid has vetted that provider's result CDN, pass the
provider's result URL as `source_url` and Genvid pulls the bytes itself; a
runner that downloads the result and discards the URL forces the local-file
path for no reason. For any other provider, bind the downloaded file with the
CLI multipart path below. When the bytes were changed locally
(decimation, facing normalization, a format conversion), the artifact is the
processed file, not the provider's result. Bind that file with
`genvid import-generated-media <project-id> -c multipart 'rendered_output: @<path>, ...'`.
A `source_url` for the processed file works only when that file is hosted on
the attested provider's vetted result CDN; Genvid refuses any other host.
Never bind the provider's original result URL in its place: every downstream
row then records a parent whose bytes that stage never read.
**Never `image_base64`**, which silently truncates a full-resolution file and
leaves Genvid signing a corrupt file that looks successful.

**A bind that timed out may already have landed.** Send an
`--idempotency-key` on every CLI bind, and retry a timed-out bind with that
same key, never a new one: the server can finish the bind after the client
gives up, and a retry without the key creates a duplicate row. The MCP
`ingest_generated_media` tool cannot read a local file, takes no idempotency
key, and accepts a `source_url` only on the attested provider's vetted result
CDN. Before any MCP fallback, check the asset's media for the row; when
the processed file is not hosted on that CDN, the CLI multipart bind is the
only path. Do not fall back to the provider's original result URL.

**Track generated assets in Genvid, never only locally.** Review happens in
the Genvid interface, not on files handed over in a terminal, so the approval
gate sits inside the governance boundary, not beside it.

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
for an unclaimed bind.

Pair every discard with a `record_decision` call so the supersession has a
durable record independent of chat history — never discard silently. The
boundary hard-requires `project_id` and `decision` on every `record_decision`
call (missing either raises `MISSING_PARAM`), and a supersession is itself a
rejection of that specific candidate, so `decision="reject"` is the correct
verdict — recording that this media lost out, not that the agent approved
anything. A `reject` verdict additionally requires at least one
`critique_tags` entry naming an *active* `critique_taxonomy_class.code`; an
invented or free-text tag (e.g. `"composition"`) is refused with an unknown
taxonomy code error. There is no MCP-facing list call for the
taxonomy; pick the `critique_taxonomy_class.code` whose seeded v1
description actually matches the owner's stated reason —
`prompt_adherence`, `subject_set_violation`, `character_canon_consistency`,
`rendering_style_drift`, `composition_framing_scale`, `motion_physics`,
`temporal_continuity`, `hallucinated_objects_anatomy`,
`burned_in_text_artifacts`, `audio_voice_fit`, `lipsync_face`,
`pacing_duration` (the boundary's seed vocabulary; it is versioned and
additions are possible, so treat this as the current list, not a closed
guarantee). If none of these actually describes
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

---

## 1. Plate craft (plates condition `GenerateModelAsync`)

Studio's `GenerationService:GenerateModelAsync` is image-conditioned (see
`genvid-roblox-studio-ops` for the surface comparison), so the plate you feed
it drives the result.

- **Always inspect and re-roll the plate before spending on 3D.** A-pose with
  clear limb gaps.
- **Variant-editing from an approved plate** is the cheap way to
  fork A/B options — edit the already-approved plate rather than generating a
  fresh one from scratch, so approval risk on the base concept is spent once.

**Example cleanup prompt.** It is written for a human character; the
pose/gap discipline it encodes is what to carry to any character.

**Goal:** strip detachable gear and clutter while keeping identity, and
normalize the pose. **Model type:** an image-edit (image-to-image) model of
your choosing. Start from a full-body, front-facing image on a plain
background.

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

Ask for about 2K resolution at a 3:4 portrait aspect, in whatever parameters
your model takes. The intent (a clean, symmetric A-pose with clear limb gaps
and no clutter) is what to carry forward for any character concept, not this
prompt's specific wardrobe.

---

## 2. Mesh output checks

- **The texture must ride the FBX.** Nothing at runtime re-textures a skinned
  `MeshPart`: the Roblox importer packages the texture into the mesh asset
  itself, and `SurfaceAppearance`/`TextureID` overrides never take.
- **Strip an Emission link that reuses the base-color atlas.** A rigged file
  that wires the same atlas into Base Color and Emission renders the body
  self-lit; remove the Emission link and strength explicitly.

---

## 3. The rig recipe

Converting a Mixamo-convention skeleton, as an auto-rigger emits it, into an
R15-compatible skinned FBX for Studio's 3D Importer. The conversion is
character-agnostic:

- **Mixamo→R15 rename table + leaf-up bone fold**: the 15 keeper bones get
  renamed to their R15 names directly; the 9 extra bones get their skin weights folded into an R15 neighbor, merged **leaf-up**
  (children reparent to the removed bone's parent first) so chains reparent
  cleanly.
- **Armature-origin-at-root-bone + mesh-vertex-shift**: the root bone must
  sit at the torso, not at the world origin — the importer maps it to `HumanoidRootPart` and hangs every
  child bone's rest offset off it, so an origin-rooted skeleton floats the
  whole visual mesh a full body-height above the ground. Relocate the
  armature origin to the root bone, then shift the raw mesh vertex data by
  the same offset (Roblox's far-LOD draws the raw mesh anchored at the root
  bone node, so unshifted vertex data floats the far-distance visual by the
  hip height even though the skinned close-range render is unaffected).
- **`HumanoidRootNode` naming** — naming it `Root` instead fails the R15
  guideline check; `HumanoidRootNode` is the name the Roblox avatar template
  expects.
- **World-space rotation-delta transfer**: do not
  play a clip's local rotations as `Bone.Transform` — Roblox re-orients bone
  local frames per bone at FBX import, so source-local rotations land on the
  wrong axes (knee flexion becomes knee twist, the "marionette" walk).
  Transfer **world-space rotation deltas** instead, with the global axis
  conversion chosen **EMPIRICALLY**: the candidate
  whose predicted foot trajectory best matches the authored clip (lateral vs.
  forward swing, height range) wins. There is no closed-form derivation for
  this — it is a search over candidates, not an analytic pick. **The pick is
  only trustworthy on a walk.** The score compares foot trajectories against a
  walk-shaped truth, and on a non-walk clip (a fall, a stomp) it can choose a
  wrong frame, such as a map with up pointing forward, while the walk and idle
  on the same skeleton agree. The map is a property of the source skeleton,
  not of the clip:
  transfer the walk first, read its pick from the poses doc (`g`), and pass
  `--g=<that name>` for every other clip on that skeleton (`poses.py` records
  `g` and `g_forced` on every doc so a review can tell which it was). The
  runner does this for you: `clips transfer --g-from Walk` reads the Walk
  doc's `g` and forces it (`--g <name>` forces one by name), and the clip item
  records `g`, `g_forced` and `g_from`.

**The transfer law:** transfer every clip by world-space rotation delta.
Do not play the standard R15 walk track on a Mixamo-convention skeleton: it
retargets badly (hip keys land at 90+ degrees, legs fold to head height).

---

## 4. The skinned-rig wiring recipe, full form

Wiring a rigged, R15-skinned import into a working in-game rig (importer
physics are not usable as-is), applicable to any character on this pipeline:

1. **Strip the importer's avatar-scaling metadata, then REBUILD it.** The
   importer's own scaling metadata silently reverts hand-done
   `HumanoidRootPart` surgery if left in place, so it has to be stripped and then explicitly rebuilt: the 6
   `Humanoid` NumberValues, per-`Bone` `OriginalPosition`, and
   `AvatarPartScaleType = "Classic"`.
2. Rebuild `HumanoidRootPart` as a torso box at the `LowerTorso` bone.
3. `WeldConstraint` every other part to it — each `MeshPart` of a
   multi-mesh import and the importer's bone-holder part (the root bone's
   parent) — with `CanCollide = false`, `Massless = true`. The
   `HumanoidRootPart` is the rig's one physics body: any other part left
   colliding rests on the ground and holds the body up.
4. Upright `AlignOrientation` (`OneAttachment`, `PrimaryAxisOnly`, axis `Y`,
   rigid). `AlignOrientation`'s `PrimaryAxis` **defaults to `X`** — leaving the
   default silently floats the rig horizontal instead of upright; it must be
   set to `Y` explicitly.
5. `RequiresNeck = false`, fall states off.
6. `AutomaticScalingEnabled = false`, **then** pin `HipHeight` — Play-start
   recomputes `HipHeight` to garbage if scaling is still enabled when it's
   set. The `HipHeight` formula is
   `hip = (rootY − feetPlane) − rootSize.Y / 2`, with `feetPlane` the lowest
   vertex over every `MeshPart` (a multi-mesh import can list a small
   accessory mesh first). No fixed hip figure is
   canonical for any character: it changes with every import's geometry.
   Use the formula, not a number from another import.
7. Release the rig via `ChangeState(GettingUp)`.
8. **Spawn placement reads the `HipHeightStuds` attribute**, not the part
   bounding box — part bboxes lie on these rigs, so your character-spawn code must read the
   attribute, not `GetBoundingBox`.

**Two-point scale calibration lives in `genvid-roblox-studio-ops`**, not
here; use it as written there.

- **Roblox render law:** skinned meshes render two
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

### 5.0 First decide WHICH path, and decide it on where the bytes are

Two paths bind generated media, and the one you need is chosen by **who ends up
holding the bytes** — never by the media being 3D.

| Where the result lives | Path | What gets recorded |
|---|---|---|
| In Roblox's cloud — an `rbxassetid://`, which nobody can fetch bytes from | `register_media` → `finalize_media_registration` (§5.1) | durable platform identifiers + a `generation` block |
| **On your disk, or on your provider's result CDN** | **`ingest_generated_media`** — see `genvid-agent-generation` | `model_provider` / `model_name` / `render_type` / `prompt` / `params`, signed as an AI-generation attestation |

§5.1 exists because a `generate_mesh` / `GenerateModelAsync` result never
leaves Roblox. That reasoning **does not carry to any other 3D generator.** If
you generated a mesh with a tool that wrote a `.glb` or `.fbx` to disk — a
hosted 3D generator you downloaded the result from, a local pipeline, anything
you drove through a browser — Genvid can hold those bytes, so bind them and let
the attestation carry the generator:

```sh
genvid import-generated-media <project-id> -c multipart \
  'rendered_output: @/path/to/character.glb, model_provider: <your generator>,
   model_name: <the model you used>, render_type: T23D,
   link_type: cast_member_model, asset_id: <asset-id>, params: {}'
```

`target` and `stage` are omitted deliberately. They are optional as a pair, and
together they claim a destination pipeline stage: the published vocabulary
carries `roblox/r15-rigged` for a skinned R15 rig, and a mesh that has not been
rigged yet satisfies neither that nor any other published stage. Add them only
when the artifact really is at a stage the vocabulary names. A pair the
vocabulary does not know is refused outright, and the vocabulary is not
published anywhere a caller can read it.

`render_type` is `T23D` for text-to-3D or `I23D` for image-to-3D — **never
`upload`**, which is what registration stamps and what makes a generated asset
read as a hand-uploaded file with no author. `link_type` is the `*_model` slot
matching the asset's type (`cast_member_model`, `prop_model`, `location_model`,
…). The provider name is free text, attested as you used it: a generator needs
no prior registration with Genvid, and needs no
`identifier_scope_vocabulary` row.

**Registering a locally-generated mesh is the failure this table exists to
prevent.** It stamps `render_type = 'upload'` and records no generator, then
rejects the generator's own task ID at the identifier vocabulary — which is
closed and Roblox-only by design. The result is a governed asset attributed
to nobody.

### 5.1 Capture at call time: `register_media` → `finalize_media_registration`

**Use this branch only for a mesh that stays in Roblox's cloud** — see §5.0
before you do. There is no after-the-fact discovery path for a generated Roblox
asset (see `genvid-roblox-studio-ops` for why) — capture has to happen at the
moment of the call. The finalize step's shape, exactly as shipped
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
pack's reference material, but not yet deployed to production.

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
   routing this pack uses elsewhere for reads MCP does not surface;
   `assets_read` does not serve this staleness read.

### 5.4 Provenance rules for animation asset naming

- **Never put a source brand name in a Roblox asset's title.** A brand name
  in the asset title gets a submission rejected; the motion itself is
  licensed for games. Scrub names to a convention like `SmallWalk_v1`, not `MixamoWalk_v1`.
- **Approved sources:** CMU Motion Capture Database (free for any use,
  including commercial), Quaternius (CC0).
  **Forbidden sources:** Ubisoft LaFAN1 and Bandai Namco motion datasets
  (non-commercial licenses); Roblox catalog animations are also out —
  **except** onto a true R15 rig, where catalog anims do retarget cleanly
  (they fail to retarget cleanly onto the Mixamo-convention skeletons
  this pipeline otherwise uses).
- **The Mixamo download rule**: **select the stock
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
| Tier reconciliation — why platform-tier captures (this skill) don't go through `genvid-media-registration`'s archival flow | `genvid-media-registration` (scoped note there); platform tier has no ingest path — no party holds bytes to hash, so there is nothing to register through that skill's flow |
| Conformance checking a captured artifact | `check_conformance` — correctly refuses on platform-custodied media: it measures the artifact's bytes, and a platform-custodied asset has none for it to read |

---

## 7. The zero-touch runner

`runner/cli.py`, under `skills/genvid-roblox-character-generation/runner/`, is a
stdlib-only Python package invoked as `python3 runner/cli.py <group> <cmd> ...`.
Each group — `init`, `plate`, `mesh`, `rig`, `surface`, `studio`, `clips`,
`eval`, `record` — is its own module exposing `register(subparsers)`; `cli.py` imports
each lazily and skips one that fails to import rather than breaking the rest.

**Nothing bound to one title lives here.** A title's own chains, its Studio
steps, its attribute names, its world design and its eval thresholds belong in a
per-title skill
that DEPENDS on this pack; the dependency is one-way and this pack never imports
one. Two manifest fields carry the production's own identity into the work this
pack does, and **neither has a default**: `project_id`
(`runner init --project`) and
`production_title` (`--production-title`), the string every asset
description this chain creates is built from — `plate bind --create-asset`
and any asset-creating site a per-title group adds read it
through `manifest.production_title()`, which raises rather than guessing.
A title's own world design (its palettes, HUD tokens, prop kit and design Luau
modules) is a per-title skill's own document, never general technique, so
none of it is a constant here. What stays here as generic technique, because a
per-title chain can reach for it without vendoring it: `runner/luau/sky.luau`
(six cubemap faces plus a lighting style), `runner/blender/equirect_to_cube.py`
(the Roblox slot remap for a cubemap's six faces) and
`runner/blender/split_sheet.py` (an equal-tile grid crop of a sheet image into
per-tile PNGs).

A per-title skill stamps both. `studio.register_steps(template_dir, stage_of=, render_defaults=,
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
pushes a caller onto a paid generation it did not need. A per-title skill exports
both from its own config.

**Stage order.** A skinned-rig character's manifest records its stages as
`plate -> mesh -> rig -> rest -> groundfit -> clips -> wire -> record`, the
order `record run` checks them in. The Studio work runs in a different order,
set by which template each step reads. `scale`, `dump_rest`, `groundfit`,
`wire` and `capture_ids` find the imported template in `workspace`; `park`
moves it into the park folder; every later step (`settle`, `sethip`,
`probe_feet`, `probe_walk`, `treadmill`, `bench_clip`, and the clip route's
`build_kfs` and `publish_clip`) reads it from the park folder. The workspace
steps take the template through the `MODEL_PATH` render parameter (default
`workspace:FindFirstChild("<template>", true)`), so `capture_ids` can also run
after `park` with `--param MODEL_PATH=<park folder expression>["<template>"]`.
So `wire` and `park` (and `capture_ids`, by default) run right after the
`groundfit` measurement, before
the settle loop and before any clip is built: `clips build` also takes the
root scale from `stages.wire.result.scale`, and `studio ingest build_kfs`
refuses a template that is not under the park folder. The end-to-end list at
the end of this section gives the full order. A static model with no Humanoid and no rig
skips straight to `plate -> mesh -> wire -> record`: there is no rig, ground-fit,
or clip stage for something that never gets a skeleton. A manifest whose chain
is not the character chain can carry its own shorter stage order (`stage_order`)
on the manifest itself.
A variant that is the same rig at a different scale under a second template name
re-runs only the scale-dependent tail (`scale`, `dump_rest`, `groundfit`, `wire`,
`park`) against a second manifest, copying the winner's plate/mesh/rig stages
across so the original manifest is never touched; that chain and the static
model's two title-specific steps live in a per-title skill, not here.

**Generation: emit, run a model, ingest.** The runner never calls a model and
never names one. Every generating step is a pair with the model run between
them, by the agent, with whatever model and provider it chooses:

    runner <group> emit <step> --manifest M [--item K] --estimate <USD> [--model <text>] [--no-urls]
    # the agent runs a model of the requested TYPE on the request's inputs
    runner <group> ingest <step> --manifest M [--item K] --provider <text> --model <text> \
        [--params <JSON object>] (--cost <amount> [--currency <ISO 4217>] | --cost-unobserved) \
        [--prompt <text>] [--render-type ...] [--input-media-id <id> ...] \
        [--record-only] [--supersede] [--unrequested <reason>] <file-or-url>

`emit` gates the estimate against the Genvid budget (below) and writes
`<out>/requests/<stage>-<step>[-<item>].json`, a request that names the model
TYPE, the render type, the prompt and the input media (with signed download
URLs unless `--no-urls`). `--model` on emit is optional and never checked; it is
recorded with the budget verdict so that naming a different model gates again.
`ingest` takes the result as a local file or an http(s) URL, records the
provider, model, params and cost the agent reports, and binds it. The pairs:

| Stage | Emit | Ingest | Model type |
|---|---|---|---|
| plate | `plate emit front --prompt ... [--input-media-id <ref>]`, `plate emit views [--item back\|left\|right]` | `plate ingest front --item c1 [--asset-id ... \| --create-asset] <result>`, `plate ingest views --item <view> <result>` | text-to-image, or image-to-image with a reference |
| mesh | `mesh emit model` | `mesh ingest model <result>` (GLB preferred; binary FBX or OBJ converted), which also preps and binds | image-to-3D |
| rig | `rig emit model [--clip LABEL:DESCRIPTION ...]` | `rig ingest model --rig <result> [--clip LABEL=FILE ...] [--derived-from mesh\|plate]`, which also converts to R15 and binds | rigging |
| clips | `clips emit motion --clip <key> ...` | `clips ingest motion --clip <key> --mode mixamo\|r15\|rename\|ual <result>` | text-to-motion |

`rig emit model --clip` asks the rigging model for library motions bundled with
the rig, one per label; `rig ingest model --clip LABEL=FILE` records each as
`<out>/clips/<label>.glb` and binds it as its own motion row citing the rig.
`clips ingest motion --mode` names the skeleton convention the clip is authored
on: `rename` (the rig's own bone names), `mixamo`, `ual` (Rigify `DEF-` names)
or `r15`. `plate select-front --media-id <id>` records which bound candidate is
the front plate. `mesh prep` / `mesh bind`, `rig r15` / `rig bind` and `plate
bind` re-run the processing or the bind on what was already recorded (after a
`ClaimPending`, or an ingest run with `--record-only`); `--supersede` binds
different bytes for an item already bound, as a new row that supersedes it.
One ingest has no emit: `rig ingest surface-texture` records and binds a
texture generated for the surface pass, and always takes `--unrequested
<reason>`. `surface prep` then re-bakes the existing character's rig with that
texture and binds it, and the `applymesh` Studio step swaps the re-baked mesh
onto the already-parked template.

**Studio steps.** Studio-side work is Luau templates under `runner/luau/` the
driving agent renders with `runner studio emit <step>`, executes over the
Studio MCP, and feeds back with `runner studio ingest <step>`. Ground-fit is
five steps, not the three the interface contract's single formula suggests,
because a standing Humanoid hovers above its own `HipHeight` by a per-rig
constant, and the loop's exit test has to be a measurement, not an assumption.
The first step reads the imported template in `workspace` and the rest read it
from the park folder, so `wire` and `park` run between them (Stage order,
above):

    studio emit groundfit ...; ingest groundfit ...    # EDIT: measures SoleOffsetStuds
    studio emit wire ...     ; ingest wire ...         # EDIT: wires the rig (§4)
    studio emit park ...     ; ingest park ...         # EDIT: moves the template into the park folder
    studio emit settle ...   ; ingest settle ...       # PLAY: measures the hover constant
    studio emit sethip ...   ; ingest sethip ...       # EDIT: writes the corrected HipHeight
    studio emit settle ...   ; ingest settle ...       # PLAY: verifies the fix (or fails; see below)
    studio emit probe_feet ...; ingest probe_feet --lod close ...                      # EDIT: close LOD
    studio emit probe_feet --param LOD=far ...; ingest probe_feet --lod far ...        # EDIT: far LOD

Two hip numbers come out of this loop for two different consumers.
`SoleOffsetStuds` is the raw geometric distance from the HumanoidRootPart's
bottom to the rest pose's lowest vertex — `(rootY - feetPlane) - rootSize.Y/2`
— and is what an anchored, non-Humanoid placement reads. `HipHeightStuds`
is what `Humanoid.HipHeight` needs so a *live* rig's soles actually touch the
ground: `SoleOffsetStuds` minus the hover constant. Using one where the other
is wanted floats or sinks the rig by exactly that constant.

The second settle verifies the fit only when its settled root bottom lands
within E13's gap tolerance (0.5 studs) of `SoleOffsetStuds`: that difference
is the gap E13 scores, read at the root. A miss is recorded under
`stages.groundfit.verification_miss`, the ingest fails naming both numbers,
and E13 scores the miss (FAIL, with both numbers under the row) until a
verified settle clears it. The usual cause is a part other than the
`HumanoidRootPart` still colliding.

**The clip route.** One clip, from source motion to a governed, published
Roblox animation, with no Save-to-Roblox click on the path. It runs once the
template is wired and parked (Stage order, above):

    runner clips declare --manifest M --clip <key> --loop true|false --priority Idle|Movement|Action [--description <motion>]   # a title's own key only
    runner clips emit motion --manifest M --clip <key> --estimate <USD>       # a generated clip only; run a text-to-motion model
    runner clips ingest motion --manifest M --clip <key> --mode <convention> --provider ... --model ... --cost ... <result>
    runner clips transfer --manifest M --clip <key> [--candidate N | --source generated] \
        [--g <name> | --g-from <key>] [--no-root] [--root-ref first|bind] \
        [--root-y hips|ground [--rig-mesh <glb>]] [--root-xz keep|none] [--trim START:END] [--translate BONE[,BONE...]] \
        [--bind-from <rig fbx|glb> | --bind-from clip]
    runner clips build --manifest M --clip <key> [--anims-dir <dir>] [--time-scale <factor>]   # then let Rojo sync
    runner clips build-kfs --manifest M --clip <key>                          # Edit; read-only verify
    runner studio ingest build_kfs --manifest M --clip <key> <result>
    runner clips publish-clip --manifest M --clip <key> [--group <Roblox group id>]   # Edit
    runner studio ingest publish_clip --manifest M --clip <key> <result>
    runner clips bench --manifest M --clip <key> [--speed <x>] [--max-wait <s>]   # Play, Server
    runner studio ingest bench_clip --manifest M --clip <key> <result>
    runner clips bind --manifest M --ids <key>=<Roblox asset id> ...          # writes the two payloads
    runner clips registered --manifest M --clip <key> --media-id <Genvid media id>

- **`clips transfer`** retargets the source motion onto the rig's own rest
  dump as world-space rotation deltas (§3 and the transfer laws below). A
  catalog clip picks its source with `--candidate`; a generated one reads what
  `clips ingest motion` recorded with `--source generated`. `--g <name>`
  forces one of the axis-map candidates and `--g-from <key>` forces the map
  another clip's transfer recorded (the two are exclusive; transfer the walk
  first). `--no-root` emits rotations only; `--root-ref first|bind` measures
  root motion from the clip's first frame (the default) or the bind pose;
  `--root-y ground` is the opt-in ground lock, which skins
  `stages.rig.artifact_glb` unless `--rig-mesh` names another glb;
  `--root-xz none` drops the root's horizontal travel and keeps its lift
  (below the transfer laws); `--trim
  START:END` keeps one range of the source clip, in seconds of authored time;
  `--translate BONE[,BONE...]` carries those non-root bones' translation
  (below the transfer laws); `--bind-from <file>` measures the transfer from
  the bind of the skeleton the clip was authored on (law 8).
  Re-transferring a clip that was built, benched, published or bound keeps
  the item it replaces on `stages.clips.superseded.<key>` and notes its
  title, Roblox id and Genvid media id on the manifest.
- **`clips build`** writes the KeyframeSequence `<Name><Key>_v<N>.rbxmx` into
  the directory the title's Rojo project maps into
  `ServerStorage.Assets.Anims`, where the Studio steps read it: `--anims-dir`,
  else `$GAME_ANIMS_DIR`. It records what the synced sequence must contain
  (`kfs_expected`: keyframe count, last keyframe time, time scale, loop,
  priority, root-node shape, root scale) and the title (`kfs_name`).
  `--time-scale <factor>` multiplies the authored keyframe times; with no
  factor the build applies the height cadence stretch (law 6), and `1` keeps a
  clip authored on this rig at its own cadence. A re-run drops the earlier
  verification, so a rewritten file is verified again before it is published.
- **`clips build-kfs`** emits `build_kfs`, a read-only Studio step that reads
  the synced sequence and the template back. `execute_luau` runs sandboxed
  with no Network, so nothing is fetched or built in Studio. `studio ingest
  build_kfs --clip <key>` compares the read-back with `kfs_expected`, refuses a
  sequence that is missing or differs (naming the `clips build` and Rojo sync
  to re-run), and records `kfs_verified`.
- **`clips publish-clip`** emits the Studio step that publishes the title
  `clips build` recorded, and refuses until `kfs_verified` names that same
  title. `studio emit publish_clip` is gated the same way and refuses a CLIP
  that is not on `stages.clips.items`, with no bypass. `--version` / `--name`
  on `clips build` set the recorded title (`--name` when the Studio template's
  own name may not appear in a published title). Without `--version`, `clips
  build` takes the next unused version: one past the highest this clip has
  been built at, read from the `kfs_name` of its current item, of each prior
  item on `stages.clips.superseded.<key>` (a list of item records; only their
  `kfs_name` counts) and of its titles on `stages.clips.clip_names`, so it
  never rewrites a title it built. A clip published with no recorded title
  needs an explicit `--version`. Each such build writes a new `.rbxmx`
  beside the earlier ones in the anims directory. On build-kfs and
  publish-clip both are optional: without `--version` they take the recorded
  version, and a `--name` that gives another title is refused, naming the
  recorded one. An explicit `--version` always wins. `--group <id>` uploads
  the clip under that Roblox group instead of the Studio user: set it when
  the experience the clip plays in is group-owned, or when several people
  publish clips for the same experience, since a user-owned animation is
  refused there without a manual permission grant. Pass it once and it is
  recorded on the manifest, so every later `publish-clip` reuses it without
  repeating it; the published item records which creator it was uploaded
  under.
- **`clips bench`** plays the published id on a clone in Play (below).
- **`clips bind`** writes the platform-tier `register_media` and
  `finalize_media_registration` payloads for each `<key>=<id>` pair, titled
  from the clip's `kfs_name`; the orchestrator runs them, and **`clips
  registered`** records the finalized Genvid media id. The payload shape and
  its source citation are below.
- `clips impact` measures an attack clip's impact time and `clips speed-scale`
  derives the walk's speed scale from the in-engine treadmill measurement;
  both are numbers a title's game reads.

**A title's own clip keys (`clips declare`).** The catalog's clips (Walk,
Idle, Stun, Attack, Death, Slam) are the pack's. A title whose characters play
clips of their own — one per attack kind, say — declares each key on the
manifest before the first step that creates it:

    runner clips declare --manifest ... --clip wave --loop false --priority Action \
        --description "both arms rise overhead and wave slowly"

`--loop` and `--priority` (Idle, Movement or Action) are what the clip's
KeyframeSequence is built with; `--description` is the motion `clips emit
motion` asks a text-to-motion model for, and that step refuses a key declared
without one. `--motion` (in_place, the default; travel; or fall) picks the
bench gates the clip answers to (see "Bench gates" below). The key is letters and digits starting with a letter; a catalog
clip's name, or a key that differs from another declared key or a clip
item's key only in case, is refused.
The declaration lands at `stages.clips.declared.<key>`; re-declaring a key
replaces it.

The steps that CREATE a clip (`clips transfer`, `clips emit motion`, `clips
ingest motion`) take a catalog clip or a declared key. A declared key has no
catalog candidates: its motion comes through `clips ingest motion`, then
`clips transfer --source generated`, and `--source catalog` on it is refused.
Every step after that (`build`, `build-kfs`, `publish-clip`, `bench`,
`impact`, `bind`, `registered`, and `studio ingest ... --clip`) takes any key
on `stages.clips.items`, since the item carries its own loop and priority; an
item a title's own transfer wrote is accepted there without a declaration.
Any other key is refused by name, listing the keys that are valid. The
published title is `<Name><Key>_v<N>` with the key's first letter upper-cased
(`wave` publishes as `<Name>Wave_v1`); a catalog clip's title is unchanged. `clips impact`
records the impact on the measured clip's own item (`impact_raw_secs`, authored,
and `impact_delay_secs`, as the built clip plays it), so a title with several
attack clips times each one; `stages.clips.attackImpactClip`,
`attackImpactRawSecs` and `attackImpactDelaySecs` mirror the clip measured last,
for readers that take one impact per title.

`build_kfs` builds nothing in Studio and uses no Network: `execute_luau` runs
sandboxed without the Network capability, so a step cannot fetch over
`HttpService`. The rest of the clip chain runs under that sandbox:
`HttpService:JSONEncode` (every step's result line),
`AssetService:CreateAssetAsync` on a KeyframeSequence (`publish_clip`), and,
in Play/Server, `Animator:LoadAnimation` of a published id the same account
owns (`bench_clip`). `publish_clip` calls `AssetService:CreateAssetAsync` on
the sequence directly, which returns a real Roblox asset id from the MCP
bridge's Edit context; `CreateAssetAsync` publishes a KeyframeSequence but
rejects a MeshPart or a Model. `wire` (same stage as `park` and `capture_ids`) also
has to force `Humanoid.RigType` to R15 and destroy any `AnimationController`
the 3D Importer parked beside the Humanoid the runner creates: either one
silently stalls every animation track's `TimePosition` at zero — an R6
Humanoid never advances an R15 KeyframeSequence, and a live
`AnimationController` competes with the Humanoid's own Animator so neither one
advances.

**Clip transfer laws.** These have to be true at once for a library clip
that moves the hips (a stomp, a kneel, a knockback, a fall) to read correctly
in the game:

1. *Root motion is emitted.* `poses.py` writes the root bone's translation per
   frame under `frames[i].r` (the hips' world delta, mapped by the same `g` as
   the rotations, scaled by `k`, expressed in the root bone's rest frame);
   `kfs.write` puts it in the LowerTorso pose position. `k` (recorded in the
   poses doc) is the LEG-CHAIN ratio, hip joint to knee to ankle on both
   sides, between rest.json and the clip's bind: an overall-height ratio read
   off a library skeleton after the rename/merge spans about hips-to-skull,
   not feet-to-crown, and makes root motion too large. A bone scale the clip
   keys (a library clip can key a scale on Hips on every frame) is stripped
   before the transfer, so every emitted quaternion is unit length. `k` also
   scales the truth ranges the empirical axis-map pick scores against
   (law 2), so re-transferring a clip can change its pick: compare the `g` the
   transfer records, and pin it with `--g` or `--g-from`. A rotation-only
   transfer plays every crouch as legs folding under a pelvis pinned at
   standing height and a fall as a torso rotating around hips that stay in the
   air (`--no-root` keeps that output).
2. *The axis map is forced to the walk's* (`--g=`, above). A wrong map gives
   wrong rotations, not only missing translation. This rule is
   for the EMPIRICAL branch, which vendor-library and rig-authored donors take.
   A native Mixamo donor (the archive packs) carries a toe bone, so `poses.py`
   takes its ANALYTIC branch -- facing measured from the rest skeleton, clip
   independent -- where `--g=` is not consulted (it only stamps `g_forced`);
   walk and death then share the map by construction. Confirm it: all the
   runs on one rig print the same `analytic g (clip faces (...))` line.
3. *The pose tree mirrors the real bone chain.* The Animator matches rotations
   by pose name whatever the tree, but it applies a TRANSLATION only when the
   tree is `HumanoidRootPart > HumanoidRootNode > LowerTorso`. `clips build`
   writes the node pose unless `stages.wire.result.hasRootNode` is false (an adopted rig without the
   bone, law 5); `build_kfs`'s ingest refuses a sequence whose node pose
   disagrees with the template.
4. *The translation is divided by the model scale.* The Animator multiplies a
   pose translation by `Model:GetScale()`. `kfs.write`
   takes `root_scale`, which `clips build` feeds from
   `stages.wire.result.scale`; `build_kfs`'s ingest refuses a clip with root
   motion when the template's `GetScale()` no longer matches it.

5. *A clip is bound to the skeleton it was built for.* A clip built on the
   16-bone runner rig plays NOTHING useful on a 15-bone rig that hangs
   `LowerTorso` straight under `HumanoidRootPart` with no `HumanoidRootNode`
   for the translation to ride on. Transfer onto that rig's own rest dump
   instead: with the tree `HumanoidRootPart > LowerTorso` (no node, which
   `clips build` omits when the rig records no such bone) the translation
   DOES apply on those rigs.
6. *Cadence follows the square root of height.* `timing.scale_time` stretches
   a clip by `sqrt(height / 8)`, so a clip authored at height H plays on a
   rig of height h at speed `sqrt(H / h)`. A rig that borrows another rig's
   clip plays it at that speed (a 20-stud rig plays a 50-stud rig's clip at
   sqrt(50 / 20) = 1.58). `kfs.write` applies
   the same factor to every keyframe time (`1 / timing.cadence(height)`: 1.58
   at 20 studs, 2.09 at 35, 2.5 at 50, 3.45 at 95). A clip authored on the rig
   itself, at the cadence it should play at, is built with
   `clips build --time-scale 1`, which keeps its authored times; any other
   number multiplies them. The factor is recorded on the clip item
   (`time_scale`) and in `kfs_expected`, and every timing derived from the
   clip reads it (`timing.clip_time`): the item's `scaled_seconds` (the bound
   row's `duration_seconds`), its `impact_delay_secs` (re-derived when the clip
   is rebuilt after `clips impact`, with the `attackImpactDelaySecs` mirror when
   it names the clip), and eval rows E15, E20 and E21 (E20 reads the Attack
   clip's own impact; the mirror only where it can be the Attack clip's). A clip
   with no `time_scale` keeps the height stretch.
7. *A rig's extra bones ride along.* The rest dump carries every bone but the
   root node, so a rig with bones beyond R15 (wings, a jaw, cloth) gets them
   into the transfer. A clip must drive every R15 bone; an extra bone it keys
   is transferred, one it does not key is held at its rest and listed under
   `held` in the poses JSON. A held bone is left out of the KeyframeSequence,
   because the Animator resolves priority per joint and a present Pose claims
   its joint: an Action clip that does not key the wings leaves them to the
   Idle underneath. A held bone stays in only as a structural identity Pose,
   when it carries root motion or a descendant is driven or translated.
8. *Deltas are measured from the rig's rest, not from whatever the clip file
   calls its bind.* Every frame is transferred as the clip's world rotation
   relative to its skeleton's bind, and root motion with `--root-ref=bind`
   starts at the bind's hips. A clip exported from a DCC can carry "the pose
   at export" as its bind (its first frame, its end pose), and then every
   frame is wrong by that pose: a collapse played in reverse, a walk whose
   axis-map pick sends up to down. On the empirical axis-map branch (every
   clip but a native Mixamo or Rigify one) `clips transfer` refuses a clip
   whose bind sits more than 5 degrees off the rig's rest, naming each bone
   and its angle. Pass `--bind-from <the fbx or glb of the skeleton the clip
   was authored on, in its rest>` (the rig's own file for a clip authored on
   the rig; bones matched by name, after the `rename` convention when the
   clip takes it): the transfer then measures from that file's bind. The file
   is refused when its bind is itself off rest.json (it is not the rig the
   rest was dumped from), when its leg chain is not the clip's length within
   1% (another skeleton or scale), or when its world is turned from the
   clip's (a glb twin turned a half turn from the fbx the clip was authored
   against; pass the file the clip was authored against). That frame check
   is recorded as `bind_frame` on the poses doc and the item: `aligned`, or
   `inconclusive (N of M bones agree)` when the clip's bind is posed off the
   rest on most bones and a turned file cannot be told from the pose; the
   transfer continues on `inconclusive`, and a manifest note says so, so check
   such a clip in Studio. A file placed elsewhere in the world shifts
   `--root-ref=bind` root motion and cannot be told from a clip whose bind is
   itself displaced, so the item records the distance between the two hips
   as `bind_hips_offset_studs`. Under `--root-ref=bind` that distance is a
   constant root-motion offset on every frame (the default `first` reference
   does not read it): check it before using the `bind` reference. `--bind-from clip` transfers from the clip's
   own bind anyway, for a clip on another skeleton whose rest is in no file
   at hand. The item records `bind_from` and `bind_mismatch_deg` (bone ->
   degrees the clip's own bind is off), and a manifest note names those
   bones. The check reads bone directions only, so without `--bind-from` a
   bone with no child in the clip (a hand, a foot, a wing tip) is not
   measured and a bone rolled about its own length is not seen. A driver that
   runs `poses.py` directly passes `--bind-from=<file>` itself.

And one reference rule: root motion is measured from the clip's FIRST FRAME
(`--root-ref=first`, the default), because library clips do not all start at
the bind pose, and bind-relative motion on such a clip leaves the mesh
sitting off its collider for the whole clip and snapping back at the end;
`--root-ref=bind` is for a clip that starts mid-air or crouched and should
read that way (`clips transfer --root-ref first|bind`; `--no-root` emits the
rotation-only doc; the item records `root_ref` and `root_motion`).

The hips delta alone does not keep the feet on the ground, whatever `k` or
reference: library clips are not grounded against their own bind (a walk's
lowest foot swings under and over the bind sole, a death sinks, an idle with
a keyed hips scale hovers), and the rig loses the clip's toe joints.
`clips transfer --root-y ground` locks the VERTICAL root motion instead: every frame, the
offset that puts the rig's lowest skinned vertex back on its rest level (the
ground the rig was fitted to), so a crouch, a kneel or a lie-down rests on
the ground and nothing sinks or hovers; the horizontal still follows
`--root-ref`. It skins the rig's own mesh, `stages.rig.artifact_glb` by
default (`--rig-mesh <glb>` for an adopted rig), fitted to rest.json by a
similarity and refused when a bone origin misses by more than 1% of the mesh
height (the mesh is then not the rig rest.json came from). The item records
`root_y` (`hips`, the default, or `ground`), `k` and the fit (`ground`). The
lock keeps the lowest point down on every frame, so a clip whose feet dig
into the ground at toe-off bobs its hips by the dig instead; it is opt-in,
and it is wrong for a clip meant to leave the ground.

A clip whose root travels and never returns (a lunge, a flight that lands far
ahead) leaves the mesh away from its collider and trips the in-place bench
gates on root travel; the next clip snaps it back. `clips transfer --root-xz
none` plays it in place: every frame's horizontal root delta is zeroed and
the vertical stays as `--root-y` sets it (the ground lock included), so a
lift and a glide height are kept. Across the ground the hips stay where the
reference puts them: the bind pose's place under `--root-ref=bind`, the first
frame's under `first`. The trajectories the eval scores carry the in-place
motion; the axis-map pick reads the authored motion unstripped, so it and
every bone's rotation are the same either way. The item records `root_xz`
(`keep`, the default, or `none`). It is refused with `--no-root`. Check
`frames[0].r` and `frames[-1].r` before publishing: an
Action clip the game holds (a stun, a death) keeps its last-frame offset for
as long as it is held, and a clip that blends back to idle snaps from it. A
repeating library clip (several seconds of stomping in place, say) is
trimmed to one action before building, and its impact is the first foot
landing after the peak lift, not the global minimum the default detector
finds across hands and feet. `clips transfer --trim START:END` does the cut:
it keeps that range of the source clip (seconds, authored time) and re-bases
it to start at 0 before anything reads it, so the root reference is the first
kept frame, the axis scoring and trajectories see one action, and the
item's `clip_seconds`/`scaled_seconds` are the trimmed length. Cut to one
action and the default impact detector finds that action's landing. A range
that ends past the clip, or keeps fewer than two frames, is refused; the item
records `trim`. Re-transferring a clip drops the impact `clips impact`
measured on it, and the mirror when it names that clip (re-run `clips
impact`); every other clip keeps its own. `clips build` refuses a clip's
recorded impact time past that clip's end.

Below the root, the transfer is rotation-only by default: a bone the clip
moves by translation (a brow or lid sliding on the face) stays at its rest
offset. Rotation-only is the safe default because a non-root bone's authored
offset belongs to the source skeleton's proportions, which the rig's own rest
replaces, and a translation has to be scaled from clip units to studs and
then by the model scale, where a rotation needs neither. `clips transfer
--translate BONE[,BONE...]` carries the named bones' translation: each
bone's displacement from where its parent's animated frame puts it at rest,
mapped by the same `g` and scaled by the same `k` as the root motion, and
written in the bone's rest frame under its parent's transferred rotation, so
it follows the parent as it turns. A root bone is refused (its translation is
the root motion), as is a bone not in rest.json, a bone the clip does not
key (held at rest) and a bone whose clip bone has no parent to measure it
from. Every transfer names the rest.json bones it
left rotation-only although the clip translates them
(`translation_dropped` on the item, bone -> largest displacement in studs);
read it after the first transfer of a rig-authored clip and pass the bones
that are meant to slide. A bone that both rotates and translates is carried
the same way; check it in Studio before publishing. `kfs.write` divides these
translations by the model scale exactly as it does the root motion (law 4),
and the item records `translate`. The rest dump must carry the bone for any
of this to apply: a bone missing from rest.json gets no track, and so does a
rest.json bone whose parent chain does not reach HumanoidRootPart (the
transfer prints a warning naming it).

**Bench before you publish, sample the right property.** The bench that
proves a clip is a Play clone with the published id (a parked, unpublished
sequence never advances) sampling `Bone.TransformedWorldCFrame` for the
hips, head and a foot against the sole plane. `Bone.WorldPosition` /
`WorldCFrame` EXCLUDE the bone's own animated `Transform`, so a sampler on
them reads every root-motion hip as 0 and the clip as "nothing moves", a
false negative.

**Binding a published clip.**
`register_media` at `storage_class="platform"` with `kind="animation-clip"`,
`link_type="cast_member_model"`, a `.glb` filename and
`mime_type="model/gltf-binary"` as the media-type hint (a `.rbxmx` name is
rejected; no proxy), then `finalize_media_registration` with
`locator="rbxassetid://<id>"`, `locator_type="platform_asset"`, the
`roblox.com` `asset_id:` identifier, `size_bytes` measured from the poses
file (stated in `generation.params`), `duration_seconds` = the scaled
length, and NO `target`/`stage` (the keyframesequence stage is refused).
`clips bind` writes exactly this, registering each clip under the title
`clips build` recorded for it (so clips at different versions bind in one
call; without `--version` it takes each clip's recorded version, a
`--version`/`--name` that gives another title is refused, and a clip with no
build record needs an explicit `--version`), and cites the clip's source row in
`input_media_ids`: a generated clip's motion row, a rig-bundled clip's own row,
nothing for an archive clip. An item from any other source (a title's own
transfer, which writes the item itself) must carry `source_media_id`, the
Genvid row of the file it was transferred from, which bind cites in
`input_media_ids` and `generation.params.source_record`; without it the bind
is refused before any payload is written. Cost lives on the generation rows, never on the
clip item: an item carries only `cost_source` (`rig`, `none`, or
`clips.generated.<clip>`), and no clip row attests "0". A bundled clip's row
omits the cost fields, since the rig's row holds the spend.

**Adopting a rig that already exists (`runner rig adopt`).** A parked template
with no manifest (a rig handed over as a bare template, or one built outside
this runner) gets a manifest whose chain starts at `rest`; plate/mesh/rig
are not on it and are not pretended. The whole sequence for one new clip:

    runner rig adopt --name Small --template <StudioTemplateName> --height 20 --project-id <project-id> \
        --asset-id <cast-member uuid> --assignee <reviewer email> \
        --production-title '<production title>' --out-dir out/small-adopted
    runner rig adopt-emit --manifest out/small-adopted/manifest.json adopt_inspect   # Edit
    runner studio ingest adopt_inspect --manifest ... <result>                        # fills wire: scale, hip, root-node flag
    runner rig adopt-emit --manifest ... dump_rest                                    # Edit, against the parked template
    runner studio ingest dump_rest --manifest ... <result>
    runner clips transfer --manifest ... --clip Death --candidate 1                   # archive fall (an adopted rig has no rig ingest)
    runner clips build --manifest ... --clip Death --anims-dir <Rojo-mapped dir>        # then let Rojo sync it
    runner clips build-kfs --manifest ... --clip Death                                # Edit, read-only verify
    runner studio ingest build_kfs --manifest ... --clip Death <result>
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
`--speed` for a walk (`stages.clips.animSpeedScale`, from `clips speed-scale`) or a borrowed clip (law 6). `frozen` is
one of the fields that say whether those numbers mean anything. The step applies
the game's own end-pose hold (`AdjustSpeed(0)` just before the clip ends), and
schedules it by TRACK time: a Heartbeat watcher freezes the track once
`TimePosition` is within three frames of `Length`. Do not schedule the hold by
wall time. A freshly loaded track sits at `TimePosition` 0 for most of a second,
so a wall-time hold lands that much short of the end. When `frozen` is false the
track ran out first, the Animator blended the clone back to its bind pose, the
numbers describe that standing pose, and the bench must be re-run. The result
also reports `frozeTp` and `lastTp` (the frozen and the last sampled
`TimePosition`) beside `length`: a bench whose `lastTp` is short of `length` by
more than one sample interval (0.25 s × speed) was held before the end, and
must be re-run too. The 0.25 s samples miss a clip's deepest frames, so the step
also tracks per-frame `extrema` over every frame once the track has advanced,
including the held end (`ankleMinY`,
`hipsMinY`, `headMinY`, `hipsTravelMax`, and the `frames` counted). They are a
few numbers, so the result stays small. Every Studio step ends by printing its result as one
`RUNNER_RESULT <json>` line AND returning that same line: `execute_luau`
surfaces a script's return value, not its console output, so the call's
return is the result to save for `studio ingest` (no `get_console_output`
needed). `mesh_dump`'s `RUNNER_CHUNK` lines are still console-only.

**Bench gates (eval rows E30-E32).** The bench timeline samples the hips,
head and both feet every 0.25 s relative to the root, so the two ways a
transferred clip commonly goes wrong are gated off it: soles that float above or
sink below the ground, and hips that slide away during a clip meant to play
where it stands. The foot samples are ankle BONES, above the sole, so a sole
is read as `ankle - (restAnkle - soleY)`: the ankle-to-sole distance the bind
pose stands on, carried through the clip. `restAnkle` is the lower ankle before
the track plays (the step reports it as `restAnkleY`; a bench recorded without it
uses its first sample at track time 0, which is the bind pose). The lowest sole,
the lowest point and the largest hips travel over the clip take the more extreme
of the per-frame `extrema` and the samples; a bench without `extrema` is read from
its samples alone. That distance
ignores foot pitch, so a strongly toe-down foot reads low. Which gates a clip
answers to follows how it moves:

| Motion | Clips | Gates |
|---|---|---|
| `in_place` | the default: Idle, Stun, Attack, Slam, any declared key not given another | E30: the lowest sole over the clip within ±`foot_contact_frac` × height of the ground. E31: the hips' largest horizontal travel from the start ≤ `root_travel_max_frac` × height, and the end pose ≤ `root_travel_end_frac` × height from the start |
| `fall` | Death | E30: nothing sampled (hips, head, soles) below −`foot_contact_frac` × height at any point. E32: the lowest end-pose point between −`foot_contact_frac` and +`fall_end_max_frac` × height |
| `travel` | Walk | E30: the lowest sole over the clip within ±`foot_contact_travel_frac` × height of the ground, a looser band because a walking foot pitches and the ankle reads it low. No root travel: the clip is meant to move, and its stride is E19's |

Defaults (fractions of `height_studs`): `foot_contact_frac` 0.029,
`foot_contact_travel_frac` 0.06, `root_travel_max_frac` 0.25, `root_travel_end_frac` 0.10, `fall_end_max_frac`
0.10. They are calibrated on one 70-stud character's benches: its accepted
in-place clips' lowest soles read -0.54 to -0.08 studs, and two rejected for
floating read +8.32 and +6.68. Its accepted walk's lowest sole read +0.271 (+0.004
of height) over every frame, and a walk rejected for landing high and then
sinking read -5.251 (-0.075 of height). Its accepted in-place hips travelled at most 4.19
to 13.63, and a rejected slide travelled 62.25. Its accepted fall's lowest end
point read +4.44 (the samples are bones inside the body, so a body lying on the
ground reads above it), and a rejected fall read -26.11. A title overrides any default, and any clip's motion,
under the manifest's top-level `bench_gates`:

    "bench_gates": {"root_travel_max_frac": 0.2, "motion": {"Crawl": "travel"}}

Each override is a number strictly between 0 and 1 naming a known gate, and
`motion` is an object of clip to class. `runner eval` refuses anything else by
name. `studio ingest bench_clip` still records the bench, and says it was not
judged. Every limit is inclusive: a reading exactly at a limit passes.

`studio ingest bench_clip` records every bench whatever it reads, and prints
one `bench gate:` line for each breach, with the clip, the reading, its fraction
of height and the limit. The verdict is `runner eval`'s: each row lists the
failing clips. A clip in scope with no usable bench is listed as `<clip> (no
bench: <why>)`: none was recorded, it was not `frozen` (the reason says whether the track ran
out or the bench's `--max-wait` did), or it was held short of
the clip's end (the reason gives the `TimePosition`, the length and the
shortfall). The row also prints every clip's reading under it with the band it is held to, and writes each clip's
readings, checks and breaches to `eval.json`'s `bench`. A row with no clip of
its motion in scope reads PEND.

**Steps a per-title skill adds.** A title that needs a Studio step of its own —
parking a static model in its own folder, or killing a live character through its
own remote to record a death timeline — registers the step rather than adding it
here. Such a step renders through this renderer with the title's own defaults and
ingests through its own handler, so its attribute names, its remotes and the
manifest keys it writes stay out of a pack that is mirrored publicly.

**Eval matrix.** `runner eval` prints and writes the eval-matrix table, rows
E1-E32 (E25 retired: no stage ever wrote its input, so it could only ever
report PENDING), reading only files on disk plus the manifest — it never
imports another stage module, so it runs standalone regardless of which stages
exist yet. A gate row with no evidence on disk reports FAIL, never PASS and
never silently skipped; a non-gate row with no evidence reports PENDING; rows
that measure a Studio artifact the runner cannot itself produce (E13/E14
far-LOD grounding, E24 the walk probe) read whatever `studio.py`'s
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
outright. So `clips.bind()` writes
`register_media` (`storage_class="platform"`,
`kind="animation-clip"`, `link_type=cast_member_model`) and
`finalize_media_registration` (`locator="rbxassetid://<id>"`,
`locator_type="platform_asset"`) payloads for the orchestrator to run for
real, and `clips registered --clip <name> --media-id <id>` records the
finalized Genvid id once it does. The payloads carry two boundary facts:
`register_media` refuses a `.rbxmx` filename ("Cannot determine media
type"), so the name is `<title>.glb` with `mime_type="model/gltf-binary"`, a
media-type hint only (no file of that name exists; the original is the
platform id); and `target="roblox"` / `stage="roblox/keyframesequence"` is not
a known destination and stage, so a clip finalizes with no target/stage.
Supersession is carried in the generation params (`supersedes_media_id`) and
in `input_media_ids`, never by deleting the earlier row. A clip's params also
carry its transfer options (`root_y`, `root_ref`, `g`, `g_from`, `trim`,
`time_scale`, `k`), and, when `stages.clips.superseded.<key>` holds a
registered item, `supersedes_media_id` names that item's Genvid media id. `record.run()` refuses an unregistered clip
unless run with `--allow-unregistered`, and eval row E27 reads PEND, never
PASS, while any clip is still only "payload written."

**Budget and claim gates, read through the genvid CLI.** Every emit gates the
estimate the agent passes (`--estimate <USD>`, `0` for a free model: the
check is required for every generation, a free one included). The runner reads
the headroom itself with `genvid get-generation-budget-headroom <project>
<estimate> [--asset-id <asset>]` (the REST read behind
`check_generation_budget`), stores the verdict with the command, the raw
response and the time in the manifest's `budget`, and writes the request only
on a literal `fits: true`. The verdict is keyed on the estimate, the model the
emit named and the item set; an emit that changes any of them gates again. A
response for a different estimate, or with no asset headroom on an asset
check, is refused; a refusal is read again on the next run. Every gate read
has a 60-second timeout and names the command when it fails. The headroom
command needs genvid CLI 0.0.5 or newer; an older CLI is refused with the
installed version and how to upgrade (`brew upgrade genvid` or install.sh).
The claim gate reads the same way: `genvid list-tasks` (the organization id
from `genvid get-project`), stored next to the status in the manifest's
`claims` (§0). No payload file is written for either read and nobody records
a verdict by hand: a cached verdict or claim status counts only when it
carries the gate's own read and that read answers it; anything else, a
hand-written `fits: true` included, is read again. The claim the runner
writes for an unclaimed task is still a `create_assignment` payload: until it
has run, the next bind on that asset stops with `ClaimPending` naming it
rather than writing a second one.

**Cost is attested by the agent, never priced by the runner.** The runner
holds no price list. Every ingest carries exactly one of `--cost <amount>`
(with `--currency <ISO 4217>`, USD by default) for what the generation cost,
or `--cost-unobserved` for a generation that was charged at an amount not
known. The bind sends the amount as `attested_cost_amount` /
`attested_cost_currency`; an unobserved cost omits both, which the boundary
records as unknown. It is never written as `0`, which is a claim that the
generation was free. Only USD counts toward project spend and budget
headroom: another currency is signed verbatim and does not reduce headroom.
The estimate on emit and the cost on ingest are different numbers: the
estimate is a pre-spend guess that feeds the gate and is never attested; the
cost is what the provider charged for a call that already happened. An
attested cost is signed into a C2PA manifest, so a guess must not be attested
as an observation: when the figure is not known, attest it as unobserved.

- **Read the cost from the provider's billing record, not its pricing page.**
  A pricing page can bill on a different axis (per call, per compute second,
  per credit) than the one a call is charged on, and says nothing about how
  many units one call consumes.
- **No cost literal lives in a stage or a driver.** The one sanctioned zero
  is a bind with no generation behind it (a local Blender step, or a re-bind
  of bytes whose cost another row already attests), and it is attested by
  name (`cost.NO_VENDOR_CALL`). A bundled clip's row attests no cost: the
  rig's row carries the spend.
- **Project spend attested this way is a FLOOR, not a total.** Attestation is
  anchored to bound media, and only media the boundary sees can carry a cost:
  rerolls, rejected candidates and intermediate calls that produce no bound
  row are real money no attested figure includes. Ingest and bind every
  generation, a rejected one included, so its cost is on a row. Eval row E29 checks a
  run's summed attested cost against its budget ceiling; whatever that sum
  comes to is a floor. **For a true total, reconcile against the provider's
  billing record.** Do not present an attested total as a complete one.

A skinned-rig character, end to end, in the order the steps can run (each
`emit` is followed by the agent running a model of the requested type, then the
matching `ingest`; each `studio emit` is followed by `execute_luau` and the
matching `studio ingest`):

    python3 runner/cli.py init --name Large --height 50 --out out/Large --project <project-id> \
        --production-title '<production title>' --assignee <reviewer email>
    python3 runner/cli.py plate emit front --manifest out/Large/manifest.json --estimate <USD> --prompt '<front prompt>'
    python3 runner/cli.py plate ingest front --manifest out/Large/manifest.json --item c1 --create-asset \
        --provider <provider> --model <model> --cost <amount> <result>
    python3 runner/cli.py plate select-front --manifest ... --media-id <bound candidate>
    python3 runner/cli.py plate emit views --manifest ... --estimate <USD>           # then plate ingest views --item back|left|right
    python3 runner/cli.py plate gaps --manifest ...                                  # limb-gap measurement for eval row E1 (needs PLATE_GAPS_PY)
    python3 runner/cli.py mesh emit model --manifest ... --estimate <USD>
    python3 runner/cli.py mesh ingest model --manifest ... --provider ... --model ... --cost ... <result>
    python3 runner/cli.py rig emit model --manifest ... --estimate <USD> [--clip Walk:'<motion>']
    python3 runner/cli.py rig ingest model --manifest ... --provider ... --model ... --cost ... --rig <result> [--clip Walk=<file>]
    # import the R15 rig into Studio with the 3D Importer; the template now sits in workspace
    python3 runner/cli.py studio emit scale --manifest ...                           # Edit; right after the import, before dump_rest
    python3 runner/cli.py studio emit dump_rest --manifest ...                       # Edit
    python3 runner/cli.py studio emit groundfit --manifest ...                       # Edit
    python3 runner/cli.py studio emit wire --manifest ...                            # Edit
    python3 runner/cli.py studio emit capture_ids --manifest ...                     # Edit; still in workspace (after park, pass --param MODEL_PATH=...)
    python3 runner/cli.py studio emit park --manifest ...                            # Edit; moves the template into the park folder
    python3 runner/cli.py studio emit settle|sethip|settle --manifest ...            # Play, Edit, Play: the hover correction
    python3 runner/cli.py studio emit probe_feet --manifest ...                      # Edit; then studio ingest probe_feet --lod close
    python3 runner/cli.py studio emit probe_feet --manifest ... --param LOD=far      # Edit; then studio ingest probe_feet --lod far
    python3 runner/cli.py studio emit probe_walk --manifest ...                      # Play; eval row E24
    python3 runner/cli.py clips transfer --manifest ... --clip Walk
    python3 runner/cli.py clips build --manifest ... --clip Walk                     # then let Rojo sync
    python3 runner/cli.py clips build-kfs --manifest ... --clip Walk                 # then studio ingest build_kfs --clip Walk
    python3 runner/cli.py clips publish-clip --manifest ... --clip Walk              # then studio ingest publish_clip --clip Walk
    python3 runner/cli.py clips bench --manifest ... --clip Walk                     # Play, Server; then studio ingest bench_clip --clip Walk
    python3 runner/cli.py studio emit treadmill --manifest ... --param WALK_ID=rbxassetid://<id>   # Play
    python3 runner/cli.py clips speed-scale --manifest ...                           # needs walk_speed on the manifest
    python3 runner/cli.py studio emit treadmill_scaled --manifest ... --param WALK_ID=rbxassetid://<id>   # Play, at the derived speed
    python3 runner/cli.py clips bind --manifest ... --ids Walk=<RobloxAssetId>       # the id publish-clip returned; the orchestrator runs the payloads
    python3 runner/cli.py clips registered --manifest ... --clip Walk --media-id <Genvid media id>
    python3 runner/cli.py record run --manifest ...

The other Studio steps are optional or situational: `inspect_template` reads an
already-parked template's structure (attribute names and holders, Humanoid
values, alignment settings) so a title can check the wiring against it;
`zoo_capture` frames the Studio camera on the character for a review capture; `applymesh` is the
surface pass above; `adopt_inspect` belongs to `rig adopt`.
