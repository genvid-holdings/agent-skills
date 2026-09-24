---
name: genvid-roblox-studio-ops
description: How to drive Roblox Studio over MCP for AI-generated 3D content without re-deriving a month of gotchas — bridge/session failure modes, execute_luau patterns, large-payload streaming, verification blind spots, crash hygiene, the generate_mesh/GenerateModelAsync generation surfaces and their ID-only reachability, 3D Importer limits, and where Auto-Setup fails.
compatibility: Standalone. Requires Roblox Studio open locally with its built-in MCP server enabled and connected; no Genvid boundary dependency.
---

# Roblox Studio MCP Operations

Operational knowledge for driving Roblox Studio over MCP — connecting the session, calling `execute_luau` reliably, moving large payloads, knowing what verification can and cannot see, and using Roblox's own AI generation surfaces (`generate_mesh`, `GenerationService:GenerateModelAsync`) correctly. This is the direct dependency of any MCP-first 3D generation workflow. It does not cover generation recipes (plate craft, mesh output checks, rig wiring) — that content belongs to a separate `genvid-roblox-character-generation` skill.

---

## Before you start a session

Studio must be **open with its MCP server enabled and the plugin connected before the agent session starts**, or the MCP tools never register and the agent cannot drive Studio at all.

1. Enable it once: **Assistant Settings** (the gear inside the Assistant panel, not the `⋯` menu) → **MCP Servers** → *Enable Studio as MCP server*. The toggle's location is easy to miss the first time.
2. After a fresh bridge start, allow **~10–15 seconds** before the first tool call — calling too soon fails with `"Unable to find an active Studio instance"`. The first time you enable the server, a full Studio restart may be required before it attaches.
3. If tools are missing mid-session (the agent registered before Studio was ready, or Studio was restarted), reconnect with `/mcp` rather than restarting the session.
4. If you are also running a Rojo-synced project, start `rojo serve` **detached** (e.g. `nohup rojo serve … & disown`) — run in the foreground, the driving harness reaps it, silently dropping the sync connection.

### The three bridge-failure modes

None of these resemble each other, and none of them says what's actually wrong — the fix is to recognize the shape, not the error text.

| # | Failure mode | Symptom | Fix |
|---|---|---|---|
| 1 | **Stale proxy on port 13469** | A leftover Claude Desktop `StudioMCP` proxy is already squatting the port; new tool registration silently never completes. | Kill the stale proxy process, run `/mcp`, then toggle Studio's MCP server off/on so the plugin re-dials against a clean port. |
| 2 | **MCP server registered in the wrong CLI config profile** | The server was registered only in the default `~/.claude.json` profile, not the project's own MCP profile — sessions in the project silently never see it. Reads as "bridge disconnected and never came back." | Commit a project-level `.mcp.json` so the registration travels with the repo instead of living only in a personal global profile. |
| 3 | **Multi-instance handshake** | A Studio window left open across a crash is invisible to a freshly spawned proxy — tool calls fail as if nothing is running, even though a Studio process is technically alive. | Quit Studio **entirely** (not just the window), reopen it, then `/mcp`. Partial restarts do not fix this. |

**A fourth, related symptom worth knowing even though it isn't a distinct failure mode:** the MCP connection can report **connected while advertising zero tools** if Studio wasn't open at session start. This is silent — there is no error, just an empty tool list — and the tool list only refreshes on reconnect (`/mcp`), never on its own. If your agent's tool list looks suspiciously short, this is the first thing to check, not a Studio bug to work around.

A first call on a fresh bridge sometimes fails with `"previously active Studio disconnected"` even when Studio is fine — retry once before treating it as one of the failure modes above.

---

## `execute_luau`: datamodel types and the scratch-script pattern

