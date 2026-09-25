"""Stage 3: the rig. The caller rigs the bound mesh with a rigging model of its
own choosing; the runner converts the rig to the 15-bone R15 skeleton and binds it.

    rig emit model     -> request citing the bound mesh, with optional library
                          clips named by label and description
    rig ingest model --rig <file-or-url> [--clip label=<file-or-url> ...]
                       -> records the rig, writes each clip to
                          <out>/clips/<label>.glb (stages.rig.clip_files), then
                          converts to R15 and binds in the same invocation
    rig r15            -> re-runs the conversion on the recorded rig
    rig bind           -> re-runs the bind (after a ClaimPending or --record-only)
    rig ingest surface-texture
                       -> records and binds a generated texture for the surface
                          pass (ingest-only: always --unrequested)

The runner calls no provider and names no model; the bind attests the provider,
model, params and cost the caller reported at ingest (request.py). The bundled
clips' files and `stages.rig.clip_files` are the contract the clips stage reads.
Each bundled clip is also bound as its own motion row citing the rig
(`stages.rig.clip_media_ids`); the rig's row carries the spend, so the clip rows
attest no cost.
"""
import json, re, shutil, subprocess
from pathlib import Path
import manifest, genvid_bind, request, budget, cost, mesh

STEP = ITEM = "model"
BUDGET_KEY = "rig"
MODEL_TYPE = "rigging"
RENDER_TYPE = "RIG"
RIG_KINDS = ("glb", "fbx")
RIG_EXT = {"glb": ".glb", "fbx": ".fbx"}
RESULT_STEM = "rig.raw"
CLIP_LABEL = re.compile(r"^[A-Za-z0-9_-]+$")
DERIVED_FROM = ("mesh", "plate")
TEXTURE_STEP = TEXTURE_ITEM = "surface-texture"
TEXTURE_STEM = "surface.texture"
TEXTURE_EXT = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}
# The runner's own processing, attested on the surface-pass row.
CONVERTER_PROVIDER, CONVERTER_MODEL = "blender", "rig_r15"

TARGET = {"format": list(RIG_KINDS), "preferred": "glb",
          "notes": "A skinned rig of the input mesh, GLB or binary FBX (7.1 or later) with its textures embedded. "
                   "Library clips, when requested, come back as one GLB per label on this rig's skeleton."}
MUST_SATISFY = [("a humanoid biped skeleton whose bones map to the R15 layout (Mixamo-style naming or any spelling "
                 "the runner's bone tables normalize)"),
                "skin weights on the mesh; every vertex weighted",
                "the rig survives conversion to the 16-bone R15 skeleton (the conversion refuses otherwise)",
                "the input mesh's pose and facing: it is already decimated and turned to face the plate"]
CHECKED_AT_INGEST = ["rig type by content: GLB or binary FBX (7.1 or later)",
                     "each clip is GLB and its label matches %s" % CLIP_LABEL.pattern,
                     "a request was emitted (the budget check ran), unless --unrequested",
                     "the R15 conversion keeps 16 bones (it refuses otherwise)"]
NO_BLENDER = ("rig ingest needs Blender on PATH: the R15 conversion runs in it. Install Blender, or pass "
              "--record-only to record the result now and run `rig r15` then `rig bind` where Blender is installed.")
OLD_SHAPE = ("stages.rig has no generated.model: this rig came from the old generator, whose attestation this "
             "bind no longer sends. Record it first with `rig ingest model --unrequested \"<reason>\" "
             "--provider <p> --model <m> --cost <c>|--cost-unobserved --rig <file>` (the raw rig file, e.g. "
             "rig.raw.glb), adding --supersede when the stage already has a media_id; that ingest converts "
             "and binds it.")


def _st(m):
    return m["stages"].get("rig") or {}


def _clip_specs(clips):
    """`[{"label", "description"}]` from `label:description` strings."""
    out = []
    for c in clips or ():
        label, sep, desc = str(c).partition(":")
        label = label.strip()
        if not sep or not desc.strip():
            raise request.IngestError("--clip %r: give label:description" % c)
        _check_label(label)
        out.append({"label": label, "description": desc.strip()})
    return out


def _check_label(label):
    if not CLIP_LABEL.match(label or ""):
        raise request.IngestError("clip label %r must match %s: it becomes the clip's file name"
                                  % (label, CLIP_LABEL.pattern))
    return label


# ---------------------------------------------------------------- emit

