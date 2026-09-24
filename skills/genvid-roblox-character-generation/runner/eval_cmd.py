"""`runner eval` -- prints and writes the eval-matrix table (plan
docs/superpowers/plans/2026-09-02-rdc-week-runner.md, "Eval matrix" section, rows E1-E29).

Reads only files on disk plus the manifest passed in; never imports another stage
module (mesh.py, rig.py, groundfit.py, clips.py, studio.py, wire.luau results are
all read as data, not code, so this module works standalone regardless of which
stage modules exist yet).

Conventions this module assumes about data other stage modules produce (pin these
here: a stage module either conforms to them or this file is updated to match):
  - `<out_dir>/rest.json`: the `dump_rest` output, `{bone: {"parent": str|None,
    "rot": [9 floats row-major], "pos": [x, y, z]}}` -- the same shape as
    tests/test_runner_metrics.py's REST fixture.
  - `<out_dir>/clips/<Clip>.poses.json`: one poses JSON (kfs.write's input shape,
    `{"hier":..., "frames": [{"t":..., "p": {bone: quat}}], "clip_seconds":...}`)
    per clip, plus a sibling `<Clip>.traj.json` of `{bone: [[t, x, y, z], ...]}`
    world-space trajectories for foot_lift/impact_height.
  - `<out_dir>/eval.json`: this module's own prior output, re-read at the start
    of every run so `groundfit.gap_close` / `groundfit.gap_far`, the whole
    `groundfit.probe_close` / `groundfit.probe_far` results E13 and E14 read
    their conditions off, and `wire.walk_probe` -- all written by studio.py's
    probe_feet / probe_walk ingests directly into this file, never computed here
    -- survive a re-run instead of being wiped back to null. Every other top-level key (`mesh`, `rig`,
    `clips`, `cost`) is this module's own and is recomputed fresh each run. Note
    the file has NO top-level `eval` wrapper key -- `mesh.has_basecolor`, not
    `eval.mesh.has_basecolor` -- matching what `run()` below actually writes.
  - `<out_dir>/silhouette.json`: silhouette_iou.py's own `out.json` argument,
    `{"iou": float, "has_basecolor": bool}` -- the source for E5/E6.
  - `<out_dir>/provenance.json`: raw `genvid get-provenance` output for E27.
  - The ingest records' caller-attested costs (`generated.<item>.cost`,
    `props.<prop>.generated.<item>.cost`, `fetched.<ref>.cost`; see
    cost.records_on) -- the USD ones summed for E29, with the unobserved and
    non-USD records counted beside the total in eval.json's `cost`.

A gate row with no evidence on disk is reported FAIL ("missing"), never PASS and
never silently skipped -- see CLAUDE.md Ground Truth Before Claims: no assumption
may render as fact. A non-gate row with no evidence is reported PENDING (`pass`
is `None`), which is an honest "not yet measured", not a false PASS.
"""
import json
import math
from pathlib import Path

import cost
import metrics
import timing

# The authoritative measurement for these two is `dump_rest` on the PARKED
# template in Studio, then reading both off that dump. What follows is a
# LOCAL-ONLY proxy measurement against archived artifacts on disk (2026-09-03),
# kept as a comment, not a calibration -- `calibrated` stays False and `value`
# is untouched (still the spec's numbers) until dump_rest runs against the
# parked template and someone deliberately sets these.
#
#   E10 shoulder_ratio, proxy source:
#     a rigged character's roblox_rest.json (the rest dump written beside the
#     rig artifact in the manifest's out_dir)
#     feet_y = min(world_y(LeftFoot), world_y(RightFoot))  (ankle-bone proxy,
#     not groundfit's mesh-sole feetPlane) -> shoulder_ratio = 0.8887.
#     0.9x that would be 0.80, well above the spec's 0.68 -- the spec number is
#     the conservative one here, on this one proxy sample.
#   E6 silhouette_iou, proxy source:
#     the conditioned mesh vs that manifest's own front plate PNG
#     (confirmed single front view, flat gray ground, orientation matches) ->
#     iou = 0.40, well BELOW the spec's 0.75. `conditioned.glb` is the mesh
#     stage's un-decimated intermediate output, not the final skinned/rigged
#     mesh the real E6 measurement would run against, so this number is not
#     trustworthy as a calibration input either way -- flagging the mismatch
#     rather than acting on it.
#   E17/E18 sanity check (not a calibration input, no threshold here to set):
#     that same character's Mixamo walk-poses JSON in out_dir
#     (the approved July walk) -> hip_twist_deg = 5.76 (limit 25), knee_twist_frac
#     = 0.238 (limit 0.25) -- both pass, knee twist close to the limit.
#
# E6 IS now calibrated (2026-09-04 bake-off findings). The proxy above
# measured `conditioned.glb`,
# a PRE-RIG intermediate, against its plate. The calibration below measures the
# same artifact CLASS as the candidates -- the rigged GLB -- which is the whole
# reason the number moved. The instrument's absolute scale is low either way (an
# approved mesh scores ~0.43 against its own plate: A-pose arm angle and plate
# shadow differ), so E6 RANKS candidates, it does not certify them; the zoo
# verdict stands above it.
CALIBRATION = {
    "E6": {"value": 0.389, "calibrated": True,
           "source": "2026-09-04 bake-off findings: 0.9 x silhouette_iou of an earlier approved "
                     "rigged character's artifacts against their own plate -- rigged_character.glb "
                     "0.4325, rigged.glb 0.432, r15_large_stylized.fbx 0.4325 (same artifact class "
                     "as the candidates, the rigged GLB) -> 0.9 x 0.4325 = 0.389. Candidates on "
                     "rig.raw.glb: leg A 0.3815 (fails by 0.008), leg B front-corrected v2 0.4465 "
                     "(passes)."},
    "E10": {"value": 0.68, "calibrated": False, "source": None},
    # Offline skeleton-fit gate: shoulder-bone separation over the largest mesh
    # span, read off the RAW vendor rig by blender/rig_r15.py before any Studio
    # step. Threshold stated by the eval matrix and backed by the same
    # measurements: leg A 0.48 m / 1.80 m = 0.27 (a skeleton that fits), leg B v1
    # 0.12 / 1.59 = 0.075 (both shoulders inside the torso, forearm weight bleed).
    "E10b": {"value": 0.15, "calibrated": True,
             "source": "2026-09-04 bake-off findings, raw rig glb in world space: leg A 0.48 m "
                       "separation over 1.80 m span = 0.27; leg B v1 (misaligned) 0.12 over 1.59 "
                       "= 0.075. Gate: separation/span >= 0.15 before any Studio step."},
    # Left/right skinning balance. 734/8062 = 0.091 on leg B is plainly broken and
    # 0.94 is plainly fine, but nothing has measured where the line sits, so this
    # row reports and never gates -- the same treatment E10 gets.
    "E10c": {"value": 0.5, "calibrated": False, "source": None},
}

