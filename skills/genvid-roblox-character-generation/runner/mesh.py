"""Stage 2: the mesh. The caller turns the bound plate into a 3D model with an
image-to-3D model of its own choosing; the runner converts it to GLB if needed,
decimates it, turns it to face the way the plate does, and binds it.

    mesh emit model    -> request citing the plate's front, left, back and right
                          (a static manifest: the front only)
    mesh ingest model <file-or-url>
                       -> records the result (GLB, binary FBX or OBJ), then preps
                          and binds it in the same invocation
    mesh prep          -> re-runs conversion, decimate and facing on the record
    mesh bind          -> re-runs the bind (after a ClaimPending or --record-only)

The runner calls no provider and names no model; the bind attests the provider,
model, params and cost the caller reported at ingest (request.py). Conversion,
decimate and facing all run in Blender, which prep needs whatever the format.
"""
import json, shutil, subprocess, sys
from pathlib import Path
import manifest, genvid_bind, request, budget

STEP = ITEM = "model"
BUDGET_KEY = "mesh"
MODEL_TYPE = "image-to-3D"
RENDER_TYPE = "I23D"
# The order the views are listed in the request (and cited by the bind).
VIEW_ORDER = ("front", "left", "back", "right")
TRI_CAP = 20000
MODEL_KINDS = ("glb", "fbx", "obj")
MODEL_EXT = {"glb": ".glb", "fbx": ".fbx", "obj": ".obj"}
RESULT_STEM = "mesh.result"
# Blender's FBX importer reads binary FBX 7.1 (7100) and later only.
FBX_MIN_VERSION = 7100
HERE = Path(__file__).parent

NO_TEXTURE = ("an OBJ arrives without its textures (its .mtl and images are separate files), so the mesh binds "
              "with no base color and eval row E5 (base-color texture present) fails: deliver GLB, or FBX with "
              "its textures embedded")
TARGET = {
    "format": list(MODEL_KINDS), "preferred": "glb", "fallbacks": ["fbx", "obj"], "triangles_max": TRI_CAP,
    "notes": "Deliver GLB: it carries its textures. FBX and OBJ are accepted as a fallback and converted to "
             "GLB. FBX must be binary, version 7.1 or later, with its textures embedded. " + NO_TEXTURE[0].upper()
             + NO_TEXTURE[1:] + ".",
}
CHECKED_AT_INGEST = ["model type by content: GLB, binary FBX (7.1 or later) or OBJ",
                     "a request was emitted (the budget check ran), unless --unrequested",
                     "at most %d triangles after prep's decimate (prep refuses otherwise)" % TRI_CAP]
NO_BLENDER = ("mesh ingest needs Blender on PATH: prep decimates and turns the mesh in it, and converts an "
              "FBX or OBJ to GLB. Install Blender, or pass --record-only to record the result now and run "
              "`mesh prep` then `mesh bind` where Blender is installed.")
OLD_SHAPE = ("stages.mesh has no generated.model: this mesh came from the old generator, whose "
             "attestation this bind no longer sends. Record it first with `mesh ingest model "
             "--unrequested \"<reason>\" --provider <p> --model <m> --cost <c>|--cost-unobserved <file>` "
             "(the raw mesh file, e.g. mesh.raw.glb), adding --supersede when the stage already has a "
             "media_id; that ingest preps and binds it.")


def _st(m):
    return m["stages"].get("mesh") or {}


def _static(m):
    return m.get("kind") == "static"


def _roles(m):
    """`[(role, media_id)]` the request cites: the front and the three views, or
    the front alone on a static manifest. Refuses an unbound view by name."""
    ids = (m["stages"].get("plate") or {}).get("media_ids") or {}
    roles = ("front",) if _static(m) else VIEW_ORDER
    missing = [r for r in roles if not ids.get(r)]
    if missing:
        raise request.IngestError("no bound plate %s: the image-to-3D request cites the front and all three "
                                  "views, so bind them with `plate ingest views` first" % ", ".join(missing))
    return [(r, str(ids[r])) for r in roles]


