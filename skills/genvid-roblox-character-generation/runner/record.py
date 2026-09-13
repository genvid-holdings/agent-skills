"""Stage 8 (final): record stage -- conformance check, provenance export,
and (when there is something to record) the hand-tuned-corrections payload.

For the terminal media and each bound clip media, checks `genvid_bind.conformance`
(the `genvid get-media-conformance` CLI call, three positional path parameters --
project-id, asset-id, media-id, in that order (witnessed via
`genvid get-media-conformance --help`, 2026-09-04) -- and folds the verdicts
into one `stages.record.result`, which eval
row E26 reads: conformant only when the boundary said so for every row it was
asked about. Nothing is excused here, by id or otherwise -- except that a clip or
a capture is never 3D model media, and the endpoint's own `--help` documents a
422 for exactly that case ("if the media is not 3D model media"); a failed call
for one of those is recorded as `{"skipped": <reason>}` rather than raised, and
never counts against the verdict. Only the terminal (model) media's call is left
unable to fail quietly. The
one check the bake-off saw failing -- `rig.forward-axis`, +Z measured against a
required -Z on the GLB twins (witnessed 2026-09-04) -- is a consumer-side
convention difference (the Roblox importer reads the FBX as -Z; Genvid's glTF
reader measured the identical-coordinate twin as +Z), and it is fixed where the
twin is made, in `blender/rig_r15.py`'s half-turn export (a turned twin passes
the profile outright), so the profile passes on the artifact rather
than past a list of excuses kept here. The terminal media is
`stages.rig.media_id` on a skinned-rig manifest; a static (prop)
manifest has no "rig" stage at all (`manifest.STATIC_STAGES` ends
plate -> mesh -> wire -> record), so there the terminal, and only, bound
artifact is `stages.mesh.media_id` -- that is what gets checked and recorded.
Exports the asset's
full provenance graph to `<out_dir>/provenance.json` via
`genvid_bind.provenance`. If `stages.wire.hand_tuned` (posture tweaks applied
by hand during wiring, never baked into a vendor artifact) is non-empty AND
`record_approved_corrections` is live on this project (SKILL.md 5.2: it is
`status: designed`, not yet on prod, as of this pack bump -- callers pass
`corrections_tool_present=True` only once that has been confirmed live),
writes that payload for the orchestrator to run; otherwise records why not
via `manifest.note` so a reviewer sees the gap rather than silence. Always
writes an `export_provenance_report` payload alongside it.

The corrections payload uses `genvid_bind.MODEL_LINK` (`cast_member_model`),
not `prop_model`: the pack rule is prefix = asset type, and every other
stage's bind() (`rig.bind`, `mesh.bind`, `clips.bind`) uses `cast_member_model`
for a model artifact on a `cast_member` asset. `clips.bind()`'s own docstring
states the same precedent.
"""
import json
import subprocess
from pathlib import Path

import genvid_bind
import manifest