CLIP_NAMES = ("Walk", "Attack")
BRANDS = ("mixamo", "meshy", "quaternius", "tripo", "cascadeur")


def _dig(d, dotted):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _load_json(path):
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


def _le(threshold):
    return lambda v: v is not None and v <= threshold


def _ge(threshold):
    return lambda v: v is not None and v >= threshold


def _between(lo, hi):
    return lambda v: v is not None and lo <= v <= hi


def _eq(expected):
    return lambda v: v == expected


def _truthy(v):
    return bool(v)


def _all_true(v):
    if isinstance(v, dict):
        return len(v) > 0 and all(bool(x) for x in v.values())
    return False


def _no_brand(name):
    if not name:
        return None
    low = name.lower()
    return not any(b in low for b in BRANDS)


class Ctx:
    """Everything a row getter may read, loaded once per `run()`."""

    def __init__(self, m):
        self.m = m
        self.out = Path(m["out_dir"])
        self.rest = _load_json(self.out / "rest.json")
        self.provenance = _load_json(self.out / "provenance.json")
        self.eval_prior = _load_json(self.out / "eval.json") or {}
        self.silhouette = _load_json(self.out / "silhouette.json")
        self.cost_totals = cost.totals(m)
        self.clip_poses = {}
        self.clip_traj = {}
        for clip in CLIP_NAMES:
            self.clip_poses[clip] = _load_json(self.out / "clips" / ("%s.poses.json" % clip))
            self.clip_traj[clip] = _load_json(self.out / "clips" / ("%s.traj.json" % clip))

    def feet_y(self):
        return _dig(self.m, "stages.groundfit.result.feetPlane")


def _row_E1(ctx):
    return _dig(ctx.m, "stages.plate.gaps_ok")


def _row_E3(ctx):
    return _dig(ctx.m, "stages.mesh.report.tris_out")


def _row_E3b(ctx):
    """Triangles in the EXPORTED R15 mesh, written by blender/rig_r15.py after
    its post-rig decimate. E3 measures the cooked mesh going INTO the rig; this
    row measures what comes out, because vendors re-mesh: Tripo's animate_rig
    returned 101,184 triangles regardless of the mesh task's face_limit, and
    Meshy's rigging returned 21,023 for a 19,599-triangle input (both witnessed
    2026-09-04). A report with no tris_r15 predates the measurement and reads
    FAIL(missing), which is the honest verdict for an unmeasured gate."""
    return _dig(ctx.m, "stages.rig.report.tris_r15")


def _row_E4(ctx):
    return _dig(ctx.m, "stages.mesh.report.shells")


def _row_E5(ctx):
    if ctx.silhouette is not None and "has_basecolor" in ctx.silhouette:
        return ctx.silhouette["has_basecolor"]
    return _dig(ctx.eval_prior, "mesh.has_basecolor")


def _row_E6(ctx):
    if ctx.silhouette is not None and "iou" in ctx.silhouette:
        return ctx.silhouette["iou"]
    return _dig(ctx.eval_prior, "mesh.silhouette_iou")