def _prompt(m):
    if _static(m):
        return ("A textured 3D model of the subject in the front image: the same shape, colors, materials and "
                "proportions, as one object.")
    return ("A textured 3D model of the character shown in the four views (front, left, back, right): the same "
            "design, colors, materials and proportions, in the same symmetric A-pose.")


def _must_satisfy(m):
    rules = ["a single textured model of the subject in the input image(s), base color included",
             "delivered as GLB (preferred) or FBX; " + NO_TEXTURE,
             "about %d triangles or fewer (prep decimates anything over, which loses detail)" % TRI_CAP]
    if not _static(m):
        rules += ["the plate's pose: symmetric A-pose, arms clear of the torso, legs apart",
                  "humanoid biped proportions: the mesh is rigged after this"]
    return rules


def _blender(blender=None):
    path = blender or shutil.which("blender")
    if not path:
        raise RuntimeError(NO_BLENDER)
    return path


# ---------------------------------------------------------------- emit

def emit_model(m, estimate, model=None, no_urls=False, run=subprocess.run):
    """Write the image-to-3D request and return its path. The plate must be
    bound: the front on a static manifest, the front and all three views on a
    character."""
    manifest.require_stage(m, "mesh")
    roles = _roles(m)
    entry = budget.gate(m, BUDGET_KEY, estimate, model=model, items=[ITEM])
    ins = request.inputs(m, roles, no_urls=no_urls, run=run)
    return request.write_request(
        m, "mesh", STEP, None, model_type=MODEL_TYPE, render_type=RENDER_TYPE, prompt=_prompt(m), inputs=ins,
        target=TARGET, must_satisfy=_must_satisfy(m), checked_at_ingest=CHECKED_AT_INGEST, budget_entry=entry,
        ingest=request.ingest_command(m, "mesh", STEP))


# ---------------------------------------------------------------- ingest

def _check_model_kind(path):
    with open(path, "rb") as f:
        head = f.read(64)
    if head.lstrip().startswith(b"; FBX"):
        raise request.IngestError("%s is an ASCII FBX, which Blender cannot import: export binary FBX (7.1 or "
                                  "later), GLB or OBJ" % path)
    kind = request.check_kind(path, MODEL_KINDS)
    if kind == "fbx":
        version = int.from_bytes(head[23:27], "little") if len(head) >= 27 else 0
        if version < FBX_MIN_VERSION:
            raise request.IngestError("%s is FBX %d, older than Blender imports: export binary FBX 7.1 or "
                                      "later, or GLB" % (path, version))
    return kind


def _bind_preconditions(m):
    if not m.get("asset_id"):
        raise ValueError("no asset_id on the manifest: the mesh binds onto the plate's asset")
    genvid_bind.require_assignee(m)


def ingest_model(m, result, att, *, prompt=None, render_type=None, input_media_ids=(), record_only=False,
                 supersede=False, unrequested=None, opener=None, blender=None, run=subprocess.run):
    """Record the caller's model, then prep and bind it; returns the media id
    (None with `record_only`). Everything that can refuse runs before the record."""
    manifest.require_stage(m, "mesh")
    if not record_only:
        _bind_preconditions(m)
        blender = _blender(blender)
    req_path = request.require_request(m, "mesh", STEP, None, unrequested)
    req = json.loads(Path(req_path).read_text()) if req_path else {}

    def make(path, url, kind):
        ids = [str(i) for i in input_media_ids] or [i["media_id"] for i in req.get("inputs") or []] \
            or [mid for _r, mid in _roles(m)]
        rec = request.make_record(
            artifact=path, source_url=url, attestation=att, prompt=prompt if prompt is not None else (req.get("prompt") or _prompt(m)),
            render_type=render_type or req.get("render_type") or RENDER_TYPE, input_media_ids=ids,
            request_path=req_path, vendor_hint=m.get("vendor"))
        # prep reads the kind from the record rather than sniffing the file again.
        rec["kind"] = kind
        return rec

    outcome = request.record_result(m, "mesh", ITEM, result, make, stem=RESULT_STEM, ext=MODEL_EXT,
                                    check=_check_model_kind, bound_media_id=_st(m).get("media_id"),
                                    supersede=supersede, opener=opener)
    if record_only:
        return None
    bound = _st(m).get("media_id")
    if outcome == "unchanged" and bound:
        return bound
    prep(m, blender=blender)
    return bind(m, run=run, supersede=supersede)


