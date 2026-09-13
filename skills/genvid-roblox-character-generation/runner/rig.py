"""Stage 3: vendor rig -> R15 skinned FBX (stage_f port) -> bind."""
import json, shutil, subprocess
from decimal import Decimal
from pathlib import Path
import manifest, genvid_bind, plate
from vendors import fal, meshy, tripo, pricing

# The default rig call is ALWAYS fal-ai/meshy/rigging/multi-animation on the mesh
# stage's public GLB url, whichever vendor produced that mesh: the endpoint takes
# any public humanoid GLB. `rig_vendor` is recorded in the stage params so bind()
# attests the rig to the vendor that actually ran it -- signing a Meshy rig as
# Tripo because the MESH came from Tripo would put a false fact in the governed
# provenance record.
DEFAULT_CLIP_IDS = (112, 0, 26, 181)
TRIPO_DIRECT_RIG = "tripo-direct-rig"
# Tripo's DIRECT multiview task (leg C). It has its own PRICES entry rather than
# reusing the fal-hosted tripo.MESH one: the direct API reports what it charged as
# `consumed_credit` on the task, so this leg's cost is OBSERVED per call, where the
# fal-hosted endpoint reports no charge at all and is priced flat from the billing
# export instead.
TRIPO_DIRECT_MESH = "tripo-direct-mesh"