def _row_E7(ctx):
    """Bone COUNT. rig_r15.py writes `report.bones` as the sorted list of the
    surviving bone names (that is what the R6 conversion test pins, and the
    names are what makes a short report diagnosable); this row is the count, so
    fold a list down to its length here rather than having the producer write a
    number and throw the names away."""
    v = _dig(ctx.m, "stages.rig.report.bones")
    if isinstance(v, (list, tuple)):
        return len(v)
    return v


def _row_E8(ctx):
    return _dig(ctx.m, "stages.rig.report.unweighted_frac")


def _row_E9(ctx):
    """Distance the armature origin moved to sit on the root bone. rig_r15.py
    writes `report.root_offset` as the [x, y, z] vector it shifted by; take its
    magnitude. A bare number (an older report) is still accepted."""
    v = _dig(ctx.m, "stages.rig.report.root_offset")
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return math.sqrt(sum(float(c) * float(c) for c in v))
    return abs(v)


def _row_E10(ctx):
    if ctx.rest is None:
        return None
    feet_y = ctx.feet_y()
    if feet_y is None:
        return None
    return metrics.shoulder_ratio(ctx.rest, feet_y)


def _row_E10b(ctx):
    """Offline skeleton fit: shoulder-bone separation / mesh span, written by
    blender/rig_r15.py off the RAW vendor rig. Catches a skeleton fitted to a
    mesh facing the wrong way before anything reaches Studio."""
    return _dig(ctx.m, "stages.rig.report.shoulder_sep_frac")


def _row_E10c(ctx):
    """Worst left/right weighted-vertex balance over the R15 keeper pairs. Not a
    gate: it is the diagnostic that names skinning bleed (leg B's forearms, 8062
    against 734), and no threshold for it has been measured."""
    return _dig(ctx.m, "stages.rig.report.symmetry_min_frac")


def _row_E11(ctx):
    return _dig(ctx.m, "stages.rest.result")


def _row_E12(ctx):
    """hip / height, on the hip the template ACTUALLY carries.

    `stages.groundfit.result.hipHeight` is the SOLE OFFSET the groundfit step
    measured, not the final hip: standing still a Humanoid holds its root bottom
    at HipHeight + e, so the settle loop corrects the sole offset by that
    measured e and `sethip` writes the result onto the template. Read the applied
    hip when the loop has run (the bake-off's 0.45 / 0.39 / 0.21 are the
    corrected hips 22.65 / 19.41 / 10.67, not the 23.1 / 20.3 / 11.7 the
    groundfit step reported), and fall back to the sole offset when it has not."""
    hip = _dig(ctx.m, "stages.groundfit.hip_applied.hip")
    if hip is None:
        hip = _dig(ctx.m, "stages.groundfit.result.hipHeight")
    if hip is None:
        return None
    return hip / float(ctx.m["height_studs"])


def _row_E12_readings(ctx):
    """Every hip reading this row could be scored on, side by side.

    The gate scores one number, but three exist and the bake-off findings
    (correction after the advisor pass, 2026-09-04) rule that the others be shown
    rather than quietly replaced -- a gate whose verdict flips when its formula
    changes has to show the reading it flipped away from:

      applied_hip       what the template actually carries once the settle loop
                        wrote it (`HipHeightStuds`). `value` above is this over
                        height, and it is the reading the gate scores.
      sole_offset       the geometric HRP-bottom-to-lowest-vertex distance the
                        groundfit step measured (`SoleOffsetStuds`, what anchored
                        placement reads). It is the applied hip plus the rig's
                        hover constant e -- 0.45 / 0.89 / 1.03 studs across the
                        bake-off legs -- so it reads slightly higher, and reading
                        it as the hip floats a live rig by e.
      spine_spacing_hip the same measurement under the SUPERSEDED rootSize rule,
                        `2 x (UpperTorso.Y - LowerTorso.Y)`. That rule read a
                        skeleton property: a Mixamo-convention rig maps Spine2 to
                        UpperTorso and got a 22-stud box on a 50-stud body, which
                        failed leg C at 0.234 on feet that were fine where the
                        body-height rule reads 0.38. Computed from the numbers
                        groundfit.luau already reports (lowerTorsoY, upperTorsoY,
                        feetPlane), so it is the same rig measured two ways --
                        None when the ground fit did not report them.

    Each reading carries its fraction of height beside the studs, and `gated`
    names which one `value` came from. Readings are not gates: nothing here is
    scored, and a missing one is None rather than a substitute.
    """
    height = float(ctx.m["height_studs"])

    def frac(v):
        return None if v is None else v / height

    sole = _dig(ctx.m, "stages.groundfit.result.hipHeight")
    applied = _dig(ctx.m, "stages.groundfit.hip_applied.hip")
    lower = _dig(ctx.m, "stages.groundfit.result.lowerTorsoY")
    upper = _dig(ctx.m, "stages.groundfit.result.upperTorsoY")
    feet = _dig(ctx.m, "stages.groundfit.result.feetPlane")
    spine = None
    if _is_number(lower) and _is_number(upper) and _is_number(feet):
        spine = (lower - feet) - (upper - lower)
    return {
        "applied_hip": applied, "applied_hip_frac": frac(applied),
        "sole_offset": sole, "sole_offset_frac": frac(sole),
        "spine_spacing_hip": spine, "spine_spacing_hip_frac": frac(spine),
        "gated": "applied_hip" if applied is not None else
                 ("sole_offset" if sole is not None else None),
    }