# ---------------------------------------------------------------- prep

def _to_glb(m, rec, raw, blender):
    """The recorded result as a GLB for decimate to read, and what a conversion
    reported (None for a GLB). A GLB this runner downloaded is read where it is;
    a caller's local GLB is copied to `raw`; an FBX or OBJ is converted to `raw`
    in Blender."""
    src = Path(rec["artifact"])
    kind = rec["kind"]
    if kind == "glb":
        if src == Path(m["out_dir"]) / (RESULT_STEM + MODEL_EXT["glb"]):
            return src, None
        shutil.copyfile(src, raw)
        return raw, None
    script = HERE / "blender" / "to_glb.py"
    r = subprocess.run([blender, "--background", "--python", str(script), "--", str(src), kind, str(raw)],
                       capture_output=True, text=True, check=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith("RUNNER_RESULT ")]
    if not lines:
        raise RuntimeError("to_glb.py printed no result: %s" % (r.stdout[-2000:] or r.stderr[-2000:]))
    rep = dict(json.loads(lines[-1][len("RUNNER_RESULT "):]), sha256=rec["sha256"])
    if not rep.get("has_basecolor"):
        rep["warning"] = ("the converted %s has no base-color texture, so eval row E5 (base-color texture "
                          "present) will fail%s: deliver GLB, or FBX with its textures embedded"
                          % (kind, " (an OBJ's .mtl and images are separate files and do not come with it)"
                             if kind == "obj" else ""))
        print("WARNING: mesh prep: " + rep["warning"], file=sys.stderr)
        manifest.note(m, "mesh prep: " + rep["warning"])
    return raw, rep