def emit_model(m, estimate, model=None, clips=(), no_urls=False, run=subprocess.run):
    """Write the rigging request and return its path. The mesh must be bound:
    the request cites it, and the rig is made from that processed artifact."""
    manifest.require_stage(m, "rig")
    mesh_id = (m["stages"].get("mesh") or {}).get("media_id")
    if not mesh_id:
        raise request.IngestError("no bound mesh: run `mesh ingest model` first")
    specs = _clip_specs(clips)
    entry = budget.gate(m, BUDGET_KEY, estimate, model=model, items=[ITEM] + sorted(c["label"] for c in specs))
    ins = request.inputs(m, [("mesh", str(mesh_id))], no_urls=no_urls, run=run)
    must = list(MUST_SATISFY)
    if specs:
        must.append("each requested clip as its own GLB, authored on this rig's skeleton, passed as "
                    "--clip <label>=<file>; a response that returns several clips may return them in any "
                    "order, so map each clip by its identifier")
    ingest = request.ingest_command(m, "rig", STEP).replace("<file-or-url>", "--rig <file-or-url>" + (
        " --clip <label>=<file-or-url> ..." if specs else ""))
    return request.write_request(
        m, "rig", STEP, None, model_type=MODEL_TYPE, render_type=RENDER_TYPE,
        prompt="Rig this character mesh as a humanoid biped with skin weights.", inputs=ins, target=TARGET,
        must_satisfy=must, checked_at_ingest=CHECKED_AT_INGEST, budget_entry=entry, ingest=ingest,
        extra={"clips": specs})


# ---------------------------------------------------------------- ingest

def _blender(blender=None):
    path = blender or shutil.which("blender")
    if not path:
        raise RuntimeError(NO_BLENDER)
    return path


def _check_rig_kind(path):
    """The rig's kind, GLB or binary FBX 7.1 or later. The kind and ASCII checks
    are worded here from RIG_KINDS; mesh's check then only adds the FBX version."""
    with open(path, "rb") as f:
        head = f.read(64)
    if head.lstrip().startswith(b"; FBX"):
        raise request.IngestError("%s is an ASCII FBX, which Blender cannot import: export the rig as GLB or "
                                  "binary FBX (7.1 or later)" % path)
    request.check_kind(path, RIG_KINDS)
    return mesh._check_model_kind(path)


def _parse_clip_args(clips):
    """`{label: file-or-url}` from `label=<file-or-url>` strings."""
    out = {}
    for c in clips or ():
        label, sep, src = str(c).partition("=")
        if not sep or not src.strip():
            raise request.IngestError("--clip %r: give label=<file-or-url>" % c)
        out[_check_label(label.strip())] = src.strip()
    return out


def _derived_inputs(m, derived_from):
    if derived_from not in DERIVED_FROM:
        raise request.IngestError("--derived-from must be one of %s" % ", ".join(DERIVED_FROM))
    if derived_from == "plate":
        ids = (m["stages"].get("plate") or {}).get("media_ids") or {}
        missing = [r for r in mesh.VIEW_ORDER if not ids.get(r)]
        if missing:
            raise request.IngestError("--derived-from plate: no bound plate %s" % ", ".join(missing))
        return [str(ids[r]) for r in mesh.VIEW_ORDER]
    mid = (m["stages"].get("mesh") or {}).get("media_id")
    if not mid:
        raise request.IngestError("no bound mesh to derive the rig from: pass --derived-from plate or "
                                  "--input-media-id")
    return [str(mid)]