def _probe_gap(ctx, lod, require_play=False):
    """The feet-gap number a probe_feet run is entitled to report, or None (PEND).

    A gap is only a measurement of the ground fit when the probe stood the rig at
    a MEASURED settled height -- the verification settle's, recorded by
    studio.settled_bottom(). Posed at the hip instead it reads -e (the hover
    constant, 0.45 / 0.89 / 1.03 studs on the bake-off legs), which sails through
    the +-0.5 gate while verifying nothing.

    The far row additionally needs the vertex read to have happened in PLAY: in
    Edit, RenderFidelity does not change vertex data and a held pose does not
    move, so the far number is the close number again. That read waits on the
    experience's Mesh & Image API setting (the operator's, not this runner's), so E14
    is PEND meanwhile -- as it was on all three bake-off legs.
    """
    probe = _dig(ctx.eval_prior, "groundfit.probe_%s" % lod)
    if not isinstance(probe, dict) or not probe.get("settledMeasure"):
        return None
    if require_play and not probe.get("inPlay"):
        return None
    return probe.get("gap")


def _row_E13(ctx):
    return _probe_gap(ctx, "close")


def _row_E14(ctx):
    return _probe_gap(ctx, "far", require_play=True)


def _clip_metric(ctx, clip, fn):
    poses = ctx.clip_poses.get(clip)
    if not poses or "frames" not in poses:
        return None
    return fn(poses)


def _row_E15(ctx):
    """Walk cycle length, SCALED. `<Clip>.poses.json`'s frame `t`s are raw,
    unscaled seconds (kfs.write, not transfer(), is what applies
    timing.scale_time -- see clips.py's on-disk docs) but the plan's threshold
    (">= 2.0 s" at 50 studs) is a scaled-seconds number, so scale the raw
    cycle length here the same way clips.impact() scales attackImpactDelaySecs,
    or every character taller than REF_HEIGHT reads a cycle short of the gate."""
    poses = ctx.clip_poses.get("Walk")
    if not poses:
        return None
    times = [f["t"] for f in poses.get("frames", [])]
    if not times:
        return None
    raw = metrics.cycle_seconds(times)
    # as the built Walk plays: its own time_scale when `clips build` set one
    return timing.clip_time(_dig(ctx.m, "stages.clips.items.Walk"), raw, ctx.m["height_studs"])


def _row_E16(ctx):
    traj = ctx.clip_traj.get("Walk")
    return metrics.foot_lift(traj) if traj else None


def _row_E17(ctx):
    return _clip_metric(ctx, "Walk", lambda p: metrics.hip_twist_deg(p["frames"]))


def _row_E18(ctx):
    return _clip_metric(ctx, "Walk", lambda p: metrics.knee_twist_frac(p["frames"]))


def _row_E19(ctx):
    """Fractional deviation of the POST-SCALE treadmill stride from walkSpeed.

    `stages.clips.treadmill` (speed 1) is what clips.speed_scale() divides
    walkSpeed by to get animSpeedScale, so comparing it back against
    walkSpeed / animSpeedScale is identically zero -- a gate that could not
    fail. The row reads `stages.clips.treadmill_scaled` instead: the same
    treadmill.luau run a second time at {{SPEED}} = animSpeedScale (studio
    step `treadmill_scaled`), compared straight against `m["walk_speed"]`,
    the game-side Humanoid.WalkSpeed. None (PEND) until that second run and
    walk_speed both exist; a scaled run recorded under a different
    animSpeedScale than the manifest now carries is stale and also PEND."""
    scaled = _dig(ctx.m, "stages.clips.treadmill_scaled")
    scale = _dig(ctx.m, "stages.clips.animSpeedScale")
    walk_speed = ctx.m.get("walk_speed")
    if not scaled or not scale or walk_speed is None or float(walk_speed) == 0:
        return None
    if scaled.get("animSpeedScale") is not None and abs(float(scaled["animSpeedScale"]) - float(scale)) > 1e-9:
        return None
    stride = scaled.get("strideStudsPerSec")
    if stride is None:
        return None
    return abs(float(stride) - float(walk_speed)) / float(walk_speed)


def _row_E20(ctx):
    return _dig(ctx.m, "stages.clips.attackImpactDelaySecs")