- `datamodel_type` is **`Edit`** in edit mode, and **`Server`** / **`Client`** during a Play session. Drive or inspect the running game with `Server`/`Client` Luau; `get_console_output` reads whatever it prints.
- Move the play-test player with **`Client`** `ch:PivotTo(...)` — a `PivotTo` issued from `Server` does not hold.
- If a script errors mid-Play, Studio gets stuck in Play mode and the next `Edit`-datamodel call fails outright. Stop play first: `start_stop_play {is_start: false}`.
- **Scratch-script pattern** for iterating on game code through the bridge: read the target script's current source, inject the revised source via `.Source = [=====[ ... ]=====]` (a long-bracket string, adjust the `=` run so it can't collide with content inside), then **destroy and recreate** the Instance rather than editing it in place.
- `require()` of a running service, called from `execute_luau`, returns a **fresh module copy**, not the live one — you cannot observe a running service's internal state this way. Read live state only through **attributes or Instance properties**, never through `require()`.
- Expect **15–40 second round trips** per `execute_luau` call — budget accordingly and batch related work into one call rather than many small ones.
- **Luau statements cannot start with `(`** inside a script you hand to `execute_luau`.
- `user_keyboard_input` invoked on the **Client** datamodel can trigger `ProximityPrompt`s in the scene — expect and handle that side effect rather than being surprised by it.
- Frame `screen_capture {capture_id, camera_position, look_at_position}` off the model's **`GetBoundingBox`** center, not its `HumanoidRootPart` — HRPs on these rigs are frequently placed somewhere that doesn't visually center the model.

---

## Large payloads: build on the host, not `_G` chunking

`_G` persists across calls within the same Studio session, so it works as a chunk-assembly buffer: stream geometry/texture data across several `execute_luau` calls into `_G`, then assemble. A single `execute_luau` call accepts at least a 700KB code string; the ceiling above that is unknown.

**A better pattern for anything non-trivial:** build the payload on the host and let Rojo sync it into the place, the way an animation clip comes in (below). Never fetch it from inside `execute_luau`: it runs sandboxed without the Network capability.

---

## Verification limits — what MCP tools cannot tell you

| Limitation | Why it matters | What to do instead |
|---|---|---|
| `screen_capture` is **blind to particle effects** | A screenshot-based verdict on any VFX (impact flashes, auras, spell effects) will read as "nothing there" even when it fired correctly. | FX verdicts need a human's eyes on the live viewport — do not trust a screen capture to confirm particle-based effects landed. |
| Never verify melee/combat by **teleporting the player** into range | `MovementSentry`-style anti-cheat logic flags the teleport and rubber-bands the player back. | Drive the player into range through normal movement (or a scripted approach that respects movement limits), not a `PivotTo`/teleport shortcut. |
| A server-side METHOD CALL never reaches a client (`ParticleEmitter:Emit`, `Sound:Play` on a server-owned instance, any `:Method()` fired from a Server script or `execute_luau` Server) | Only property writes and events replicate. An effect emitted server-side looks correct in a Server-datamodel check (`Enabled` flips) and renders on no client. | Fire a RemoteEvent and call the method on each client; the Server witness proves the event was sent, a Client-datamodel `OnClientEvent` hook proves it arrived. |
| `Bone.WorldPosition` / `WorldCFrame` ignore the bone's own animated `Transform` | A sampler on them reads a playing clip's root motion as zero and a fall as "nothing moved". | Sample `Bone.TransformedWorldCFrame`. |
| Cameras framed off the wrong anchor | Rigs frequently have an oddly-placed `HumanoidRootPart`; framing off it puts the subject off-center or out of frame. | Frame off `GetBoundingBox`, as noted above. |

---

## Crash hygiene

- **Crash-saves silently drop terrain voxels while keeping parts.** A place that crashed and was recovered from a crash-save can appear intact (all `Part`s present) while its `Terrain` has silently lost voxel data. A visual scan of parts is not an audit.
- **Post-crash audits must raycast-probe the terrain**, not just enumerate instances — that is the only way to catch the silent voxel loss above.
- **Avoid the AutoRecovery copy** as your working file after a crash; treat it as a diagnostic artifact, not the place to keep building on.

---

## Generation surfaces: `generate_mesh` vs `GenerationService:GenerateModelAsync`

Roblox Studio's MCP surface exposes two distinct AI generation paths with different capabilities, different calling contexts, and — critically — different provenance egress. Treat them as separate tools with separate rules, not interchangeable options.