def _write_clips(m, clip_srcs, requested, opener=None, supersede=False):
    """Write each clip to `<out>/clips/<label>.glb` and record `stages.rig.clip_files`.

    Every clip is resolved and checked before any is written. A clip already
    bound (`stages.rig.clip_media_ids`) with different bytes is refused unless
    `supersede`, so the file on disk never runs ahead of its bound row."""
    if not clip_srcs:
        return {}
    out = Path(m["out_dir"]) / "clips"
    out.mkdir(parents=True, exist_ok=True)
    files = dict(_st(m).get("clip_files") or {})
    bound = _st(m).get("clip_media_ids") or {}
    shas = _st(m).get("clip_sha256") or {}
    staged = []
    try:
        for label, src in sorted(clip_srcs.items()):
            path, url = request.resolve_result(src, out / (label + ".download"), opener=opener)
            staged.append((label, path, url))
            request.check_kind(path, ("glb",))
            if label in bound and shas.get(label) != request.sha256_of(path) and not supersede:
                raise request.IngestError("bundled clip %s is already bound as media %s with different bytes: pass "
                                          "--supersede to bind the new clip as a new row" % (label, bound[label]))
    except Exception:
        for _label, path, url in staged:
            if url:
                path.unlink(missing_ok=True)
        raise
    for label, path, url in staged:
        dest = out / (label + ".glb")
        if url:
            path.replace(dest)
        elif Path(path).resolve() != dest.resolve():
            shutil.copyfile(path, dest)
        if requested is not None and label not in requested:
            manifest.note(m, "rig ingest: clip %r was not in the emitted request; recorded anyway" % label)
        if label in files:
            manifest.note(m, "rig ingest: clip %r rewritten at %s" % (label, dest))
        files[label] = str(dest)
    manifest.set_stage(m, "rig", clip_files=files)
    manifest.save(m)
    return files


def ingest_model(m, rig_result, att, *, clips=(), derived_from="mesh", prompt=None, render_type=None,
                 input_media_ids=(), record_only=False, supersede=False, unrequested=None, opener=None,
                 blender=None, run=subprocess.run):
    """Record the caller's rig and write its clips, then convert and bind it;
    returns the media id (None with `record_only`). The rig's own checks and the
    clip labels run before the record; a clip whose bytes are refused (not GLB)
    leaves the rig recorded, and a re-run with the right clip picks up from there."""
    manifest.require_stage(m, "rig")
    if not rig_result:
        raise request.IngestError("--rig is required: the rig file or URL")
    clip_srcs = _parse_clip_args(clips)
    if not record_only:
        mesh._bind_preconditions(m)
        blender = _blender(blender)
    req_path = request.require_request(m, "rig", STEP, None, unrequested)
    req = json.loads(Path(req_path).read_text()) if req_path else {}
    ids = [str(i) for i in input_media_ids] or _derived_inputs(m, derived_from)

    def make(path, url, kind):
        rec = request.make_record(
            artifact=path, source_url=url, attestation=att,
            prompt=prompt if prompt is not None else (req.get("prompt") or ""), render_type=render_type or req.get("render_type") or RENDER_TYPE,
            input_media_ids=ids, request_path=req_path, vendor_hint=m.get("vendor"))
        rec["kind"] = kind
        rec["derived_from"] = "explicit" if input_media_ids else derived_from
        return rec

    outcome = request.record_result(m, "rig", ITEM, rig_result, make, stem=RESULT_STEM, ext=RIG_EXT,
                                    check=_check_rig_kind, bound_media_id=_st(m).get("media_id"),
                                    supersede=supersede, opener=opener)
    rec = _st(m)["generated"][ITEM]
    raw = Path(rec["artifact"])
    dest = Path(m["out_dir"]) / (RESULT_STEM + RIG_EXT[rec["kind"]])
    if raw.resolve() != dest.resolve():
        # A caller's local file is copied in, so a later `rig r15` or surface pass
        # still finds it when the original is gone.
        shutil.copyfile(raw, dest)
    manifest.set_stage(m, "rig", artifact_raw=str(dest)); manifest.save(m)
    requested = {c["label"] for c in req.get("clips") or []} if req_path else None
    _write_clips(m, clip_srcs, requested, opener=opener, supersede=supersede)
    if record_only:
        return None
    bound = _st(m).get("media_id")
    if outcome == "unchanged" and bound:
        bind_clips(m, supersede=supersede, run=run)
        return bound
    r15(m, blender=blender)
    return bind(m, run=run, supersede=supersede)