def gen(m, t, poll_secs=15, clip_ids=DEFAULT_CLIP_IDS, tripo_direct=False, resume=None):
    """Rig the mesh. `resume` recovers a job that was already PAID FOR: `""`
    picks up the recorded id for this leg, an explicit id overrides it, and
    `None` (the default) is a fresh run. Which id depends on the leg -- the fal
    queue's `stages.rig.fal_request_id` on the default (Meshy) leg, Tripo's own
    `stages.rig.tripo_mesh_task_id` on the tripo-direct one, since the two
    services have different task identities and different polling.

    Both bake-off Meshy legs needed hand recovery on 2026-09-04 because a
    wait/parse failure after submit left the spend committed with no way back to
    the result, and the same night's leg C crash stranded a paid Tripo mesh task
    until it was recovered by hand.

    What a resume re-spends differs by leg, and so does the budget gate:
      - Default (Meshy) leg: one submit, already paid. The resume makes no new
        submit at all, so the gate is deliberately NOT re-run -- it guards
        spending, and this call spends nothing.
      - tripo-direct leg: TWO paid tasks. Resuming the mesh task says nothing
        about the rig one, so unless `stages.rig.rig_task_id` is also recorded
        this path still submits (and pays for) `animate_rig` -- and it is gated
        for that spend, at the rig's cost alone, since the mesh is already
        bought.
    """
    manifest.require_stage(m, "rig")
    out = Path(m["out_dir"])
    # Record the ledger path this manifest's transport should be (and,
    # via the CLI, is) carrying, so submit()'s ids survive a driver crash
    # independent of the --resume flag above (which reads the manifest's own
    # fal_request_id/tripo_mesh_task_id fields and is unchanged by this).
    manifest.set_stage(m, "rig", ledger_path=manifest.ledger_path(m)); manifest.save(m)
    if tripo_direct:
        # Bake-off leg C. `t` is a tripo.direct_transport() the caller built
        # (the CLI does); taking it as an argument rather than constructing it
        # here keeps TRIPO_API_KEY out of this function and lets the leg be
        # tested over a FakeTransport.
        # This leg spends TWICE -- a multiview mesh task and then a rig_model
        # task -- so both are in the pre-spend estimate and both end up in the
        # attested cost below. Gating and attesting on the rig alone would
        # understate the spend on a governed record, which is exactly what the
        # pack's cost-attestation requirement exists to prevent. Tripo's direct
        # multiview task is billed in the same credits as the fal-hosted
        # endpoint, so it reuses that endpoint's PRICES entry.
        rig_st = m["stages"].get("rig") or {}
        # Read the already-submitted rig task id BEFORE anything writes to the
        # stage: on a resume it is the difference between polling a paid job and
        # paying 30 credits for a second one.
        paid_rig_task = rig_st.get("rig_task_id") if resume is not None else None
        if resume is None:
            plate.budget_gate(m, "rig", str(Decimal(pricing.estimate_of(TRIPO_DIRECT_MESH))
                                            + Decimal(pricing.estimate_of(TRIPO_DIRECT_RIG))))
            # Tripo must own the mesh to rig it (spec §2.2): animate_prerigcheck
            # and animate_rig take a Tripo original_model_task_id, never an
            # arbitrary GLB url, so this leg re-generates the mesh from the SAME
            # approved four-view sheet before rigging it.
            paths = m["stages"]["plate"]["view_paths"]
            tokens = dict((k, tripo.direct_upload(paths[k], t)) for k in ("front", "left", "back", "right"))
            mesh_task = tripo.direct_multiview(tokens, t)
        else:
            mesh_task = resume or rig_st.get("tripo_mesh_task_id")
            if not mesh_task:
                raise RuntimeError("rig gen --tripo-direct --resume: no task id given and none recorded at "
                                   "stages.rig.tripo_mesh_task_id (manifest %s)" % manifest.path_for(m))
            manifest.note(m, "rig gen --tripo-direct --resume %s: picked the already-paid Tripo mesh "
                             "task back up; no re-upload and no second mesh submit. The rig task is "
                             "separate: it is polled when stages.rig.rig_task_id is recorded, and "
                             "otherwise still submitted and billed, through the budget gate."
                             % mesh_task)
        manifest.set_stage(m, "rig", tripo_mesh_task_id=mesh_task); manifest.save(m)
        # Wait for the mesh task before asking whether it is riggable:
        # animate_prerigcheck reads the finished original model.
        mesh_res = tripo.direct_wait(mesh_task, t, poll_secs=poll_secs)
        mesh_cost = pricing.cost_of(TRIPO_DIRECT_MESH, mesh_res)
        manifest.set_stage(m, "rig", tripo_mesh_cost_usd=mesh_cost); manifest.save(m)
        if paid_rig_task:
            rid = paid_rig_task
            manifest.note(m, "rig gen --tripo-direct --resume: animate_rig task %s was already submitted "
                             "and billed; polling it instead of submitting a second one" % rid)
        else:
            if resume is not None:
                # Resuming the MESH task says nothing about the rig one. With no
                # rig_task_id recorded this branch is about to buy a 30-credit
                # animate_rig, so it goes through the same pre-spend gate a fresh
                # run does -- at the rig's cost alone, the mesh being already
                # paid for.
                plate.budget_gate(m, "rig", pricing.estimate_of(TRIPO_DIRECT_RIG))
            if not tripo.direct_check_riggable(mesh_task, t):
                raise RuntimeError("Tripo says the mesh is not riggable; leg C is cut")
            rid = tripo.direct_rig(mesh_task, t, rig_type="biped", spec="mixamo", out_format="fbx")
        manifest.set_stage(m, "rig", rig_task_id=rid); manifest.save(m)
        task = tripo.direct_wait(rid, t, poll_secs=poll_secs)
        dest = out / "rig.raw.fbx"; t.download(tripo.direct_result_url(task), dest)
        rig_cost = pricing.cost_of(TRIPO_DIRECT_RIG, task)
        params = {"rig_vendor": "tripo-direct", "endpoint": TRIPO_DIRECT_RIG, "rig_type": "biped", "spec": "mixamo",
                  "tripo_mesh_task_id": mesh_task, "tripo_mesh_endpoint": TRIPO_DIRECT_MESH,
                  "tripo_mesh_cost_usd": mesh_cost, "tripo_rig_cost_usd": rig_cost}
        manifest.set_stage(m, "rig", artifact_raw=str(dest), rig_task_id=rid, params=params, clip_urls={},
                           cost_usd=str(Decimal(mesh_cost) + Decimal(rig_cost)))
    else:
        mesh_st = m["stages"]["mesh"]
        # On a resume the submit already happened, against the uploaded cooked
        # mesh: read that url back rather than falling to the vendor's raw one,
        # which params["model_url"] would then attest as the rig's input when it
        # was not.
        raw_url = mesh_st.get("rig_input_url") or mesh_st.get("cooked_url") or mesh_st["raw_url"]
        if resume is None:
            plate.budget_gate(m, "rig", pricing.estimate_of(meshy.RIG_CLIPS))
            # Rig the COOKED mesh (stages.mesh.artifact, mesh.20k.glb), never
            # stages.mesh.raw_url. Two witnessed reasons, both from 2026-09-04:
            #   - raw_url is the vendor's UNDECIMATED output. Leg A rigged it and
            #     the R15 came back at 21,023 triangles despite mesh prep's own
            #     19,599 decimate, over the 20,000 Roblox skinned-mesh cap.
            #   - raw_url is also the UNROTATED mesh. When prep turned the mesh to
            #     face -Y, rigging the vendor url re-creates the exact defect the
            #     turn exists to prevent (leg B: a skeleton fitted to a sideways
            #     mesh, both shoulders inside the torso).
            # The cooked artifact is a file this runner made, so it has to be
            # uploaded to fal before the endpoint can read it, and the resulting
            # CDN url is recorded: the rig's real input is then on the manifest
            # rather than implied. An already-recorded cooked_url is reused, so a
            # re-run does not upload the same bytes twice.
            if mesh_st.get("artifact"):
                cooked_url = mesh_st.get("cooked_url") or fal.upload_file(mesh_st["artifact"], t)
                raw_url = cooked_url
                manifest.set_stage(m, "mesh", cooked_url=cooked_url, rig_input_url=cooked_url); manifest.save(m)
            # Check the on-disk ledger for an already-submitted request
            # under this manifest's own tag BEFORE calling rig_with_clips --
            # same "resume instead of resubmit" pattern as mesh.gen, so a
            # driver crash between this submit and its wait() below is
            # recoverable on re-run rather than paying for a second rig.
            tag = "%s:rig" % m["name"]
            rid = fal.pending_request_id(meshy.RIG_CLIPS, tag, t)
            if rid is None:
                rid = meshy.rig_with_clips(raw_url, clip_ids, t, height_meters=1.8, tag=tag)
            else:
                manifest.note(m, "rig gen: resuming fal request %s from the ledger; no new submit" % rid)
            # Spend is already committed at submit: persist the request id right
            # away so a wait/download failure below still leaves it recoverable
            # (the same shape plate.sheet() guards against).
            manifest.set_stage(m, "rig", fal_request_id=rid); manifest.save(m)
        else:
            rid = resume or (m["stages"].get("rig") or {}).get("fal_request_id")
            if not rid:
                raise RuntimeError("rig gen --resume: no request id given and none recorded at "
                                   "stages.rig.fal_request_id (manifest %s)" % manifest.path_for(m))
            manifest.note(m, "rig gen --resume %s: picked the already-paid fal request back up; "
                             "no new submit, no new spend" % rid)
            manifest.set_stage(m, "rig", fal_request_id=rid); manifest.save(m)
        res = meshy.wait(meshy.RIG_CLIPS, rid, t, poll_secs=poll_secs)
        dest = out / "rig.raw.glb"; t.download(meshy.result_url(res, "rig_glb"), dest)
        t.download(meshy.result_url(res, "rig_fbx"), out / "rig.raw.fbx")
        clip_urls = {}
        for cid in clip_ids:
            # By ACTION ID, never by position: the vendor returns animations[] in its
            # own order (witnessed 2026-09-04), so indexing by the requested position
            # writes the wrong take into <cid>.glb without erroring.
            url = meshy.result_url(res, "clip[%d]" % cid); clip_urls[str(cid)] = url
            t.download(url, out / "clips" / ("%d.glb" % cid))
        params = {"rig_vendor": "meshy", "endpoint": meshy.RIG_CLIPS, "model_url": raw_url,
                  "height_meters": 1.8, "animation_action_ids": list(clip_ids)}
        manifest.set_stage(m, "rig", artifact_raw=str(dest), rig_task_id=res.get("rig_task_id"), fal_request_id=rid,
                           params=params, clip_urls=clip_urls, cost_usd=pricing.cost_of(meshy.RIG_CLIPS, res))
    manifest.save(m)


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