| | `generate_mesh` (MCP tool) | `GenerationService:GenerateModelAsync` (via `execute_luau`) |
|---|---|---|
| Input | **Text only.** Silently ignores any attached image URI — it does not error, it just doesn't use it. | Image-conditioned: `Image` + a custom `SchemaDefinition` + `Size` compose together. |
| Calling context | MCP tool call | `execute_luau`, and it works from **Edit mode** — no Play session required. |
| Part naming | `partNames` must be passed **comma-separated**. Its JSON-array parsing is broken. | N/A |
| Asset egress | Uploads **per-part cloud `MeshId`/`TextureID` assets** — real asset IDs you can act on afterward. | Returns editable content with **empty asset refs**. There is nothing to retrieve later; whatever you need, capture at call time. |
| Moderation | Nondeterministic (observed on `GenerateModelAsync`; assume both surfaces and retry either). Identical inputs on separate calls can return `"Moderation failed"` on one and pass on the next. | Wrap either surface's moderation step with retry logic; do not treat one failure as conclusive. |
| Metadata | Exactly `{UUID}` — no other fields. | Exactly `{UUID}` — no other fields. |

**Reachability is ID-only, and there is no after-the-fact discovery.** Once you have a generated asset's ID, here is what each access path actually gives you — and none of it substitutes for capturing the generation's inputs/outputs at call time:

| Access path | Auth required | What it reveals |
|---|---|---|
| Public economy endpoint, by asset ID | None | Metadata + timestamps |
| Public thumbnails API | None (keyless) | Rendered thumbnail |
| `assetdelivery` / Open Cloud content | Key required | 403 without one |
| In-Studio MCP, same live session | N/A — live session only | Metadata, instances, **and full geometry** (`EditableMesh` verts/faces) |
| Authenticated Open Cloud GET (with a key) | Key required | Adds `revisionId` + `moderationState` — but still **zero** generative-AI provenance fields |
| Inventory `MESH_PART` filter | Authenticated | Returns **empty** for generated meshes; `IMAGE` is not even a valid filter type; there is no list-my-assets endpoint |

The conclusion this table supports: **capture generation inputs and outputs (plate/prompt, schema, size, the returned UUID, and any per-part asset IDs) at the moment of the call.** There is no query you can run later — authenticated or not — that recovers what a given generated asset was made from. Fresh UUIDs are minted on every call, even for what looks like cached geometry, so there is no dedup shortcut either.

---

## Import and publish paths — what an agent drives, what a human still does

Three of the four ways content enters Studio run end to end from the MCP
bridge with zero clicks; one runs from a script on the host machine; the
place publish is the only step that is a human's.

| Content | Agent-driven path |
|---|---|
| A **static mesh** (props, collectibles) | Never fetch the GLB's buffers from `execute_luau`: it has no Network capability. Build the data on the host and let Rojo sync it into the place, the route an animation clip takes; then decode in Luau, build an `EditableMesh` (`AddVertex`/`AddUV`/`AddNormal`, `AddTriangle` + `SetFaceUVs`/`SetFaceNormals`; glTF → Roblox = negate Z and reverse winding), `AssetService:CreateAssetAsync(em, Enum.AssetType.Mesh)` — it returns TWO values, `(Enum.CreateAssetResult, assetId)`; capture both — then `CreateMeshPartAsync` (collision fidelity set here) and park the part. Textures ride the same way through `EditableImage`. No dialog. |
| An **animation clip** | Write the `KeyframeSequence` as an `.rbxmx` on the host into the directory the project's Rojo tree maps to `ServerStorage/Assets/Anims`, let Rojo sync it, read it back from the bridge to confirm it landed, then `AssetService:CreateAssetAsync(kfs, Enum.AssetType.Animation, {Name, Description})` from the bridge's Edit context. `CreateAssetAsync` publishes a KeyframeSequence but rejects a MeshPart or a Model. Do not build it IN Studio from poses fetched over local HTTP: `execute_luau` has no Network capability. `CreateAssetAsync` returns a real asset id; there is no confirm or pay dialog on this call. An UNPUBLISHED sequence never advances when played, so publishing is not optional. |
| A **skinned rig** (rigged FBX/GLB with bones) | This one is the 3D Importer, and the Importer has no MCP surface. It IS drivable without a human on macOS: `osascript` opens File → Import (System Events, Accessibility granted to the terminal), the native open panel takes ⌘⇧G + the path + Return, and the Qt "Import" button — which ignores System Events clicks and Return — fires on a real CGEvent from a ~40-line Swift helper compiled with the Xcode toolchain (screen points = screenshot px / 2). The import creates the mesh asset, the packaged texture and an Asset Manager model; the agent then parks the result and, for a re-upload, swaps it into the live template with `MeshPart:ApplyMesh` so no wiring is redone. |
| The **place** (what players get) | None. Cmd-S saves; only File → Publish to Roblox ships the place, and the bridge cannot do either. Every session ends by telling the human to save and publish. |