def facing(m, cooked, blender=None, plate=None):
    """Turn the cooked mesh so it faces the way the approved plate does, and
    record the turn at `stages.mesh.facing_yaw_deg`.

    Witnessed 2026-09-04 (bake-off leg B): Tripo H3.1 meshes face +/-X while the
    auto-rig that rigs them assumes -Y, and rigging an unrotated one put both
    shoulders 12 cm apart inside the torso. The turn has to happen BEFORE the rig
    call, which is why it lives in prep and not in a later stage.
    blender/facing.py picks the quarter turn by silhouette IoU against the plate
    and settles front-vs-back on head-region color; it rewrites `cooked` in place
    (it loads the file fully before exporting over it).
    """
    front = plate or (m["stages"].get("plate", {}).get("view_paths") or {}).get("front")
    if not front or not Path(front).exists():
        # Refused, not skipped: a mesh bound unturned is rigged unturned.
        raise ValueError("mesh prep: no front plate image on the manifest (%s), so the mesh cannot be turned to "
                         "face the way the plate does, and rigging it unturned puts the shoulders inside the "
                         "torso; run `plate select-front --media-id <front>` to fetch it, then `mesh prep`"
                         % (front or "stages.plate.view_paths.front is unset"))
    out = Path(m["out_dir"])
    script = HERE / "blender" / "facing.py"
    # --python-exit-code 1: Blender exits 0 when a --python script raises.
    r = subprocess.run([_blender(blender), "--background", "--python-exit-code", "1", "--python", str(script), "--",
                        str(cooked), str(front), str(out / "facing.json"), str(cooked)],
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError("facing.py failed, so the mesh was not turned: %s" % (r.stderr or r.stdout)[-2000:])
    lines = [l for l in r.stdout.splitlines() if l.startswith("RUNNER_RESULT ")]
    if not lines:
        raise RuntimeError("facing.py printed no result: %s" % (r.stderr[-2000:] or r.stdout[-2000:]))
    rep = json.loads(lines[-1][len("RUNNER_RESULT "):])
    manifest.set_stage(m, "mesh", facing_yaw_deg=rep["yaw_deg"], facing=rep)
    manifest.save(m)
    return rep


def prep(m, blender=None, plate=None):
    """Convert the recorded result to `mesh.raw.glb` if it is not GLB, decimate
    it to `mesh.20k.glb`, and turn it to face the way the plate does."""
    out = Path(m["out_dir"]); raw = out / "mesh.raw.glb"; cooked = out / "mesh.20k.glb"
    rec = (_st(m).get("generated") or {}).get(ITEM)
    if not rec and not raw.exists():
        raise ValueError("no mesh recorded: run `mesh ingest model` with the caller's result first")
    blender = _blender(blender)
    if rec:
        raw, converted = _to_glb(m, rec, raw, blender)
        manifest.set_stage(m, "mesh", artifact_raw=str(raw), converted_from=converted); manifest.save(m)
    script = HERE / "blender" / "decimate_check.py"
    r = subprocess.run([blender, "--background", "--python", str(script), "--",
                        str(raw), str(cooked), str(TRI_CAP)], capture_output=True, text=True, check=True)
    rep = json.loads([l for l in r.stdout.splitlines() if l.startswith("{")][-1])
    (out / "mesh.report.json").write_text(json.dumps(rep, indent=2))
    if rep["tris_out"] > TRI_CAP:
        raise RuntimeError("mesh still over cap: %s" % rep)
    if not rep["genus0"]:
        manifest.note(m, "mesh is not genus-0: %s (allowed for skinned rigs; recorded)" % rep)
    entry = manifest.set_stage(m, "mesh", artifact=str(cooked), report=rep)
    # A turn recorded for an earlier cooked mesh does not describe this one.
    entry.pop("facing_yaw_deg", None); entry.pop("facing", None)
    manifest.save(m)
    facing(m, cooked, blender=blender, plate=plate)
    return rep


# ---------------------------------------------------------------- bind

def bind(m, run=subprocess.run, supersede=False):
    """Bind the prepped mesh. A stage already bound is not bound again for the
    same prepped bytes; different bytes (a re-run prep, e.g. the facing turn)
    need `supersede`, which binds a new row naming the one it supersedes."""
    st = _st(m)
    rec = (st.get("generated") or {}).get(ITEM)
    if not rec:
        raise ValueError(OLD_SHAPE)
    if not st.get("artifact") or "report" not in st:
        raise ValueError("no prepped mesh on the manifest: run `mesh prep` before `mesh bind`")
    if st.get("facing_yaw_deg") is None:
        # prep records the artifact before the turn, so a refused turn leaves one behind.
        raise ValueError("the prepped mesh was never turned to face the plate (stages.mesh.facing_yaw_deg is "
                         "unset): run `plate select-front --media-id <front>` and `mesh prep` before `mesh bind`")
    bound = st.get("media_id")
    sha = request.sha256_of(st["artifact"])
    same = st.get("bound_sha256") == sha and st.get("bound_source_sha256") == rec.get("sha256")
    if bound and same:
        manifest.note(m, "mesh bind: these prepped bytes are already bound as media %s; nothing changed" % bound)
        manifest.save(m)
        return bound
    if bound and not supersede:
        if not st.get("bound_sha256"):
            raise request.IngestError("the mesh is already bound as media %s, bound before its bytes were recorded, "
                                      "so a change cannot be told from none: pass --supersede only if you re-ran "
                                      "`mesh prep` or ingested a new result since" % bound)
        raise request.IngestError("the mesh is already bound as media %s and the prepped bytes differ: pass "
                                  "--supersede to bind them as a new row that supersedes it" % bound)
    # A media-bind-only site: the asset already exists (the plate created it), so
    # nothing upstream re-checks its claim before this governed write runs.
    genvid_bind.ensure_claim(m, m["asset_id"], "mesh")
    # The bound artifact is the converted, decimated and turned mesh, so what the
    # runner did to it belongs in the signed params.
    runner = {"stage": "mesh", "report": st["report"], "facing_yaw_deg": st.get("facing_yaw_deg"),
              "converted_from": st.get("converted_from")}
    # No target/stage: the unrigged mesh has no Roblox destination, and the boundary
    # refuses target="roblox" + stage="roblox/mesh" ("not a known destination and
    # pipeline stage", 2026-09-23). The rig row carries roblox/r15-rigged.
    kw = request.bind_kwargs(rec, runner=runner, artifact=st["artifact"])
    if bound:
        kw["params"]["supersedes_media_id"] = str(bound)
    mid = genvid_bind.import_media(m["project_id"], link_type=genvid_bind.MODEL_LINK, asset_id=m["asset_id"],
                                   run=run, **kw)
    entry = manifest.set_stage(m, "mesh", media_id=mid, bound_sha256=sha, bound_source_sha256=rec.get("sha256"))
    if bound:
        entry["superseded_media_ids"] = list(entry.get("superseded_media_ids") or []) + [str(bound)]
        manifest.note(m, "mesh bind: media %s supersedes %s" % (mid, bound))
    manifest.save(m)
    return mid


# ---------------------------------------------------------------- CLI

def register(sub):
    p = sub.add_parser("mesh"); s = p.add_subparsers(dest="cmd", required=True)
    e = s.add_parser("emit", help="write the image-to-3D request for the caller's own model")
    es = e.add_subparsers(dest="step", required=True)
    em = es.add_parser("model", help="the model, from the bound plate; asks for GLB (FBX or OBJ as a fallback)")
    request.add_emit_args(em, item_help="not used: the mesh is one item")
    em.set_defaults(func=_emit_model)
    i = s.add_parser("ingest", help="record the caller's model, then prep and bind it")
    ist = i.add_subparsers(dest="step", required=True)
    im = ist.add_parser("model", help="the model as a local file or a URL: GLB preferred; binary FBX or OBJ "
                                      "accepted and converted (an OBJ has no textures, so E5 fails)")
    request.add_ingest_args(im, item_help="not used: the mesh is one item")
    im.set_defaults(func=_ingest_model)
    a = s.add_parser("prep", help="re-run conversion, decimate and facing on the recorded model")
    a.add_argument("--manifest", required=True)
    a.set_defaults(func=lambda x: _done(prep(manifest.load(x.manifest))))
    b = s.add_parser("bind", help="re-run the bind of the prepped mesh")
    b.add_argument("--manifest", required=True)
    b.add_argument("--supersede", action="store_true",
                   help="bind re-prepped bytes for a mesh that is already bound, as a new row that supersedes it")
    b.set_defaults(func=lambda x: _done(bind(manifest.load(x.manifest), supersede=x.supersede)))


def _done(_result):
    """CLI commands return an exit code, never the value."""
    return None


def _no_item(x):
    if x.item:
        raise SystemExit("mesh %s model takes no --item: the mesh is one item" % x.cmd)


def _emit_model(x):
    _no_item(x)
    print(emit_model(manifest.load(x.manifest), x.estimate, model=x.model, no_urls=x.no_urls))


def _ingest_model(x):
    _no_item(x)
    ingest_model(manifest.load(x.manifest), x.result, request.attestation_from_args(x), prompt=x.prompt,
                 render_type=x.render_type, input_media_ids=x.input_media_id, record_only=x.record_only,
                 supersede=x.supersede, unrequested=x.unrequested)