def ingest_surface_texture(m, result, att, *, unrequested, prompt=None, render_type=None, input_media_ids=(),
                           record_only=False, supersede=False, opener=None, run=subprocess.run):
    """Record a generated texture for the surface pass at
    `stages.rig.generated.surface-texture` and bind it as its own image row
    (managed media, attested from the record; by source_url first, as a plate
    view is) at
    `stages.rig.surface_texture_media_id`; returns that media id (None with
    `record_only`, which records without binding). There is no
    emit for it, so it is always ingested with an `--unrequested` reason.
    `surface prep` reads the recorded file when `--texture` is omitted and cites
    the bound row unless `--texture-media-id` names another."""
    if not _st(m).get("artifact_raw"):
        raise request.IngestError("no rig on the manifest: the surface pass re-textures an existing rig")
    if unrequested is None or not str(unrequested).strip():
        raise request.IngestError("rig ingest surface-texture has no emit: pass --unrequested \"<reason>\"")
    if not record_only:
        mesh._bind_preconditions(m)
    request.require_request(m, "rig", TEXTURE_STEP, None, unrequested)
    ids = [str(i) for i in input_media_ids] or ([str(_st(m)["media_id"])] if _st(m).get("media_id") else [])

    def make(path, url, kind):
        return request.make_record(artifact=path, source_url=url, attestation=att, prompt=prompt or "",
                                   render_type=render_type or ("I2I" if ids else "T2I"), input_media_ids=ids,
                                   request_path=None, vendor_hint=m.get("vendor"))

    bound = _st(m).get("surface_texture_media_id")
    outcome = request.record_result(m, "rig", TEXTURE_ITEM, result, make, stem=TEXTURE_STEM, ext=TEXTURE_EXT,
                                    check=lambda p: request.check_kind(p, request.IMAGE_KINDS),
                                    bound_media_id=bound, supersede=supersede, opener=opener)
    if record_only:
        return None
    if outcome == "unchanged" and bound:
        return bound
    # The same claim site as the surface pass it feeds: both write to the rig's asset.
    genvid_bind.ensure_claim(m, m["asset_id"], "rig.surface")
    rec = _st(m)["generated"][TEXTURE_ITEM]
    # Bound as delivered, like a plate view: by the caller's source_url first, the
    # recorded file uploaded when the boundary refuses that host.
    mid = genvid_bind.import_media(
        m["project_id"], link_type="cast_member_image", asset_id=m["asset_id"], run=run,
        **request.bind_kwargs(rec, runner={"stage": "rig", "step": TEXTURE_STEP, "size_px": rec.get("size_px")}))
    manifest.set_stage(m, "rig", surface_texture_media_id=mid); manifest.save(m)
    return mid


def _convert_r15(out, raw, dst, texture, blender):
    """Shell the stage_f-port Blender script converting `raw` to a 15-bone R15
    skinned FBX at `dst`, optionally re-textured with `texture`. Shared by r15()
    (the rig stage) and surface_prep() (the R15 surface-pass re-bake, which
    writes to a different `dst` and never touches the rig stage's own
    artifact/report/media_id)."""
    script = Path(__file__).parent / "blender" / "rig_r15.py"
    # --python-exit-code 1: without it Blender exits 0 even when the script
    # raised, and a stale rig.report.json from a previous run would then read
    # as a successful conversion. The dst.exists() check below closes the same
    # hole for a report written before an exporter crash.
    argv = [blender or shutil.which("blender"), "--background", "--python-exit-code", "1",
            "--python", str(script), "--", raw, str(dst)]
    if texture: argv.append(texture)
    r = subprocess.run(argv, capture_output=True, text=True)
    # blender/rig_r15.py always writes Path(out_fbx).parent / "rig.report.json" --
    # it does not namespace the report by the fbx name -- so r15() and
    # surface_prep() (same `out` dir, different `dst`) both write and read THIS
    # SAME on-disk path. The read here is always fresh (right after this call's
    # own subprocess exits, before any other call could run), so neither r15()'s
    # nor surface_prep()'s in-memory `rep` -- and therefore neither manifest
    # write -- is ever stale. But without copying it out, a later call clobbers
    # the earlier call's on-disk report.json; the dst-namespaced copy below
    # keeps both reports inspectable on disk after both stages have run.
    rep_path = out / "rig.report.json"
    rep = json.loads(rep_path.read_text()) if rep_path.exists() else {"bones": [], "warnings": [r.stderr[-1000:]]}
    if r.returncode != 0 or len(rep["bones"]) != 16 or not dst.exists():
        raise RuntimeError("R15 conversion failed (rc=%s, fbx_written=%s): %s" % (r.returncode, dst.exists(), rep))
    if rep_path.exists():
        (dst.parent / (dst.name + ".report.json")).write_text(rep_path.read_text())
    return rep


