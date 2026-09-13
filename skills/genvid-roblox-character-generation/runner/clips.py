"""Stage 5 (runner): clip transfer -> KeyframeSequence -> bind.

Per logical clip (`clipsources.CATALOG`): `transfer()` runs `blender/poses.py`
on the chosen candidate to produce a poses JSON in the target rig's own
world-space rest frame; `build()` writes the KeyframeSequence `.rbxmx` Rojo
syncs into `game/anims/`; `impact()` and `speed_scale()` compute the two
game-facing numbers (`attackImpactDelaySecs`, `animSpeedScale`) the interface
contract hands to the game's own character-type table; `build_kfs()` and `publish_clip()` are the primary in-Studio path -- the
KeyframeSequence is built from the poses JSON served over local HTTP and
published with `AssetService:CreateAssetAsync`, so neither a Rojo sync nor a
Save to Roblox click is on the path to a playable clip; `bind()` writes the
platform-tier registration payloads once a clip has a published Roblox asset
id, and `registered()` records the finalized Genvid media id once the
orchestrator has actually run them.

ORCHESTRATOR STEPS (written and unit-testable, never executed by this runner):
`fetch()` re-submits `fal-ai/meshy/rigging/multi-animation` for extra Meshy
library clip ids not in the rig's original call ($0.08, real vendor spend);
`bind()` writes `register_media` / `finalize_media_registration` MCP payloads
(platform tier) for the orchestrator to run for real -- a published clip is
platform-custodied media (the bytes live only as a Roblox asset id), and the
boundary rejects a direct `genvid import-generated-media` upload of the
`.rbxmx` outright (422 "Cannot determine media type from filename ...rbxmx",
witnessed 2026-09-04), so there is no synchronous upload call on this path at
all; `registered()` is the second half, run once the orchestrator has the
finalized Genvid media id back.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import clipsources
import genvid_bind
import kfs
import manifest
import plate
import studio
import timing
from impact import impact_time
from vendors import meshy, pricing

POSES_SCRIPT = Path(__file__).parent / "blender" / "poses.py"

ANIMS_DIR_ENV = "GAME_ANIMS_DIR"


def anims_dir():
    """Where `build()` writes a clip's KeyframeSequence .rbxmx -- the title's own
    Rojo-synced animation directory, named by $GAME_ANIMS_DIR.

    REQUIRED, with no default. The default this replaced pointed at one checkout
    under the author's home directory: on any other machine it silently wrote a real
    .rbxmx into a path nothing syncs, and reaching Studio is the whole purpose of this
    fallback path. A per-title skill exports the variable (it knows its own repo); a
    caller driving this pack directly passes `--anims-dir`."""
    root = os.environ.get(ANIMS_DIR_ENV)
    if not root:
        raise RuntimeError(
            "%s is not set and has no default: it must name the directory this title's "
            "Rojo project maps its animations from, because a KeyframeSequence written "
            "anywhere else never reaches Studio. Export it (a per-title skill does this "
            "for you) or pass --anims-dir." % ANIMS_DIR_ENV)
    return Path(root).expanduser()


def _resolve_anims_dir(value):
    """An explicit directory, else the required environment variable. Separate from
    `anims_dir()` only because `build`'s own parameter shadows that name."""
    return Path(value).expanduser() if value else anims_dir()


def _rig_clip_path(m, ref):
    """Where a meshy-library clip lives: `<out_dir>/clips/<ref>.glb`, downloaded
    either by `rig.gen()` (the clip ids in the original rig call) or by
    `fetch()` (an id fetched afterward). Both write to the same directory."""
    return Path(m["out_dir"]) / "clips" / ("%s.glb" % ref)