Two more import facts: the Importer reads geometry and
skeletons only, never a file's animations (clips come in through the second
row); and `insert_asset` is not an import — it needs an existing cloud asset
id, not a local file.

What a human still does, and why:
- **Save and Publish the place.** No bridge call reaches either menu.
- **Moderation.** A published mesh can come back MODERATED with no reason
  shown; Roblox then renders it to its owner only, so the owner's own Play
  session proves nothing — verify with a non-owner account. Re-uploading the same content is moderated again.
- **Genvid approvals.** Every published mesh and clip is bound as governed
  media; the reviewer approves or rejects it in Genvid, never the agent.
- **Accessibility grant** for the scripted Importer path, once per machine.

---

## Auto-Setup: where it fails

Do not use Roblox Avatar Auto-Setup (cage/rig/segmentation/skinning from a single body mesh) for **spiky or non-humanoid bodies**. The rules below say why and what to check when it fails.

- **Cage/wrap shreds spiky surfaces in its cage-fitting step, regardless of who partitions the body first.** It fails in both the auto-segmentation and pre-partitioned modes — pre-partitioning does not rescue it. Treat this as a closed question for spiky/non-human silhouettes, not something to re-test per project.
- **Hard triangle ceiling: 10,742 for the whole body**, with per-part caps under that: Head 4,000 / Torso 1,750 / each Arm 1,248 / each Leg 1,248. Auto-Setup's limb partitioner applies its own caps during segmentation, so being over the total surfaces as the misleading *"Failed to generate the body cage… no holes, disjoint, self-intersecting or complex concave geometry"* error — the actual cause is budget, not geometry quality, even though the error text reads like a topology complaint.
- **Ingestion path matters independently of triangle budget.** Auto-Setup's cage generator needs a **file-imported** mesh (Studio's 3D Importer welds/cleans and creates a real mesh asset with proper normals). It rejects a same-shaped mesh built at runtime via `AssetService:CreateEditableMesh()`/`CreateMeshPartAsync`, with the identical misleading cage error. If Auto-Setup is failing, check triangle budget **and** ingestion path as two separate causes before concluding the mesh itself is bad — a project that was over-budget can appear fixed once trimmed to budget while still hitting the same error for the unrelated ingestion reason.
- **`DoubleSided = true` fixes smooth-body seams only.** On a clean, watertight, single-shell body, Auto-Setup's part-cutting step can leave single-sided rendering at the seams between its 15 generated parts, which reads as see-through gaps; `DoubleSided = true` closes them and is animation-safe (it does not change animation weights). It does **not** help a spiky/shredded surface — that failure is upstream of seams entirely.
- **Two-point scale calibration**, needed on any Auto-Setup-produced rig: these rigs commonly ship an oversized `HumanoidRootPart`, so `GetScale`/`ScaleTo` do not track the model's real bounding-box height. Calibrate by measuring actual height at `ScaleTo(4)` and again at `ScaleTo(8)`, then interpolate linearly between the two to find the scale that hits your target height. Insert a `task.wait` between the two measurements so the bounding box settles before you read it — reading immediately after a `ScaleTo` call can catch it mid-update.
- **Do not re-attempt the user-guided path:** the user-guided Auto-Setup path (supplying 15 pre-partitioned, R15-named body parts to skip auto-segmentation) does not rescue spiky bodies either — the cage-fitting failure is independent of who did the partitioning, per the first bullet above.

---

## Out of scope here

Generation *recipes* — plate craft, mesh output checks, the Blender rig recipe, the skinned-rig wiring recipe, render-distance verification law, animation-speed tuning — are not covered by this skill. That content belongs to `genvid-roblox-character-generation`.