def r15(m, texture=None, blender=None):
    out = Path(m["out_dir"]); raw = m["stages"]["rig"]["artifact_raw"]; dst = out / "rig.r15.fbx"
    rep = _convert_r15(out, raw, dst, texture, blender)
    # blender/rig_r15.py exports the same scene twice: the FBX the Roblox 3D
    # Importer takes, and a glTF-binary twin Genvid's roblox/r15-rigged
    # conformance profile can actually read. Record the twin only when it is on
    # disk, so a manifest built by an older conversion keeps its old shape.
    glb = dst.with_suffix(".glb")
    if glb.exists():
        manifest.set_stage(m, "rig", artifact_glb=str(glb))
    manifest.set_stage(m, "rig", artifact=str(dst), report=rep,
                       previews=[str(dst) + ".view0.png", str(dst) + ".view1.png"]); manifest.save(m)
    return rep


def bind_clips(m, supersede=False, run=subprocess.run):
    """Bind each bundled clip in `stages.rig.clip_files` as its own motion row
    (T2MOTION, managed media) citing the bound rig rows; returns
    `stages.rig.clip_media_ids`. The rig's row carries the spend, so a clip row
    attests no cost (both fields omitted, never "0") and names the rig in
    params.runner. A clip already bound with the same bytes is skipped;
    different bytes need `supersede`, checked for every clip before any write."""
    st = _st(m)
    files = st.get("clip_files") or {}
    if not files:
        return {}
    rec = (st.get("generated") or {}).get(ITEM) or {}
    if not st.get("media_id") or not rec:
        raise ValueError("no bound rig: bundled clips are bound after the rig they came with")
    ids = dict(st.get("clip_media_ids") or {})
    shas = dict(st.get("clip_sha256") or {})
    todo = []
    for label, path in sorted(files.items()):
        sha = request.sha256_of(path)
        if label in ids and shas.get(label) == sha:
            continue
        if label in ids and not supersede:
            raise request.IngestError("bundled clip %s is already bound as media %s with different bytes: pass "
                                      "--supersede to bind the new clip as a new row" % (label, ids[label]))
        todo.append((label, path, sha))
    if not todo:
        return ids
    req = json.loads(Path(rec["request"]).read_text()) if rec.get("request") else {}
    described = {c["label"]: c["description"] for c in req.get("clips") or []}
    rig_ids = [str(st["media_id"])] + ([str(st["glb_media_id"])] if st.get("glb_media_id") else [])
    # The same claim site as the rig row: both bind to the rig's asset in one ingest.
    genvid_bind.ensure_claim(m, m["asset_id"], "rig.bind")
    for label, path, sha in todo:
        runner = {"stage": "rig", "clip": label, "kind": "animation-clip", "cost_source": "rig",
                  "rig_media_id": str(st["media_id"])}
        params = {"runner": runner}
        if label in ids:
            params["supersedes_media_id"] = str(ids[label])
        mid = genvid_bind.import_media(
            m["project_id"], path=str(path), link_type=genvid_bind.MODEL_LINK, asset_id=m["asset_id"],
            model_provider=rec["model_provider"], model_name=rec["model_name"], render_type="T2MOTION",
            prompt=described.get(label) or "%s clip bundled with the rig" % label, params=params,
            input_media_ids=rig_ids, cost={"unobserved": True}, run=run)
        ids[label] = mid
        shas[label] = sha
        manifest.set_stage(m, "rig", clip_media_ids=dict(ids), clip_sha256=dict(shas)); manifest.save(m)
    return ids