def _row_E21(ctx):
    traj = ctx.clip_traj.get("Attack")
    impact_t = _row_E20(ctx)
    feet_y = ctx.feet_y()
    if not traj or impact_t is None or feet_y is None:
        return None
    # `stages.clips.attackImpactDelaySecs` (E20's value, `impact_t` here) is
    # SCALED -- clips.impact() applies timing.scale_time before recording it
    # -- but `<Attack>.traj.json` holds the RAW, unscaled sample times poses.py
    # wrote (kfs.write is what scales, and it never touches the .traj.json
    # sidecar). metrics.impact_height matches samples with `abs(t - impact_t)
    # < 1e-6`, so comparing a scaled t against raw sample times finds nothing
    # and returns inf for any character whose cadence != 1.0 (REF_HEIGHT only) --
    # descale back to raw seconds first: scale_time divides by cadence, so
    # multiplying by cadence is its inverse. A clip built at its own
    # --time-scale is descaled by that instead (timing.authored_time).
    raw_impact_t = timing.authored_time(_dig(ctx.m, "stages.clips.items.Attack"), impact_t, ctx.m["height_studs"])
    v = metrics.impact_height(traj, raw_impact_t, feet_y)
    return None if v == float("inf") else v


def _row_E22(ctx):
    return _dig(ctx.m, "stages.clips.clip_names")


def _row_E23(ctx):
    return _dig(ctx.m, "stages.wire.result")


def _row_E24(ctx):
    return _dig(ctx.eval_prior, "wire.walk_probe")


def _row_E25(ctx):
    return _dig(ctx.m, "stages.wire.attack_capture_media_id")


def _row_E26(ctx):
    return _dig(ctx.m, "stages.record.result")


def _clips_unregistered(m):
    """True when `stages.clips.items` exist and at least one is not yet
    `registration.state == "registered"` (a clip binds through
    `register_media`/`finalize_media_registration` MCP payloads, not a real
    synchronous import, so `clips registered` -- the orchestrator's own
    follow-up once it has the finalized Genvid media id -- is what moves a
    clip past "payload_written"). Empty/absent items reads False here, same
    as no clips stage at all -- this only fires once bind() has actually run
    for at least one clip. Duplicated from manifest.py's own
    `_clips_done`/`_clips_registration_states` rather than imported: this
    module's own docstring rules out importing another stage module so it
    stays standalone regardless of which ones exist -- manifest.py's stage
    ORDER is exactly what makes it one."""
    items = _dig(m, "stages.clips.items")
    if not isinstance(items, dict) or not items:
        return False
    return any(not isinstance(it, dict) or (it.get("registration") or {}).get("state") != "registered"
              for it in items.values())


def _row_E27(ctx):
    # DELIBERATE EXCEPTION to this module's own "no evidence -> FAIL(missing)"
    # rule (see the module docstring): an unregistered clip is not missing
    # evidence, it is evidence this row cannot honestly evaluate yet -- the
    # provenance graph's real node count is meaningless while a clip's media
    # id is still a placeholder in an unrun MCP payload. Forcing this value to
    # None ALONE would still read FAIL under the gate below; the gate itself
    # is turned off for exactly this case (see the E27 `add()` call), which is
    # what actually yields PEND.
    if _clips_unregistered(ctx.m):
        return None
    if ctx.provenance is None:
        return None
    nodes = ctx.provenance.get("nodes") if isinstance(ctx.provenance, dict) else None
    return len(nodes) if isinstance(nodes, list) else None


def _row_E28(ctx):
    return _dig(ctx.m, "stages.wire.hand_tuned")


def _row_E29(ctx):
    """The attested USD spend across every ingest record, or None when there is
    none (every manifest written before ingest records existed reads PEND). It is
    a floor: unobserved and non-USD records are not in it (see _cost_detail)."""
    usd = ctx.cost_totals["usd"]
    return float(usd) if usd is not None else None


def _cost_detail(ctx):
    detail = dict(ctx.cost_totals)
    detail["usd"] = float(detail["usd"]) if detail["usd"] is not None else None
    return detail


def _bound_media_count(m):
    return sum(1 for e in m.get("stages", {}).values() if isinstance(e, dict) and e.get("media_id"))


def _row_E27_check(m):
    need = 1 + _bound_media_count(m)
    return lambda v: v is not None and v >= need


# `Humanoid.HipHeight` is a single-precision float; the `HipHeightStuds` attribute
# it is assigned from is a double. wire.luau reports `hip` (read back off the
# attribute) beside `expected_hip = hum.HipHeight`, so on a CORRECTLY wired character
# the two differ in the last bits -- 30.150000382214785 in, 30.149999618530273 back
# -- and an exact == failed this gate on every one of them. A relative 1e-6
# forgives the float32 round-trip (at most ~6e-8 relative) and nothing else: an
# engine clamp, a stale attribute or a rescale after ground-fit moves HipHeight by
# studs, not by bits.
HIP_READBACK_TOL = 1e-6


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _wire_all_true(v):
    if not isinstance(v, dict) or not v:
        return None
    checks = []
    if "hip" in v and "expected_hip" in v:
        hip, expected = v["hip"], v["expected_hip"]
        if _is_number(hip) and _is_number(expected):
            checks.append(math.isclose(hip, expected, rel_tol=HIP_READBACK_TOL, abs_tol=HIP_READBACK_TOL))
        else:
            checks.append(hip == expected)
    # rigTypeR15 and noAnimationController are self-check keys: an R6
    # Humanoid loads an R15 bone KeyframeSequence and never advances it, and an
    # AnimationController left beside the Humanoid stops BOTH Animators advancing
    # (both witnessed 2026-09-04 -- together they are the dead treadmill). A wire
    # result predating them contributes no check for them rather than a false
    # PASS on a key that is not there; the keys are present on every result the
    # current wire.luau prints.
    for k in ("primaryAxisCorrect", "automaticScalingDisabled", "fallStatesDisabled",
              "rigTypeR15", "noAnimationController"):
        if k in v:
            checks.append(bool(v[k]))
    return all(checks) if checks else None


