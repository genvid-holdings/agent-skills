"""Stage 2: sheet -> vendor image-to-3D -> decimate/check -> bind."""
import json, shutil, subprocess
from pathlib import Path
import manifest, genvid_bind, plate
from vendors import fal, meshy, tripo, pricing

def gen(m, t, poll_secs=15):
    manifest.require_stage(m, "mesh")
    endpoint = meshy.MESH if m["vendor"] == "meshy" else tripo.MESH
    plate.budget_gate(m, "mesh", pricing.estimate_of(endpoint))
    out = Path(m["out_dir"]); v = plate.views(m); dest = out / "mesh.raw.glb"
    urls = m["stages"]["plate"]["view_urls"]; front = m["stages"]["plate"]["plate_url"]
    order = {"front": front, "left": urls["left"], "back": urls["back"], "right": urls["right"]}
    # This is a paid job (submit() bills fal the moment the queue call
    # returns a request_id). Record the ledger path on the manifest and check
    # it for an already-submitted request under this manifest's own tag BEFORE
    # calling submit() -- a re-run after a crash between submit and wait must
    # pick that request back up, never pay for it twice.
    manifest.set_stage(m, "mesh", ledger_path=manifest.ledger_path(m)); manifest.save(m)
    tag = "%s:mesh" % m["name"]
    if m["vendor"] == "meshy":
        rid = fal.pending_request_id(meshy.MESH, tag, t)
        if rid is None:
            rid = meshy.multi_image_to_3d([order[k] for k in ("front", "left", "back", "right")], t, tag=tag)
        else:
            manifest.note(m, "mesh gen: resuming fal request %s from the ledger; no new submit" % rid)
        # Spend is already committed at submit: persist the request id right away so a
        # wait/download failure below still leaves it recoverable instead of losing it
        # until the whole call succeeds (same "billable action with nothing persisted to
        # recover it" shape plate.sheet() guards against).
        manifest.set_stage(m, "mesh", fal_request_id=rid); manifest.save(m)
        res = meshy.wait(meshy.MESH, rid, t, poll_secs=poll_secs)
        glb_url = meshy.result_url(res, "glb")
        params = {"endpoint": meshy.MESH, "pose_mode": "a-pose", "topology": "triangle", "target_polycount": 20000}
        model_name = "meshy-7"
    else:
        rid = fal.pending_request_id(tripo.MESH, tag, t)
        if rid is None:
            rid = tripo.multiview_to_model(order, t, tag=tag)
        else:
            manifest.note(m, "mesh gen: resuming fal request %s from the ledger; no new submit" % rid)
        manifest.set_stage(m, "mesh", fal_request_id=rid); manifest.save(m)
        res = tripo.wait(rid, t, poll_secs=poll_secs)
        glb_url = tripo.result_url(res)
        params = {"endpoint": tripo.MESH, "face_limit": 20000, "texture_alignment": "original_image"}
        model_name = "tripo-h3.1"
    # the raw GLB's fal CDN URL is what fal-ai/meshy/rigging takes as model_url (any public GLB)
    manifest.set_stage(m, "mesh", raw_url=glb_url); manifest.save(m)
    t.download(glb_url, dest)
    manifest.set_stage(m, "mesh", artifact_raw=str(dest), params=params, model_name=model_name,
                       cost_usd=pricing.cost_of(params["endpoint"], res))
    manifest.save(m)

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
        manifest.note(m, "mesh prep: no front plate on the manifest; facing not normalized")
        manifest.save(m)
        return None
    out = Path(m["out_dir"])
    script = Path(__file__).parent / "blender" / "facing.py"
    r = subprocess.run([blender or shutil.which("blender"), "--background", "--python", str(script), "--",
                        str(cooked), str(front), str(out / "facing.json"), str(cooked)],
                       capture_output=True, text=True, check=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith("RUNNER_RESULT ")]
    if not lines:
        raise RuntimeError("facing.py printed no result: %s" % (r.stdout[-2000:] or r.stderr[-2000:]))
    rep = json.loads(lines[-1][len("RUNNER_RESULT "):])
    manifest.set_stage(m, "mesh", facing_yaw_deg=rep["yaw_deg"], facing=rep)
    manifest.save(m)
    return rep


def prep(m, blender=None, plate=None):
    out = Path(m["out_dir"]); raw = out / "mesh.raw.glb"; cooked = out / "mesh.20k.glb"
    script = Path(__file__).parent / "blender" / "decimate_check.py"
    r = subprocess.run([blender or shutil.which("blender"), "--background", "--python", str(script), "--",
                        str(raw), str(cooked), "20000"], capture_output=True, text=True, check=True)
    rep = json.loads([l for l in r.stdout.splitlines() if l.startswith("{")][-1])
    (out / "mesh.report.json").write_text(json.dumps(rep, indent=2))
    if rep["tris_out"] > 20000:
        raise RuntimeError("mesh still over cap: %s" % rep)
    if not rep["genus0"]:
        manifest.note(m, "mesh is not genus-0: %s (allowed for skinned rigs; recorded)" % rep)
    manifest.set_stage(m, "mesh", artifact=str(cooked), report=rep); manifest.save(m)
    facing(m, cooked, blender=blender, plate=plate)
    return rep

def bind(m, run=subprocess.run):
    st = m["stages"]["mesh"]; pl = m["stages"]["plate"]
    # This is a media-bind-only site -- the asset already exists (plate.bind
    # created it), so nothing upstream re-checks its claim before this governed
    # write runs.
    genvid_bind.ensure_claim(m, m["asset_id"], "mesh")
    # The bound artifact is the decimated AND facing-normalized mesh, so the turn
    # applied to it belongs in the signed params rather than only in the manifest.
    params = dict(st["params"], report=st["report"])
    if st.get("facing_yaw_deg") is not None:
        params["facing_yaw_deg"] = st["facing_yaw_deg"]
    mid = genvid_bind.import_media(m["project_id"], path=st["artifact"], link_type=genvid_bind.MODEL_LINK,
        asset_id=m["asset_id"], model_provider=m["vendor"], model_name=st["model_name"], render_type="I23D",
        prompt="image-to-3D from the approved plate and its four-view sheet", params=params, attested_cost_usd=st["cost_usd"],
        input_media_ids=list(pl["media_ids"].values()), stage="roblox/mesh", target="roblox", run=run)
    manifest.set_stage(m, "mesh", media_id=mid); manifest.save(m); return mid

def _gen_cli(x):
    m = manifest.load(x.manifest)
    t = (meshy if m["vendor"] == "meshy" else tripo).transport(ledger_path=manifest.ledger_path(m))
    return gen(m, t)

def register(sub):
    p = sub.add_parser("mesh"); s = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("gen", _gen_cli),
                     ("prep", lambda x: prep(manifest.load(x.manifest))),
                     ("bind", lambda x: bind(manifest.load(x.manifest)))):
        a = s.add_parser(name); a.add_argument("--manifest", required=True); a.set_defaults(func=fn)