def bind(m, run=subprocess.run, supersede=False):
    st = _st(m)
    rec = (st.get("generated") or {}).get(ITEM)
    if not rec:
        raise ValueError(OLD_SHAPE)
    if not st.get("artifact") or "report" not in st:
        raise ValueError("no converted rig on the manifest: run `rig r15` before `rig bind`")
    # Media-bind-only site, covers BOTH governed writes below (the FBX row
    # and, when there is one, its GLB twin) -- one claim check before either runs.
    genvid_bind.ensure_claim(m, m["asset_id"], "rig.bind")
    # The bound artifact is the R15 conversion of the caller's rig, so the
    # conversion is recorded under params.runner, never fused into model_name.
    runner = {"stage": "rig", "report": st["report"],
              "conversion": {"provider": CONVERTER_PROVIDER, "model": CONVERTER_MODEL, "to": "r15"},
              "derived_from": rec.get("derived_from")}
    kw = request.bind_kwargs(rec, runner=runner, artifact=st["artifact"])
    mid = genvid_bind.import_media(m["project_id"], link_type=genvid_bind.MODEL_LINK, asset_id=m["asset_id"],
                                   stage="roblox/r15-rigged", target="roblox", run=run, **kw)
    # Persist after EACH governed write, the same shape plate.bind() and
    # mesh.bind() use. Saving only after the last one means a failure on a later
    # write leaves the rig model row created in Genvid with no media_id on the
    # manifest: is_done() reads the stage as not-done and a re-run creates a
    # duplicate rig row with a duplicate cost attestation. The preview list is reset
    # here too, so a re-run after a partial bind cannot keep ids from an older row
    # that still had them.
    manifest.set_stage(m, "rig", media_id=mid, preview_media_ids=[]); manifest.save(m)
    # The GLB twin, when the conversion produced one: Genvid's roblox/r15-rigged
    # conformance profile reads gltf-binary only and fails an FBX at
    # container.format (witnessed 2026-09-04), so E26 has nothing to measure
    # without this row. It is the SAME conversion in another container, so it
    # cites the same derivation inputs as the FBX row -- not the FBX row itself,
    # which is a sibling export, not an ancestor -- and attests $0: the rig spend
    # is already attested once, above, and attesting it twice would overstate
    # project spend on the governed record.
    #
    # forward_axis / twin_rotation_deg: the profile's rig.forward-axis check is a
    # second, independent thing to get right -- three untouched twin media items,
    # witnessed 2026-09-04, measured +Z against a required
    # -Z while the SAME rigs' FBX read -Z after the Studio import; the FBX was
    # never wrong -- the two Blender exporters write identical raw coordinates
    # for one scene, so they do not disagree. The two CONSUMERS (the Roblox 3D
    # Importer vs. Genvid's roblox/r15-rigged profile) read that one scene's
    # handedness two different ways, and which side holds the convention is
    # not witnessed (see blender/rig_r15.py's GLB_TWIN_YAW_DEG comment).
    # blender/rig_r15.py now turns the twin's scene a half turn
    # about up before the glTF export (GLB_TWIN_YAW_DEG) and reads back whether
    # that turn actually landed on the armature, recording the result in
    # rig.report.json as glb_twin_yaw_deg -- 180 when it landed, 0 when an
    # object-level write was re-driven away by an imported action and the twin
    # still faces the way the FBX does. Read that flag here rather than
    # hardcoding "-Z": a manifest built before this fix, or a report where the
    # turn did not land, must not claim an axis the twin does not actually
    # carry. A turned twin passed the profile outright.
    if st.get("artifact_glb"):
        twin_yaw = st["report"].get("glb_twin_yaw_deg", 0)
        twin = dict(kw, path=st["artifact_glb"], cost=cost.no_vendor_call(),
                    params=dict(kw["params"], container="glb", forward_axis="-Z" if twin_yaw == 180 else "+Z",
                                twin_rotation_deg=twin_yaw,
                                note="same conversion as the FBX row; glTF-binary for the roblox/r15-rigged "
                                     "conformance profile; turned %d deg about up relative to the FBX" % twin_yaw))
        glb_mid = genvid_bind.import_media(m["project_id"], link_type=genvid_bind.MODEL_LINK, asset_id=m["asset_id"],
                                           stage="roblox/r15-rigged", target="roblox", run=run, **twin)
        manifest.set_stage(m, "rig", glb_media_id=glb_mid); manifest.save(m)
    # The two Blender workbench preview frames are NOT bound. What is witnessed
    # (2026-09-04) is only the outcome: the preview-render binds were the one
    # part of the bake-off's rig binds that did not land. The CAUSE was not
    # isolated. The run note at the time read it as render_type "image" being
    # outside the media vocabulary, and that reading is an assumption the same
    # morning's record argues against: other plates carrying
    # render_type "image" were bound through the MCP ingest_generated_media path
    # ($0.48 attested). Which says nothing certain about THIS path -- the
    # runner's own plate bind sites send "image" through
    # genvid_bind.import_media (the CLI), and no such row is witnessed landing
    # or failing on that value either way. Two paths that may validate
    # differently is exactly why the cause is not isolated, so no claim about
    # the vocabulary is made here or on the record.
    #
    # They stay unbound on their own merits: a local workbench render of an
    # artifact this runner has already bound is a look-check convenience, not a
    # governed generation, and it has no render type among the documented
    # generation modes (T2I, I2I, I23D, ...) that would describe it honestly.
    # The rig FBX and its GLB twin above are the governed rows, and the zoo
    # capture (`stages.wire.capture`) is the visual record that is actually reviewed. The frames
    # stay on the manifest as files so a reviewer can open them.
    manifest.set_stage(m, "rig", preview_media_ids=[], previews_unbound=list(st["previews"]))
    manifest.note(m, "rig bind: the %d workbench preview frame(s) are not bound -- a local "
                     "look-check render of an already-bound artifact is not a governed "
                     "generation and has no honest render type; the bake-off's preview binds "
                     "were rejected (witnessed 2026-09-04) with the cause not isolated. Files "
                     "at stages.rig.previews_unbound" % len(st["previews"]))
    manifest.save(m)
    bind_clips(m, supersede=supersede, run=run)
    return mid