def _walk_probe_check(v):
    if not isinstance(v, dict):
        return None
    travel = v.get("travel")
    falls = v.get("falls")
    tilt = v.get("maxTilt")
    if travel is None or falls is None or tilt is None:
        return None
    return travel >= 25 and falls == 0 and tilt <= 5


def _no_hand_tuned(v):
    if v is None:
        return None
    return len(v) == 0


def build_rows(ctx):
    """One dict per eval-matrix row: id, stage, judge, gate, value, threshold_desc, pass."""
    rows = []

    def add(row_id, stage, metric_desc, judge, gate, evidence, get_fn, check_fn, threshold_desc,
            readings_fn=None):
        value = get_fn(ctx)
        if judge != "auto":
            # human / capture rows: the runner reports presence, never a verdict.
            passed = None
        elif value is None:
            passed = False if gate else None
        else:
            passed = bool(check_fn(value))
        row = {
            "id": row_id, "stage": stage, "metric": metric_desc, "judge": judge, "gate": gate,
            "evidence": evidence, "value": value, "threshold": threshold_desc, "pass": passed,
        }
        if readings_fn is not None:
            # A row whose value could honestly be read more than one way carries
            # the other readings beside it. They are shown, never scored: `value`
            # and `pass` are unchanged by anything in here.
            row["readings"] = readings_fn(ctx)
        rows.append(row)

    add("E1", "plate", "limb gaps", "auto", False, "stages.plate.gaps_ok", _row_E1,
        _truthy, "no touching limbs")
    add("E2", "plate", "approval", "human", False, "stages.plate.media_id",
        lambda c: _dig(c.m, "stages.plate.media_id"), _truthy, "one plate approved")
    add("E3", "mesh", "triangle count", "auto", True, "stages.mesh.report.tris_out", _row_E3, _le(20000), "<= 20000")
    add("E3b", "rig", "R15 triangle count (post-rig)", "auto", True, "stages.rig.report.tris_r15",
        _row_E3b, _le(20000), "<= 20000 (vendors re-mesh; measured on the exported R15)")
    add("E4", "mesh", "shells", "auto", False, "stages.mesh.report.shells", _row_E4, _eq(1), "== 1 (not gated)")
    add("E5", "mesh", "base-color texture present", "auto", True, "mesh.has_basecolor", _row_E5, _truthy, "true")
    # %.3f, not %.2f: the calibrated threshold is 0.389 and printing ">= 0.39"
    # would state a number the gate does not use.
    add("E6", "mesh", "silhouette IoU vs plate", "auto", True, "mesh.silhouette_iou", _row_E6,
        _ge(CALIBRATION["E6"]["value"]), ">= %.3f%s" % (CALIBRATION["E6"]["value"], "" if CALIBRATION["E6"]["calibrated"] else " (UNCALIBRATED, Step 7)"))
    add("E7", "rig", "bone count", "auto", True, "stages.rig.report.bones", _row_E7, _eq(16), "== 16")
    add("E8", "rig", "unweighted vertex fraction", "auto", True, "stages.rig.report.unweighted_frac", _row_E8, _le(0.01), "<= 0.01")
    add("E9", "rig", "root offset from torso", "auto", True, "stages.rig.report.root_offset", _row_E9, lambda v: v > 0.2, "> 0.2")
    add("E10", "rig", "shoulder ratio", "auto", True, "eval.rig.shoulder_ratio", _row_E10,
        _ge(CALIBRATION["E10"]["value"]), ">= %.2f%s" % (CALIBRATION["E10"]["value"], "" if CALIBRATION["E10"]["calibrated"] else " (UNCALIBRATED, Step 7)"))
    add("E10b", "rig", "skeleton fit (shoulder sep / span)", "auto", True,
        "stages.rig.report.shoulder_sep_frac", _row_E10b, _ge(CALIBRATION["E10b"]["value"]),
        ">= %.2f (offline, before any Studio step)" % CALIBRATION["E10b"]["value"])
    add("E10c", "rig", "skinning L/R symmetry", "auto", False,
        "stages.rig.report.symmetry_min_frac", _row_E10c, _ge(CALIBRATION["E10c"]["value"]),
        ">= %.2f%s" % (CALIBRATION["E10c"]["value"],
                       "" if CALIBRATION["E10c"]["calibrated"] else " (UNCALIBRATED, advisory)"))
    add("E11", "rest", "dump complete/orthonormal", "auto", True, "stages.rest.result", _row_E11, _all_true, "all pass")
    # The HumanoidRootPart the hip is measured against is sized from BODY HEIGHT
    # (0.15 x height, groundfit.root_box) rather than from spine spacing: the old
    # 2 x (UpperTorso.Y - LowerTorso.Y) rule read a skeleton property, so a
    # Mixamo-convention rig whose Spine2 maps to UpperTorso got a 22-stud box on
    # a 50-stud body and failed this gate at 0.234 with feet that were fine
    # (witnessed 2026-09-04). Same rig, same feet, 0.38 under the new rule.
    # That change FLIPS leg C's verdict, so the row carries every reading it could
    # have been scored on -- the applied hip, the sole offset, and the superseded
    # spine-spacing hip -- printed under the row and written into eval.json.
    add("E12", "groundfit", "HipHeight fraction of height", "auto", True, "stages.groundfit.result.hipHeight", _row_E12,
        _between(0.3, 0.6), "0.3 <= hip/height <= 0.6 (rootSize from 0.15 x height, not spine spacing)",
        readings_fn=_row_E12_readings)
    # E13 is the settle loop's exit test, so it reads a gap only when the probe
    # stood the rig at the height a VERIFICATION settle measured in Play
    # (groundfit -> settle -> sethip -> settle -> probe_feet); posed at the hip
    # instead it reads the hover constant back and passes without verifying.
    # E14 is PEND until the vertex read itself happens in Play, which waits on
    # the experience's Mesh & Image API setting -- in Edit the far read is the
    # close read again (RenderFidelity does not change vertex data, and the pose
    # is held). It was PEND on all three bake-off legs for that reason.
    add("E13", "groundfit", "feet grounded, close LOD", "auto", False, "eval.groundfit.probe_close", _row_E13,
        _between(-0.5, 0.5), "-0.5 <= gap <= 0.5 studs, at the measured settled HRP height")
    add("E14", "groundfit", "feet grounded, far LOD", "auto", False, "eval.groundfit.probe_far", _row_E14,
        _between(-1.0, 1.0), "-1.0 <= gap <= 1.0 studs, measured in Play (PEND until the Mesh & Image API is on)")
    add("E15", "clips", "Walk cadence (cycle seconds)", "auto", True, "eval.clips.Walk.cycle_seconds", _row_E15,
        _ge(2.0), ">= 2.0 s")
    add("E16", "clips", "Walk foot lift", "auto", True, "eval.clips.Walk.foot_lift", _row_E16,
        lambda v: v >= 0.03 * ctx.m["height_studs"], ">= 0.03 x height")
    # E18's 0.25 threshold is a discriminator, not an arbitrary round number:
    # a library-authored walk measured 0.042 knee twist against 0.25-0.31 for
    # an archive retarget of the same motion (2026-09-04 bake-off findings).
    add("E17", "clips", "Walk hip twist", "auto", True, "eval.clips.Walk.hip_twist_deg", _row_E17, _le(25.0), "<= 25 deg")
    add("E18", "clips", "Walk knee twist fraction", "auto", True, "eval.clips.Walk.knee_twist_frac", _row_E18, _le(0.25), "<= 0.25")
    add("E19", "clips", "no slide (treadmill)", "auto", True, "stages.clips.treadmill_scaled", _row_E19,
        _le(0.10), "post-scale stride within 10% of walkSpeed")
    # attackImpactDelaySecs (v) is SCALED (clips.impact() applies
    # timing.scale_time); clip_poses["Attack"]["clip_seconds"] is the RAW,
    # unscaled duration poses.py wrote -- comparing a scaled t against a raw
    # upper bound makes this gate unpassable for any character taller than
    # REF_HEIGHT (e.g. 0.2 < 2.0 < 1.1 is False at 50 studs). Compare against
    # stages.clips.items.Attack.scaled_seconds instead, the same scaled
    # duration transfer() already recorded alongside the raw one.
    add("E20", "clips", "attack impact defined", "auto", True, "stages.clips.attackImpactDelaySecs", _row_E20,
        lambda v: 0.2 < v < (_dig(ctx.m, "stages.clips.items.Attack.scaled_seconds") or float("inf")) - 0.1,
        "0.2s < t < scaled clip_seconds - 0.1s")
    add("E21", "clips", "attack reaches the ground", "auto", True, "eval.clips.Attack.impact_height", _row_E21,
        _le(3.0), "<= 3 studs")
    add("E22", "clips", "naming law", "auto", True, "file name", _row_E22,
        lambda v: isinstance(v, list) and v and all(_no_brand(n) for n in v), "no brand word")
    add("E23", "wire", "recipe applied", "auto", True, "stages.wire.result", _row_E23, _wire_all_true, "all true")
    add("E24", "wire", "spawns and walks", "auto", True, "eval.wire.walk_probe", _row_E24, _walk_probe_check,
        "travel >= 25, falls == 0, tilt <= 5deg")
    add("E25", "wire", "head looks down at players", "capture", False, "cast_member_image params.stage=attack-capture",
        _row_E25, _truthy, "head pitch >= 20 deg at impact")
    add("E26", "record", "conformance", "auto", True, "stages.record.result", _row_E26, _eq("conformant"), "conformant")
    # gate is False, not the usual True, exactly while a clip is unregistered
    # add()'s only route to PEND for an "auto" row is value is None
    # with gate False, so both the value getter (_row_E27) and this gate read
    # the same registration state, or an unregistered clip would read
    # FAIL(missing) instead of the honest "not yet measured".
    add("E27", "record", "provenance graph complete", "auto", not _clips_unregistered(ctx.m),
        "provenance.json", _row_E27, _row_E27_check(ctx.m), ">= 1 + bound media rows")
    add("E28", "record", "no hand-tuned values", "auto", False, "stages.record", _row_E28, _no_hand_tuned, "empty")
    add("E29", "any", "cost", "auto", False, "eval.cost", _row_E29,
        lambda v: v <= 25.0, "a full character <= $25 attested USD; a static prop <= $6 each")
    return rows