def bind(m, run=subprocess.run):
    st = m["stages"]["rig"]
    # Media-bind-only site, covers BOTH governed writes below (the FBX row
    # and, when there is one, its GLB twin) -- one claim check before either runs.
    genvid_bind.ensure_claim(m, m["asset_id"], "rig.bind")
    rig_vendor = st.get("params", {}).get("rig_vendor", m["vendor"])
    # Derivation inputs follow the leg that actually produced this FBX. Leg C
    # (tripo-direct) rigs a mesh gen() regenerated from the approved four-view
    # sheet and never bound, so stages.mesh.media_id is not this rig's input --
    # citing it would put a derivation edge that does not exist into the signed
    # provenance record. The bound plate views are the real ancestors, which is
    # what mesh.bind() cites for the same reason.
    if rig_vendor == "tripo-direct":
        inputs = list(m["stages"]["plate"]["media_ids"].values())
    else:
        inputs = [m["stages"]["mesh"]["media_id"]]
    mid = genvid_bind.import_media(m["project_id"], path=st["artifact"], link_type=genvid_bind.MODEL_LINK,
        asset_id=m["asset_id"], model_provider=rig_vendor, model_name="%s-rig+r15-convert" % rig_vendor,
        render_type="I23D", prompt="vendor auto-rig converted to the 15-bone R15 skeleton", attested_cost_usd=st["cost_usd"],
        params=dict(st["params"], report=st["report"]), input_media_ids=inputs,
        stage="roblox/r15-rigged", target="roblox", run=run)
    # Persist after EACH governed write, the same shape plate.bind(), rig.gen() and
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
        glb_mid = genvid_bind.import_media(m["project_id"], path=st["artifact_glb"], link_type=genvid_bind.MODEL_LINK,
            asset_id=m["asset_id"], model_provider=rig_vendor, model_name="%s-rig+r15-convert" % rig_vendor,
            render_type="I23D", prompt="vendor auto-rig converted to the 15-bone R15 skeleton, glTF-binary twin",
            attested_cost_usd=pricing.NO_VENDOR_CALL, params=dict(st["params"], report=st["report"], container="glb",
                                               forward_axis="-Z" if twin_yaw == 180 else "+Z",
                                               twin_rotation_deg=twin_yaw,
                                               note="same conversion as the FBX row; glTF-binary for the "
                                                    "roblox/r15-rigged conformance profile; turned "
                                                    "%d deg about up relative to the FBX" % twin_yaw),
            input_media_ids=inputs, stage="roblox/r15-rigged", target="roblox", run=run)
        manifest.set_stage(m, "rig", glb_media_id=glb_mid); manifest.save(m)
    # The two Blender workbench preview frames are NOT bound. What is witnessed
    # (2026-09-04) is only the outcome: the preview-render binds were the one
    # part of the bake-off's rig binds that did not land. The CAUSE was not
    # isolated. The run note at the time read it as render_type "image" being
    # outside the media vocabulary, and that reading is an assumption the same
    # morning's record argues against: the biome and HUD plates carrying
    # render_type "image" were bound through the MCP ingest_generated_media path
    # ($0.48 attested). Which says nothing certain about THIS path -- the
    # runner's own plate and biome bind sites send "image" through
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
    # capture (E25) is the visual record that is actually reviewed. The frames
    # stay on the manifest as files so a reviewer can open them.
    manifest.set_stage(m, "rig", preview_media_ids=[], previews_unbound=list(st["previews"]))
    manifest.note(m, "rig bind: the %d workbench preview frame(s) are not bound -- a local "
                     "look-check render of an already-bound artifact is not a governed "
                     "generation and has no honest render type; the bake-off's preview binds "
                     "were rejected (witnessed 2026-09-04) with the cause not isolated. Files "
                     "at stages.rig.previews_unbound" % len(st["previews"]))
    manifest.save(m)
    return mid