def _is_recorded_texture(texture, recorded):
    """Whether `texture` is the file `rig ingest surface-texture` recorded: the
    same path, or the same bytes."""
    if not texture or not recorded.get("artifact"):
        return False
    p = Path(texture)
    if p.resolve() == Path(recorded["artifact"]).resolve():
        return True
    return p.is_file() and request.sha256_of(p) == recorded.get("sha256")


def surface_prep(m, texture=None, blender=None, run=subprocess.run, texture_media_id=None):
    """Surface pass: re-runs the R15 conversion on the EXISTING
    character's raw rig FBX (stages.rig.artifact_raw) with a new stylized texture,
    into rig.r15.surface.fbx -- a sibling of the primary rig.r15.fbx, never
    overwriting it -- then binds the result as `genvid_bind.MODEL_LINK`
    (`cast_member_model`), the same link type `mesh.bind`, `rig.bind` and
    `clips.bind` already use for a model artifact on a `cast_member` asset.
    It is `cast_member_model`, never `prop_model`: the pack rule is prefix =
    asset type, and `record.py`'s docstring documents the same link type for
    the corrections payload.

    The orchestrator produces the stylized texture PNG by running the retired
    stage_g_stylize.py (read-only, .venv/bin/python) on the existing texture +
    plate BEFORE calling this (orchestrator step, not run here). This is called
    on an ALREADY fully-built, already-recorded character -- it does not gate on
    manifest.require_stage, since "rig" is not a stage this function advances,
    only one it reads from.
    """
    # Media-bind-only site (a re-bake of an already-recorded character) -- check
    # the claim BEFORE the Blender conversion below, not just before the import,
    # so a pending claim doesn't cost a Blender run.
    recorded = (_st(m).get("generated") or {}).get(TEXTURE_ITEM) or {}
    texture = texture or recorded.get("artifact")
    # The bound texture row is cited only when it is the texture being baked; a
    # different --texture with no --texture-media-id cites the rig alone, as an
    # uncited texture always has.
    if not texture_media_id and _is_recorded_texture(texture, recorded):
        texture_media_id = _st(m).get("surface_texture_media_id")
    if not texture:
        raise ValueError("surface prep needs --texture, or a texture recorded by `rig ingest surface-texture`")
    genvid_bind.ensure_claim(m, m["asset_id"], "rig.surface")
    out = Path(m["out_dir"])
    rig_st = m["stages"]["rig"]
    raw = rig_st["artifact_raw"]
    dst = out / "rig.r15.surface.fbx"
    rep = _convert_r15(out, raw, dst, texture, blender)
    manifest.set_stage(m, "rig", surface_artifact=str(dst), surface_report=rep,
                       surface_previews=[str(dst) + ".view0.png", str(dst) + ".view1.png"])
    manifest.save(m)
    # The surface pass is the runner's own conversion: no model ran, so it
    # attests the converter and no cost, and cites the rig (and the texture,
    # when it is a bound media row) it was made from.
    inputs = [str(rig_st["media_id"])] + ([str(texture_media_id)] if texture_media_id else [])
    mid = genvid_bind.import_media(m["project_id"], path=str(dst), link_type=genvid_bind.MODEL_LINK,
        asset_id=m["asset_id"], model_provider=CONVERTER_PROVIDER, model_name=CONVERTER_MODEL,
        render_type=RENDER_TYPE, prompt="R15 skinned rig re-textured for the surface pass",
        params={"stage": "surface-pass", "report": rep, "texture": str(texture),
                "model_type": "r15-conversion"},
        input_media_ids=inputs, cost=cost.no_vendor_call(),
        stage="roblox/r15-rigged", target="roblox", run=run)
    manifest.set_stage(m, "rig", surface_media_id=mid); manifest.save(m)
    return mid