def _print_table(rows):
    widths = {"id": 3, "stage": 10, "metric": 30, "judge": 7, "value": 14, "result": 6}
    header = "%-3s %-10s %-30s %-7s %-14s %-6s" % ("ID", "Stage", "Metric", "Judge", "Value", "Result")
    print(header)
    print("-" * len(header))
    for r in rows:
        if r["pass"] is True:
            result = "PASS"
        elif r["pass"] is False:
            result = "FAIL" if r["value"] is not None else "FAIL(missing)"
        else:
            result = "PEND"
        val = r["value"]
        val_s = ("%.4g" % val) if isinstance(val, float) else str(val)
        if len(val_s) > 14:
            val_s = val_s[:13] + "…"
        print("%-3s %-10s %-30s %-7s %-14s %-6s" % (r["id"], r["stage"], r["metric"][:30], r["judge"], val_s, result))
        for line in _reading_lines(r):
            print(line)


def _reading_lines(row):
    """The `readings` block under a row, one line per reading, or nothing.

    A row that could be read more than one way prints every reading it has --
    scored one marked, the rest plainly -- so a verdict that depends on which
    number was chosen shows the numbers it did not choose (bake-off findings,
    correction after the advisor pass, 2026-09-04)."""
    readings = row.get("readings")
    if not isinstance(readings, dict):
        return []
    gated = readings.get("gated")
    lines = []
    for name in sorted(k for k in readings if k != "gated" and not k.endswith("_frac")):
        value, fraction = readings.get(name), readings.get(name + "_frac")
        if value is None:
            lines.append("      %-18s not measured" % name)
            continue
        lines.append("      %-18s %8.3f studs  %6.3f of height%s"
                     % (name, value, fraction, "   <- gated" if name == gated else ""))
    return lines