def surface_prep(m, texture, blender=None, run=subprocess.run):
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
    genvid_bind.ensure_claim(m, m["asset_id"], "rig.surface")
    out = Path(m["out_dir"])
    rig_st = m["stages"]["rig"]
    raw = rig_st["artifact_raw"]
    dst = out / "rig.r15.surface.fbx"
    rep = _convert_r15(out, raw, dst, texture, blender)
    manifest.set_stage(m, "rig", surface_artifact=str(dst), surface_report=rep,
                       surface_previews=[str(dst) + ".view0.png", str(dst) + ".view1.png"])
    manifest.save(m)
    rig_vendor = rig_st.get("params", {}).get("rig_vendor", m["vendor"])
    mid = genvid_bind.import_media(m["project_id"], path=str(dst), link_type=genvid_bind.MODEL_LINK,
        asset_id=m["asset_id"], model_provider=rig_vendor, model_name="%s-rig+r15-convert+surface" % rig_vendor,
        render_type="I23D", prompt="R15 skinned rig re-textured for the surface pass",
        params={"stage": "surface-pass", "report": rep, "texture": str(texture)},
        input_media_ids=[rig_st["media_id"]], attested_cost_usd=pricing.NO_VENDOR_CALL,
        stage="roblox/r15-rigged", target="roblox", run=run)
    manifest.set_stage(m, "rig", surface_media_id=mid); manifest.save(m)
    return mid