def transfer(m, clip, candidate, *, rest="rest.json", archive_root=None, downloads=None, blender=None):
    """Run `blender/poses.py` on `candidate` for `clip`; record the result under
    `stages.clips.items[<clip>]` and return the poses JSON path."""
    manifest.require_stage(m, "clips")
    source = candidate["source"]
    mode = candidate.get("mode")
    if mode is None:
        raise ValueError(
            "candidate for %r has no local transfer mode (source=%r): this is the "
            "orchestrator-only leg noted on clipsources.CATALOG -- resolve it by hand "
            "(submit the vendor job, download the clip) and call transfer() again with "
            "a mixamo-archive-shaped candidate pointing at the downloaded file" % (clip, source))

    out = Path(m["out_dir"])
    rest_path = Path(rest) if Path(rest).is_absolute() else out / rest

    if source == "meshy-library":
        ref = str(candidate["ref"])
        clip_path = _rig_clip_path(m, ref)
        if not clip_path.is_file():
            raise FileNotFoundError(
                "meshy-library clip %s.glb not found under %s; it should have arrived with the "
                "rig (`rig gen --clips`) or via a prior clips.fetch()" % (ref, clip_path.parent))
        fetched = (m["stages"].get("clips", {}).get("fetched") or {}).get(ref)
        cost_usd = fetched["cost_usd"] if fetched else pricing.NO_VENDOR_CALL  # bundled with rig.gen()'s own attestation
    elif source in ("mixamo-archive", "quaternius"):
        root = Path(archive_root) if archive_root else clipsources.archive_root()
        dl = Path(downloads) if downloads else clipsources.DEFAULT_DOWNLOADS
        clip_path = clipsources.locate(candidate, root, dl)
        if clip_path is None:
            raise FileNotFoundError("no local file found for %s candidate %r (clip %s)" % (source, candidate, clip))
        cost_usd = pricing.NO_VENDOR_CALL
    else:
        raise ValueError(
            "transfer() cannot resolve source %r locally for clip %s; see clipsources.CATALOG's "
            "note on meshy-text-to-motion" % (source, clip))

    # eval_cmd.py's Ctx (its own docstring, "Conventions this module assumes")
    # reads `<out_dir>/clips/<Clip>.poses.json` plus a sibling
    # `<Clip>.traj.json` -- write there, not `<out_dir>/poses/<Clip>.json`,
    # so the E15/E16/E17/E18/E21 gate rows have evidence on disk instead of
    # reading None and failing "missing" forever.
    out_path = out / "clips" / ("%s.poses.json" % clip)
    out_path.parent.mkdir(parents=True, exist_ok=True)  # poses.py itself does not create it
    argv = [blender or shutil.which("blender"), "--background", "--python-exit-code", "1",
            "--python", str(POSES_SCRIPT), "--", str(clip_path), str(rest_path), str(out_path), mode,
            "--rig-height=%s" % m["height_studs"]]
    if source == "quaternius":
        argv.append("--action=%s" % candidate["ref"])
    r = subprocess.run(argv, capture_output=True, text=True)
    # --python-exit-code 1 (as rig.r15() uses): without it Blender exits 0 on a
    # raised exception too, and a stale poses.json from an earlier run would
    # then read as a successful transfer.
    if r.returncode != 0 or not out_path.exists():
        raise RuntimeError("clip transfer failed for %s (rc=%s, wrote=%s): %s"
                           % (clip, r.returncode, out_path.exists(), r.stderr[-2000:]))
    poses = json.loads(out_path.read_text())
    clip_seconds = poses["clip_seconds"]
    scaled_seconds = timing.scale_time(clip_seconds, m["height_studs"])

    # Ctx.clip_traj reads the world-space trajectories as their own file, a
    # plain {bone: [[t, x, y, z], ...]} -- the same shape metrics.foot_lift /
    # metrics.impact_height take -- not nested under the poses doc's "traj"
    # key. poses.py writes both into the one combined doc; split the
    # trajectories back out to the sibling file Ctx and the eval rows expect.
    traj_path = out / "clips" / ("%s.traj.json" % clip)
    traj_path.write_text(json.dumps(poses["traj"]))

    items = dict(m["stages"].get("clips", {}).get("items") or {})
    items[clip] = {"clip": clip, "source": source, "ref": candidate["ref"], "mode": mode,
                   "poses": str(out_path), "clip_seconds": clip_seconds, "scaled_seconds": scaled_seconds,
                   "loop": candidate["loop"], "priority": candidate["priority"], "cost_usd": cost_usd}
    manifest.set_stage(m, "clips", items=items)
    manifest.save(m)
    return out_path


def clip_title(m, clip, version=1, name=None):
    """The published KeyframeSequence title for this clip.

    `name` overrides the character prefix. It exists because the Studio template
    name and the published clip title are governed by different rules and came
    apart on the bake-off (witnessed 2026-09-04): the cross-track contract pinned
    template names carrying vendor words, and `kfs.clip_name` refuses to build a
    published title from one, since a published asset title carries no source
    brand. Default is the manifest's own `name`, which is already the brand-free
    one (`contract_name` is what the template answers to)."""
    return kfs.clip_name(name or m["name"], clip, version)