def run(m, stage=None):
    ctx = Ctx(m)
    rows = build_rows(ctx)
    if stage:
        rows = [r for r in rows if r["stage"] == stage]
    _print_table(rows)

    def clip_block(clip):
        return {
            "cycle_seconds": _row_E15(ctx) if clip == "Walk" else None,
            "foot_lift": _row_E16(ctx) if clip == "Walk" else None,
            "hip_twist_deg": _row_E17(ctx) if clip == "Walk" else None,
            "knee_twist_frac": _row_E18(ctx) if clip == "Walk" else None,
            "impact_height": _row_E21(ctx) if clip == "Attack" else None,
        }

    # Start from whatever eval.json already held (in particular the groundfit
    # gap_*/probe_* keys and wire.walk_probe, which only studio.py's probes populate) and
    # overlay only the keys this module itself computes -- never blank a probe result
    # this run didn't re-measure.
    result = dict(ctx.eval_prior)
    result["mesh"] = {"has_basecolor": _row_E5(ctx), "silhouette_iou": _row_E6(ctx)}
    result["rig"] = {"shoulder_ratio": _row_E10(ctx), "shoulder_sep_frac": _row_E10b(ctx),
                     "symmetry_min_frac": _row_E10c(ctx)}
    result["clips"] = {clip: clip_block(clip) for clip in CLIP_NAMES}
    result["cost"] = _cost_detail(ctx)
    result.setdefault("groundfit", {})
    result.setdefault("wire", {})
    result.setdefault("record", {})
    result["rows"] = rows
    (ctx.out / "eval.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str))

    failed_gates = [r["id"] for r in rows if r["gate"] and r["pass"] is not True]
    return result, failed_gates


def register(sub):
    p = sub.add_parser("eval", help="print/write the eval-matrix table (eval.json)")
    p.add_argument("--manifest", required=True)
    p.add_argument("--stage", default=None, help="restrict to one stage's rows")
    p.set_defaults(func=_cli)


def _cli(args):
    import manifest
    m = manifest.load(args.manifest)
    _result, failed = run(m, stage=args.stage)
    if failed:
        print("FAILED gates: %s" % ", ".join(failed))
        return 1
    return 0