def run(m, run=subprocess.run, corrections_tool_present=False, allow_unregistered=False):
    manifest.require_stage(m, "record", allow_unregistered=allow_unregistered)
    if allow_unregistered:
        # manifest.require_stage(..., allow_unregistered=True) tolerates a clip
        # whose registration.state is still "payload_written" (the orchestrator has
        # not run its register_media/finalize_media_registration payloads for real
        # yet); name which ones so a reader sees the gap, not silence -- the same
        # discipline the hand-tuned-corrections branch below already follows. Eval
        # row E27 reads PEND, never PASS, for these clips regardless of this note.
        items = m["stages"].get("clips", {}).get("items") or {}
        pending = sorted(clip for clip, it in items.items()
                         if (it.get("registration") or {}).get("state") != "registered")
        if pending:
            manifest.note(m, "record --allow-unregistered: proceeding with clip(s) still at "
                              "registration.state=payload_written: %s -- eval row E27 reads PEND for these, "
                              "never PASS, until `clips registered` records their finalized Genvid media id"
                              % ", ".join(pending))
    # A static (prop) manifest has no "rig" stage (manifest.STATIC_STAGES
    # is plate/mesh/wire/record); its terminal bound artifact is the mesh.
    terminal_stage = "mesh" if m.get("kind") == "static" else "rig"
    terminal = m["stages"][terminal_stage]
    # Prefer the glTF-binary twin when the rig stage bound one: the
    # roblox/r15-rigged conformance profile (spec 1.1.0) reads gltf-binary only
    # and fails an FBX at container.format (witnessed 2026-09-04), so checking
    # the FBX row records "nonconformant" for a rig that is fine. The FBX row is
    # still the Studio import artifact and still in the provenance graph.
    terminal_media_id = terminal.get("glb_media_id") or terminal["media_id"]
    clip_media_ids = dict(m["stages"].get("clips", {}).get("media_ids") or {})

    conformance = {}
    all_conformant = True

    def _check(label, media_id, tolerate_failure):
        try:
            return genvid_bind.conformance(m["project_id"], m["asset_id"], media_id, run=run)
        except subprocess.CalledProcessError as e:
            if not tolerate_failure:
                raise
            # A clip (KeyframeSequence) or a capture is never 3D model media --
            # get-media-conformance's model profile (roblox/r15-rigged and
            # friends) 422s on it (non-zero exit under check=True). That is not
            # a conformance failure to roll up, it is the wrong check being
            # asked of the wrong media kind, so it is recorded as skipped
            # rather than aborting the whole record stage or counting against
            # the verdict. Only the terminal (model) media below is held to
            # "the boundary's verdict and only that" without this tolerance.
            # str(e) alone drops stderr (CalledProcessError.__str__ only names
            # the exit status), so a real wrong bind -- the CLI 404s a media id
            # that is not linked to this asset, per its own --help -- would
            # read identically to the sanctioned "not 3D model media" 422 here.
            # Fold e.stderr in so a reviewer can tell the two apart from the
            # skip reason alone (eval row E26 reads this field).
            return {"skipped": "get-media-conformance failed for %s (media %s): %s: %s"
                                % (label, media_id, e, (e.stderr or "").strip())}

    # The terminal artifact (the rig's GLB twin, or the mesh for a static
    # asset) is the only entry the manifest marks as 3D model media; its
    # conformance call is never tolerated to fail -- a real failure there
    # aborts the stage, same as before.
    terminal_res = _check(terminal_stage, terminal_media_id, tolerate_failure=False)
    conformance[terminal_stage] = terminal_res
    # The boundary's verdict, and only that. A row it calls nonconformant is
    # nonconformant here whatever the failing check is named: a runner that
    # keeps a list of checks it forgives grades its own homework, and the
    # whole response is on stages.record.conformance for a reader who wants
    # to see which check it was.
    if not terminal_res.get("conformant"):
        all_conformant = False

    for label, media_id in sorted(clip_media_ids.items()):
        res = _check(label, media_id, tolerate_failure=True)
        conformance[label] = res
        if "skipped" not in res and not res.get("conformant"):
            all_conformant = False

    prov = genvid_bind.provenance(m["project_id"], "asset", m["asset_id"], run=run)
    prov_path = Path(m["out_dir"]) / "provenance.json"
    prov_path.write_text(json.dumps(prov, indent=2, sort_keys=True))

    hand_tuned = m["stages"].get("wire", {}).get("hand_tuned") or {}
    if hand_tuned and corrections_tool_present:
        genvid_bind.mcp_payload("record_approved_corrections", m["out_dir"],
            project_id=m["project_id"], asset_id=m["asset_id"], media_id=terminal_media_id,
            link_type=genvid_bind.MODEL_LINK, target="roblox", stage="roblox/r15-rigged",
            payload=json.dumps(hand_tuned),
            note="hand-tuned wiring corrections approved for %s" % m["name"])
    elif not hand_tuned:
        manifest.note(m, "record: no hand-tuned values on stages.wire.hand_tuned; "
                          "record_approved_corrections not needed")
    else:
        manifest.note(m, "record: stages.wire.hand_tuned is non-empty but "
                          "record_approved_corrections is not yet live on this project "
                          "(SKILL.md 5.2, status: designed); corrections were not recorded")

    genvid_bind.mcp_payload("export_provenance_report", m["out_dir"],
        project_id=m["project_id"], format="json")

    result = "conformant" if all_conformant else "nonconformant"
    manifest.set_stage(m, "record", media_id=terminal_media_id, result=result, conformance=conformance,
                       provenance=str(prov_path))
    manifest.save(m)
    return result


def _run_cli(x):
    # The CLI wrappers return an exit CODE, never the verdict string (studio.py's
    # own register() already documents this convention): cli.py does
    # `sys.exit(main() or 0)`, so returning "conformant"/"nonconformant" -- both
    # truthy -- makes every run, passing or failing, print to stderr and exit 1,
    # leaving the orchestrator's final gate unscriptable from the exit status.
    # `run=subprocess.run` is passed explicitly (read fresh at call time) rather
    # than left to run()'s default so a test can patch subprocess.run.
    m = manifest.load(x.manifest)
    result = run(m, run=subprocess.run, corrections_tool_present=x.corrections_tool_present,
                allow_unregistered=x.allow_unregistered)
    return 0 if result == "conformant" else 1


def register(sub):
    p = sub.add_parser("record"); s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("run"); a.add_argument("--manifest", required=True)
    a.add_argument("--corrections-tool-present", action="store_true",
                   help="pass only once record_approved_corrections is confirmed live (SKILL.md 5.2)")
    a.add_argument("--allow-unregistered", action="store_true",
                   help="accept a clip whose registration.state is still 'payload_written' "
                        "instead of 'registered'; eval row E27 reads PEND, never PASS, for it")
    a.set_defaults(func=_run_cli)