def register(sub):
    p = sub.add_parser("rig"); s = p.add_subparsers(dest="cmd", required=True)
    e = s.add_parser("emit", help="write the rigging request for the caller's own model")
    es = e.add_subparsers(dest="step", required=True)
    em = es.add_parser("model", help="the rig, from the bound mesh; optional library clips by label")
    request.add_emit_args(em, item_help="not used: the rig is one item")
    em.add_argument("--clip", action="append", default=[], metavar="LABEL:DESCRIPTION",
                    help="a library motion to request with the rig (repeatable); the label becomes the file name")
    em.set_defaults(func=_emit_model)
    i = s.add_parser("ingest", help="record the caller's rig, then convert and bind it")
    ist = i.add_subparsers(dest="step", required=True)
    im = ist.add_parser("model", help="the rig and its bundled clips, each a local file or a URL")
    request.add_ingest_args(im, item_help="not used: the rig is one item", positional=False)
    im.add_argument("--rig", required=True, help="the rig: GLB or binary FBX, a local file or an http(s) URL")
    im.add_argument("--clip", action="append", default=[], metavar="LABEL=FILE",
                    help="a bundled clip as GLB, written to <out>/clips/<label>.glb (repeatable)")
    im.add_argument("--derived-from", choices=DERIVED_FROM, default="mesh",
                    help="what the rig was made from: the bound mesh (default), or the plate views when the "
                         "provider re-meshed from them")
    im.set_defaults(func=_ingest_model)
    it = ist.add_parser(TEXTURE_STEP, help="a generated texture for the surface pass (always --unrequested)")
    request.add_ingest_args(it, item_help="not used")
    it.set_defaults(func=_ingest_texture)
    b = s.add_parser("r15"); b.add_argument("--manifest", required=True); b.add_argument("--texture")
    b.set_defaults(func=lambda x: r15(manifest.load(x.manifest), x.texture))
    c = s.add_parser("bind"); c.add_argument("--manifest", required=True)
    c.add_argument("--supersede", action="store_true",
                   help="bind new bytes for a bundled clip that is already bound, as a new row that supersedes it")
    c.set_defaults(func=lambda x: bind(manifest.load(x.manifest), supersede=x.supersede))

    # Second top-level group, registered here (not in cli.py's GROUPS) since this
    # module already owns the rig-conversion machinery the surface pass reuses.
    surf = sub.add_parser("surface"); ss = surf.add_subparsers(dest="cmd", required=True)
    sp = ss.add_parser("prep", help="re-bake an EXISTING character's rig with a new texture and bind it")
    sp.add_argument("--manifest", required=True)
    sp.add_argument("--texture", help="the texture PNG (default: the one `rig ingest surface-texture` recorded)")
    sp.add_argument("--texture-media-id", help="the texture's Genvid media id, cited as an input (default: the row "
                                                   "`rig ingest surface-texture` bound)")
    sp.set_defaults(func=_surface_prep_cli)

    # adopt / adopt-emit: a rig that already exists in Studio gets a manifest
    # whose chain starts at rest (adopt.py); the verbs live here because the
    # orchestrator thinks of it as a rig operation, not a new group.
    import adopt
    adopt.register(s)


def _surface_prep_cli(args):
    surface_prep(manifest.load(args.manifest), args.texture, texture_media_id=args.texture_media_id)


def _no_item(x):
    if x.item:
        raise SystemExit("rig %s %s takes no --item" % (x.cmd, x.step))


def _emit_model(x):
    _no_item(x)
    print(emit_model(manifest.load(x.manifest), x.estimate, model=x.model, clips=x.clip, no_urls=x.no_urls))


def _ingest_model(x):
    _no_item(x)
    ingest_model(manifest.load(x.manifest), x.rig, request.attestation_from_args(x), clips=x.clip,
                 derived_from=x.derived_from, prompt=x.prompt, render_type=x.render_type,
                 input_media_ids=x.input_media_id, record_only=x.record_only, supersede=x.supersede,
                 unrequested=x.unrequested)


def _ingest_texture(x):
    _no_item(x)
    m = manifest.load(x.manifest)
    ingest_surface_texture(m, x.result, request.attestation_from_args(x), unrequested=x.unrequested,
                           prompt=x.prompt, render_type=x.render_type, input_media_ids=x.input_media_id,
                           record_only=x.record_only, supersede=x.supersede)
    print(_st(m)["generated"][TEXTURE_ITEM]["artifact"])