def _gen_cli(args):
    m = manifest.load(args.manifest)
    clip_ids = tuple(int(x) for x in str(args.clips).split(",") if x.strip())
    ledger_path = manifest.ledger_path(m)
    t = tripo.direct_transport(ledger_path=ledger_path) if args.tripo_direct else meshy.transport(ledger_path=ledger_path)
    return gen(m, t, clip_ids=clip_ids, tripo_direct=args.tripo_direct, resume=args.resume)


def register(sub):
    p = sub.add_parser("rig"); s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("gen"); a.add_argument("--manifest", required=True)
    a.add_argument("--clips", default=",".join(str(c) for c in DEFAULT_CLIP_IDS),
                   help="comma-separated fal library animation ids (1-10 distinct, 0-696)")
    a.add_argument("--tripo-direct", action="store_true",
                   help="bake-off leg C: Tripo direct-API rig; needs TRIPO_API_KEY in the environment")
    a.add_argument("--resume", nargs="?", const="", default=None, metavar="REQUEST_ID",
                   help="pick an already-paid rig job back up instead of submitting a new one: bare "
                        "--resume reads stages.rig.fal_request_id (default leg) or "
                        "stages.rig.tripo_mesh_task_id (--tripo-direct), or pass the id. On the "
                        "tripo-direct leg the rig task is separate and is still submitted (and "
                        "billed, through the budget gate) unless stages.rig.rig_task_id is recorded")
    a.set_defaults(func=_gen_cli)
    b = s.add_parser("r15"); b.add_argument("--manifest", required=True); b.add_argument("--texture")
    b.set_defaults(func=lambda x: r15(manifest.load(x.manifest), x.texture))
    c = s.add_parser("bind"); c.add_argument("--manifest", required=True); c.set_defaults(func=lambda x: bind(manifest.load(x.manifest)))

    # Second top-level group, registered here (not in cli.py's GROUPS) since this
    # module already owns the rig-conversion machinery the surface pass reuses.
    surf = sub.add_parser("surface"); ss = surf.add_subparsers(dest="cmd", required=True)
    sp = ss.add_parser("prep", help="re-bake an EXISTING character's rig with a new texture and bind it")
    sp.add_argument("--manifest", required=True)
    sp.add_argument("--texture", required=True)
    sp.set_defaults(func=_surface_prep_cli)

    # adopt / adopt-emit: a rig that already exists in Studio gets a manifest
    # whose chain starts at rest (adopt.py); the verbs live here because the
    # orchestrator thinks of it as a rig operation, not a new group.
    import adopt
    adopt.register(s)


def _surface_prep_cli(args):
    surface_prep(manifest.load(args.manifest), args.texture)