# The runner serves <out_dir> over plain local HTTP so Studio can fetch the poses
# JSON: HttpService reaches 127.0.0.1 from Studio (witnessed 2026-09-04), which
# is what lets the KeyframeSequence be built IN Studio with no Rojo sync.
POSES_HOST = "127.0.0.1"
POSES_PORT = 8765


def _port_open(host, port):
    with socket.socket() as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, int(port))) == 0


def serve_out_dir(m, *, host=POSES_HOST, port=POSES_PORT, is_open=_port_open,
                  popen=subprocess.Popen, sleep=time.sleep):
    """Return the base URL for `<out_dir>` over local HTTP, starting a server
    only if nothing is already listening on the port. Bound to 127.0.0.1: this
    serves generated artifacts to Studio on the same machine and has no business
    on any other interface."""
    if not is_open(host, port):
        popen([sys.executable, "-m", "http.server", str(port), "--bind", host,
               "--directory", str(Path(m["out_dir"]))],
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if is_open(host, port):
                break
            sleep(0.1)
        else:
            raise RuntimeError("no HTTP server answering on %s:%s after 5s; start one rooted at %s "
                               "(python3 -m http.server %s --bind %s --directory %s)"
                               % (host, port, m["out_dir"], port, host, m["out_dir"]))
    return "http://%s:%s" % (host, port)


def poses_url(m, clip, **kw):
    """The URL Studio fetches this clip's poses JSON from. `transfer()` writes it
    at `<out_dir>/clips/<Clip>.poses.json`, so the path is that, relative to the
    served root."""
    return "%s/clips/%s.poses.json" % (serve_out_dir(m, **kw), clip)


def build_kfs(m, clip, *, version=1, name=None, server=None):
    """Emit the `build_kfs` Studio step for `clip`: the KeyframeSequence is built
    IN Studio from the poses JSON served over local HTTP, so the Rojo .rbxmx sync
    is not on the path to a playable clip (it stays as the fallback, `build()`).

    `{{SCALE}}` is the sqrt-cadence multiplier, the same factor `kfs.write`
    applies to every keyframe time -- passed explicitly, since `studio.emit`'s
    own SCALE default is the unrelated GroundFitScale."""
    item = m["stages"]["clips"]["items"][clip]
    title = clip_title(m, clip, version, name)
    url = poses_url(m, clip, **(server or {}))
    return studio.emit(m, "build_kfs", CLIP=clip, CLIP_NAME=title, POSES_URL=url,
                       SCALE=timing.scale_time(1.0, m["height_studs"]),
                       LOOP="true" if item["loop"] else "false", PRIORITY=item["priority"])


def publish_clip(m, clip, *, version=1, name=None):
    """Emit the `publish_clip` Studio step: AssetService:CreateAssetAsync on the
    built KeyframeSequence, which returns a real asset id from the bridge's Edit
    context (witnessed 2026-09-04) and writes it onto the template as
    `<Clip>AnimId`. This is what replaces the manual Save to Roblox click -- and
    it is not optional: an unpublished sequence loads with the right Length and
    never advances."""
    title = clip_title(m, clip, version, name)
    return studio.emit(m, "publish_clip", CLIP=clip, CLIP_NAME=title,
                       DESCRIPTION="%s clip for %s, built from the transferred poses"
                                   % (clip, manifest.template_name(m)))


def bench(m, clip, *, speed=None, max_wait=25, at=(0, 300, 0)):
    """Emit the `bench_clip` Studio step (PLAY, Server datamodel) for a clip that
    has ALREADY been published: the clone plays the published id, since a parked
    sequence never advances. `speed` defaults to 1 (a death/attack clip) --
    pass `m["stages"]["clips"]["animSpeedScale"]` for a walk, or the sqrt-height
    ratio when a rig borrows another rig's clip (SKILL.md law 6)."""
    items = (m["stages"].get("clips") or {}).get("items") or {}
    if clip not in items:
        raise ValueError("clips.bench(%s): not on stages.clips.items (have %s) -- run clips transfer first"
                         % (clip, sorted(items) or "none"))
    item = items[clip]
    roblox_id = item.get("roblox_id")
    if not roblox_id:
        raise ValueError("clips.bench(%s): no roblox_id on the clip item -- publish it first "
                         "(clips publish-clip + studio ingest publish_clip --clip %s)" % (clip, clip))
    return studio.emit(m, "bench_clip", CLIP=clip, ANIM_ID="rbxassetid://%s" % roblox_id,
                       SPEED=float(speed or 1), MAX_WAIT=int(max_wait),
                       BENCH_X=at[0], BENCH_Y=at[1], BENCH_Z=at[2])


def build(m, clip, *, anims_dir=None, version=1, name=None):
    """FALLBACK path: write the clip's KeyframeSequence .rbxmx (name via
    `clip_title`) into `anims_dir` -- the title's own Rojo-mapped animation
    directory, defaulting to $GAME_ANIMS_DIR, which is required (see `anims_dir()`);
    record it on the
    clip's item and on `stages.clips.clip_names` (E22's naming-law gate reads
    this list). The primary path is `build_kfs` + `publish_clip`, which needs no
    file sync; this one stays for a Studio session with no HTTP reach."""
    items = dict(m["stages"]["clips"]["items"])
    item = items[clip]
    poses = json.loads(Path(item["poses"]).read_text())
    name = clip_title(m, clip, version, name)
    path = _resolve_anims_dir(anims_dir) / ("%s.rbxmx" % name)
    # the Studio scale step's factor (stages.wire.result.scale, from wire.luau's
    # ingest) is what the Animator multiplies pose translations by
    root_scale = float(((m["stages"].get("wire") or {}).get("result") or {}).get("scale") or 1.0)
    kfs.write(poses, path, name=name, height_studs=m["height_studs"], loop=item["loop"], priority=item["priority"], root_scale=root_scale)
    item = dict(item, rbxmx=str(path), kfs_name=name)
    items[clip] = item
    names = sorted(set((m["stages"]["clips"].get("clip_names") or [])) | {name})
    manifest.set_stage(m, "clips", items=items, clip_names=names)
    manifest.save(m)
    return path


def impact(m, clip):
    """Impact time for `clip` (scaled by timing), recorded as
    `stages.clips.attackImpactDelaySecs`. impact_time()'s 0.0 return means "no
    lift found in this clip's trajectory" (impact.py's own docstring) -- never
    record that as a real delay, since the game would then fire damage on
    frame one; raise instead so the caller picks a different candidate."""
    item = m["stages"]["clips"]["items"][clip]
    poses = json.loads(Path(item["poses"]).read_text())
    t = impact_time(poses["traj"])
    if t <= 0.0:
        raise RuntimeError(
            "impact.impact_time found no lift-then-strike in the %r clip's trajectory (0.0 back); "
            "recording that as attackImpactDelaySecs would fire damage on frame one -- try a "
            "different candidate for this clip" % clip)
    scaled = timing.scale_time(t, m["height_studs"])
    manifest.set_stage(m, "clips", attackImpactDelaySecs=scaled)
    manifest.save(m)
    return scaled


def speed_scale(m):
    """animSpeedScale = walkSpeed / strideStudsPerSec, from the in-engine
    treadmill measurement (`studio.py` ingests `treadmill.luau`'s
    `strideStudsPerSec` to `stages.clips.treadmill`) and `m["walk_speed"]` --
    the game-side Humanoid.WalkSpeed for this character type (the game's own
    concern, not a runner stage output; eval_cmd.py's E19 row already reads
    this same top-level manifest convention -- see its `_row_E19` docstring)."""
    treadmill = m["stages"].get("clips", {}).get("treadmill")
    if not treadmill or not treadmill.get("strideStudsPerSec"):
        raise RuntimeError("no stages.clips.treadmill.strideStudsPerSec recorded; "
                           "run `studio emit/ingest treadmill` before speed_scale()")
    walk_speed = m.get("walk_speed")
    if walk_speed is None:
        raise RuntimeError("no walk_speed on the manifest (m['walk_speed']); set the character's "
                           "intended Humanoid.WalkSpeed before computing animSpeedScale")
    scale = float(walk_speed) / float(treadmill["strideStudsPerSec"])
    manifest.set_stage(m, "clips", animSpeedScale=scale)
    manifest.save(m)
    return scale


def fetch(m, ids, t, poll_secs=15):
    """ORCHESTRATOR STEP -- never called by this runner. Extra Meshy library
    clips after the rig already exists (`clips fetch --ids 127,171`):
    re-submits `fal-ai/meshy/rigging/multi-animation` against the SAME mesh
    GLB ($0.08 flat; the rig comes back byte-identical to the original rig
    call, the requested clips are what we keep). Gated by `plate.budget_gate`
    before the vendor submit, per the pack's mandatory pre-spend check; the
    per-clip share of the attested cost is recorded on `stages.clips.fetched`
    so `transfer()` can attest it (never "0") when it later builds that clip."""
    manifest.require_stage(m, "clips")
    # meshy.rig_with_clips dedupes internally (dict.fromkeys); dedupe the same way
    # here so the id list this loop asks for matches what was actually submitted.
    ids = list(dict.fromkeys(int(i) for i in ids))
    # The rig input is the same one rig.gen used: the normalized mesh this runner
    # uploaded when mesh prep turned it, else the vendor's raw CDN url. Asking for
    # extra clips against a DIFFERENT mesh than the rig was built from would come
    # back rigged to the wrong body.
    mesh_st = m["stages"]["mesh"]
    raw_url = mesh_st.get("rig_input_url") or mesh_st["raw_url"]
    plate.budget_gate(m, "clips", pricing.estimate_of(meshy.RIG_CLIPS))
    rid = meshy.rig_with_clips(raw_url, ids, t, height_meters=1.8)
    manifest.set_stage(m, "clips", fetch_request_id=rid)
    manifest.save(m)
    res = meshy.wait(meshy.RIG_CLIPS, rid, t, poll_secs=poll_secs)
    cost = pricing.cost_of(meshy.RIG_CLIPS, res)
    # Split at the same 4 places every attested figure carries; the rig call is
    # billed once for all the clips it returns, so each clip attests its share.
    per_clip_cost = str((Decimal(cost) / Decimal(len(ids))).quantize(pricing.FOUR_PLACES)) if ids else cost
    fetched = dict(m["stages"]["clips"].get("fetched") or {})
    for cid in ids:
        # By ACTION ID: animations[] comes back in the vendor's order, so an
        # index read here would save one clip's GLB under another clip's id.
        url = meshy.result_url(res, "clip[%d]" % cid)
        t.download(url, _rig_clip_path(m, cid))
        fetched[str(cid)] = {"url": url, "cost_usd": per_clip_cost}
    manifest.set_stage(m, "clips", fetched=fetched, fetch_cost_usd=cost)
    manifest.save(m)
    return fetched


def _pending_media_id(register_path):
    """Placeholder for `finalize_media_registration`'s required `media_id` field
    (the PENDING registry row id `register_media`'s own response returns) --
    unknowable here, since this runner never calls that MCP tool itself. Names
    the sibling register payload file so the orchestrator knows exactly which
    response to read the real id from before running finalize."""
    return "PENDING:%s" % register_path.name


def bind(m, ids, version=1, name=None):
    """ORCHESTRATOR STEP for its governed writes -- never called by this
    runner. `ids`: `{clip: roblox_asset_id}` for every clip a human has
    published (`publish_clip`'s `CreateAssetAsync`, or a manual Save to
    Roblox). `version`/`name` match the published title `publish_clip`/
    `build` used (see `clip_title`) -- see the module docstring for why the
    Studio template name and the published title can differ.

    A published clip is PLATFORM-CUSTODIED media: the bytes live only as a
    Roblox asset id, which is exactly what `register_media`'s
    `storage_class="platform"` / `locator_type="platform_asset"` tier is for
    (SKILL.md 5.1) -- and the boundary rejects a direct `genvid
    import-generated-media` upload of a `.rbxmx` outright (422 "Cannot
    determine media type from filename", witnessed 2026-09-04), so there is
    no synchronous upload call on this path at all, unlike `rig.bind()` /
    `mesh.bind()`. Per clip this writes two `register_media` /
    `finalize_media_registration` MCP payloads (`genvid_bind.mcp_payload`,
    for the orchestrator to run for real):

    - `register_media`: `storage_class="platform"`, `kind="animation-clip"`
      (the genvid-media-registration vocabulary for a rig animation, distinct
      from `"mesh"`), `link_type=genvid_bind.MODEL_LINK`
      (`cast_member_model` -- the pack rule is prefix = asset type), a `.glb`
      filename with `mime_type="model/gltf-binary"` (the media-type HINT the
      boundary accepts for a model row; there is no such file -- an `.rbxmx`
      name is rejected outright, so the payload must carry a `.glb` name;
      shape witnessed 2026-09-10). No
      `proxy_filename`: the platform tier permits no proxy.
    - `finalize_media_registration`: `locator="rbxassetid://<id>"`,
      `locator_type="platform_asset"`, `identifiers=[{"identifier_scope":
      "roblox.com", "identifier_value": "asset_id:<id>"}]` (the schema's
      `IdentifierInput` shape, not a bare string list -- `<id>` here is the
      PUBLISHED ROBLOX asset id, never the Genvid anchor id `m["asset_id"]`,
      which is artifact-scoped and, being the same value for every clip,
      would also trip the `(org, scope, value)` duplicate-identifier
      rejection on the second clip's finalize), and `generation={"provider":
      "runner", "model": "world-space-transfer", "prompt": <clip source
      line>, "params": {...}}` (a JSON OBJECT, per the schema, not a
      string). `target="roblox"`/`stage="roblox/keyframesequence"` mirror
      what makes a row conformance-checkable (SKILL.md 5.1); the exact
      `"roblox/keyframesequence"` stage string is UNVERIFIED against a
      published target_vocabulary (the schema says to check one, and no such
      check ran here), carried forward from the code this replaces.
      `input_media_ids=[]`: there is no already-known Genvid media id this
      registration derives from (the old code pointed at its own now-removed
      multipart-import id). Two more schema-required fields are left for the
      orchestrator to fill when it actually runs this: `media_id` (the
      placeholder `_pending_media_id` writes) and `size_bytes` (unknowable
      without reading the .rbxmx this runner never re-opens on this path).

    Records `stages.clips.items[clip].roblox_id` and `.registration =
    {"state": "payload_written", "register_payload": <path>,
    "finalize_payload": <path>}` -- and mirrors the id onto
    `stages.clips.roblox_ids[clip]`, the same shape `publish_clip`'s Studio
    ingest already writes (`studio.ingest(m, "publish_clip", ...)`), so the
    two paths agree. `"payload_written"` is not `"registered"`:
    `manifest.require_stage(m, "record")` (default, strict) will not treat
    this clip as bound until `registered()` below records the orchestrator's
    real finalize result -- or `record run --allow-unregistered` tolerates
    this state and eval row E27 reads PEND, never PASS, for it.
    """
    # Media-bind-only site -- before the first register_media payload, not
    # per-clip (one claim covers every clip's payload pair in this call).
    genvid_bind.ensure_claim(m, m["asset_id"], "clips")
    items = dict(m["stages"]["clips"]["items"])
    roblox_ids = dict(m["stages"].get("clips", {}).get("roblox_ids") or {})
    for clip, roblox_id in ids.items():
        item = items[clip]
        title = clip_title(m, clip, version, name)
        # A `.rbxmx` filename is rejected at register_media (422 "Cannot determine
        # media type from filename", 2026-09-04) and so was every bind from
        # 2026-09-04 to 09-09, which the orchestrator re-shaped by hand. The shape
        # that lands (witnessed 2026-09-10 on two bound clips): a geometry
        # extension so the row types as a model, with `kind="animation-clip"`
        # saying what it is. The extension is a media-type hint only -- no file of
        # that name exists; the original is the platform id.
        filename = "%s.glb" % title
        mime_type = "model/gltf-binary"
        # size_bytes is a required finalize field; the published KeyframeSequence
        # has no file, so the size WITNESSED here is the transfer output the
        # sequence was built from, and params says so.
        poses_path = Path(item.get("poses") or "")
        if not poses_path.is_file():
            raise FileNotFoundError("clips.bind(%s): poses file %r not on disk; size_bytes must be measured, not guessed"
                                    % (clip, item.get("poses")))
        size_bytes = poses_path.stat().st_size

        register_path = genvid_bind.mcp_payload("register_media", m["out_dir"], project_id=m["project_id"],
            link_type=genvid_bind.MODEL_LINK, asset_id=m["asset_id"], filename=filename,
            mime_type=mime_type, storage_class="platform", kind="animation-clip")

        prompt = "%s clip for %s, %s source ref %s (%s world-space transfer)" % (
            clip, manifest.template_name(m), item["source"], item["ref"], item["mode"])
        generation = {"provider": "runner", "model": "world-space-transfer", "prompt": prompt,
                     "params": {"clip": clip, "source": item["source"], "ref": item["ref"], "mode": item["mode"],
                                "clip_seconds": item["clip_seconds"], "scaled_seconds": item["scaled_seconds"],
                                "loop": item["loop"], "priority": item["priority"],
                                "size_bytes_is": "the transfer's poses JSON the KeyframeSequence was built from; "
                                                 "the published sequence has no file"}}
        identifiers = [{"identifier_scope": "roblox.com", "identifier_value": "asset_id:%s" % roblox_id}]
        finalize_path = genvid_bind.mcp_payload("finalize_media_registration", m["out_dir"],
            project_id=m["project_id"], media_id=_pending_media_id(register_path),
            link_type=genvid_bind.MODEL_LINK, asset_id=m["asset_id"], filename=filename,
            mime_type=mime_type, size_bytes=size_bytes, duration_seconds=item["scaled_seconds"],
            locator="rbxassetid://%s" % roblox_id, locator_type="platform_asset",
            storage_class="platform", identifiers=identifiers, generation=generation, input_media_ids=[])
        # No target/stage: finalize rejects target="roblox" + stage="roblox/keyframesequence"
        # ("not a known destination and pipeline stage", 2026-09-08); the clip rows
        # bind without them until the target vocabulary grows a clip stage.

        roblox_ids[clip] = str(roblox_id)
        items[clip] = dict(item, roblox_id=str(roblox_id),
                           registration={"state": "payload_written",
                                        "register_payload": str(register_path),
                                        "finalize_payload": str(finalize_path)})
        manifest.set_stage(m, "clips", items=dict(items), roblox_ids=dict(roblox_ids))
        manifest.note(m, "clips bind: %s registered at platform tier (rbxassetid %s); payloads written "
                          "(%s, %s), awaiting the orchestrator's register_media + finalize_media_registration "
                          "calls and `clips registered --clip %s --media-id <id>`"
                          % (clip, roblox_id, register_path.name, finalize_path.name, clip))
        manifest.save(m)
    return items


def registered(m, clip, media_id):
    """The second half of `bind()`'s platform-tier capture -- run once the
    orchestrator has actually executed `clip`'s `register_media` +
    `finalize_media_registration` payloads and has the finalized Genvid media
    id back. Moves `stages.clips.items[clip].registration.state` from
    `"payload_written"` to `"registered"` and records `media_id` on it; also
    mirrors `media_id` onto `stages.clips.media_ids[clip]` and, for Walk, the
    top-level `stages.clips.media_id` -- the same shapes `record.run()`'s
    per-clip conformance loop and eval row E27's bound-media count already
    read, so neither needed to change to learn about a registration this
    runner itself never makes."""
    items = dict(m["stages"]["clips"]["items"])
    item = items.get(clip)
    if item is None:
        raise ValueError("no stages.clips.items[%r] on the manifest" % clip)
    registration = dict(item.get("registration") or {})
    if not registration:
        raise RuntimeError("clip %r has no registration payloads on record; run `clips bind` for it first" % clip)
    registration.update(state="registered", media_id=media_id)
    items[clip] = dict(item, registration=registration)
    manifest.set_stage(m, "clips", items=items)

    media_ids = dict(m["stages"]["clips"].get("media_ids") or {})
    media_ids[clip] = media_id
    manifest.set_stage(m, "clips", media_ids=media_ids)
    if clip == "Walk":
        manifest.set_stage(m, "clips", media_id=media_id)
    manifest.note(m, "clips registered: %s -> Genvid media %s" % (clip, media_id))
    manifest.save(m)
    return items[clip]


def _transfer_cli(x):
    candidate = clipsources.CATALOG[x.clip][x.candidate]
    transfer(manifest.load(x.manifest), x.clip, candidate, rest=x.rest,
             archive_root=x.archive_root, downloads=x.downloads, blender=x.blender)


def _build_cli(x):
    build(manifest.load(x.manifest), x.clip, anims_dir=x.anims_dir, version=x.version, name=x.name)


def _build_kfs_cli(x):
    build_kfs(manifest.load(x.manifest), x.clip, version=x.version, name=x.name,
              server={"port": x.port})
    return 0


def _publish_clip_cli(x):
    publish_clip(manifest.load(x.manifest), x.clip, version=x.version, name=x.name)
    return 0


def _bench_cli(x):
    bench(manifest.load(x.manifest), x.clip, speed=x.speed, max_wait=x.max_wait)
    return 0


def _impact_cli(x):
    impact(manifest.load(x.manifest), x.clip)


def _speed_scale_cli(x):
    speed_scale(manifest.load(x.manifest))


def _fetch_cli(x):
    ids = [int(i) for i in str(x.ids).split(",") if i.strip()]
    fetch(manifest.load(x.manifest), ids, meshy.transport())


def _bind_cli(x):
    ids = dict(kv.split("=", 1) for kv in x.ids)
    bind(manifest.load(x.manifest), ids, version=x.version, name=x.name)


def _registered_cli(x):
    registered(manifest.load(x.manifest), x.clip, x.media_id)


def register(sub):
    p = sub.add_parser("clips"); s = p.add_subparsers(dest="cmd", required=True)

    a = s.add_parser("transfer"); a.add_argument("--manifest", required=True)
    a.add_argument("--clip", required=True, choices=sorted(clipsources.CATALOG))
    a.add_argument("--candidate", type=int, default=0, help="index into clipsources.CATALOG[clip]")
    a.add_argument("--rest", default="rest.json")
    a.add_argument("--archive-root", help="the animation archive tree; defaults to "
                   "$ANIM_LIBRARY_ROOT, which is required when this is omitted")
    a.add_argument("--downloads", help="default: ANIM_LIBRARY_DOWNLOADS env or ~/Downloads")
    a.add_argument("--blender")
    a.set_defaults(func=_transfer_cli)

    b = s.add_parser("build"); b.add_argument("--manifest", required=True)
    b.add_argument("--clip", required=True, choices=sorted(clipsources.CATALOG))
    b.add_argument("--anims-dir", default=None,
                   help="where to write the KeyframeSequence .rbxmx; defaults to "
                        "$GAME_ANIMS_DIR, which is required when this is omitted")
    b.add_argument("--version", type=int, default=1)
    b.add_argument("--name", default=None,
                   help="character prefix for the published clip title, when the Studio template's "
                        "own name is not one a published asset title may carry (no source brand)")
    b.set_defaults(func=_build_cli)

    bk = s.add_parser("build-kfs", help="emit the Studio step that builds the KeyframeSequence in Studio")
    bk.add_argument("--manifest", required=True)
    bk.add_argument("--clip", required=True, choices=sorted(clipsources.CATALOG))
    bk.add_argument("--version", type=int, default=1)
    bk.add_argument("--name", default=None, help="see `clips build --name`")
    bk.add_argument("--port", type=int, default=POSES_PORT, help="local HTTP port serving <out_dir>")
    bk.set_defaults(func=_build_kfs_cli)

    pc = s.add_parser("publish-clip", help="emit the Studio step that publishes the built KeyframeSequence")
    pc.add_argument("--manifest", required=True)
    pc.add_argument("--clip", required=True, choices=sorted(clipsources.CATALOG))
    pc.add_argument("--version", type=int, default=1)
    pc.add_argument("--name", default=None, help="see `clips build --name`")
    pc.set_defaults(func=_publish_clip_cli)

    bc = s.add_parser("bench", help="emit the Play bench step for a PUBLISHED clip (hip drop, slide, head over sole)")
    bc.add_argument("--manifest", required=True)
    bc.add_argument("--clip", required=True, choices=sorted(clipsources.CATALOG))
    bc.add_argument("--speed", type=float, default=None, help="playback speed; default 1")
    bc.add_argument("--max-wait", type=int, default=25, help="seconds the bridge call may block")
    bc.set_defaults(func=_bench_cli)

    c = s.add_parser("impact"); c.add_argument("--manifest", required=True)
    c.add_argument("--clip", required=True, choices=sorted(clipsources.CATALOG))
    c.set_defaults(func=_impact_cli)

    d = s.add_parser("speed-scale"); d.add_argument("--manifest", required=True)
    d.set_defaults(func=_speed_scale_cli)

    e = s.add_parser("fetch"); e.add_argument("--manifest", required=True)
    e.add_argument("--ids", required=True, help="comma-separated Meshy library animation ids")
    e.set_defaults(func=_fetch_cli)

    f = s.add_parser("bind"); f.add_argument("--manifest", required=True)
    f.add_argument("--ids", required=True, nargs="+", help="Clip=RobloxAssetId pairs, space-separated")
    f.add_argument("--version", type=int, default=1)
    f.add_argument("--name", default=None, help="see `clips build --name`")
    f.set_defaults(func=_bind_cli)

    g = s.add_parser("registered", help="record the finalized Genvid media id for a clip bind() wrote payloads for")
    g.add_argument("--manifest", required=True)
    g.add_argument("--clip", required=True, choices=sorted(clipsources.CATALOG))
    g.add_argument("--media-id", required=True, help="the Genvid media id finalize_media_registration returned")
    g.set_defaults(func=_registered_cli)
