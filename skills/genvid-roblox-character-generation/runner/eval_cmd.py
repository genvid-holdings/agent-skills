"""`runner eval` -- prints and writes the eval-matrix table (plan
docs/superpowers/plans/2026-09-02-rdc-week-runner.md, "Eval matrix" section, rows E1-E29 (E25 retired); E30-E32 are the bench gates).

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
  - `<out_dir>/clips/<Clip>.bench.json`: the `bench_clip` timeline studio.py
    files beside the clip item's `bench` record (which carries `soleY` and, from
    benches that report it, `restAnkleY`), read by metrics.bench_readings for
    E30-E32.
  - `<out_dir>/eval.json`: this module's own prior output, re-read at the start
    of every run so `groundfit.gap_close` / `groundfit.gap_far`, the whole
    `groundfit.probe_close` / `groundfit.probe_far` results E13 and E14 read
    their conditions off, and `wire.walk_probe` -- all written by studio.py's
    probe_feet / probe_walk ingests directly into this file, never computed here
    -- survive a re-run instead of being wiped back to null. Every other top-level key (`mesh`, `rig`,
    `clips`, `bench`, `cost`) is this module's own and is recomputed fresh each run. Note
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
import request
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

CLIP_NAMES = ("Walk", "Attack", "Slam")

# bench_clip gates (rows E30-E32), as fractions of height_studs, ruled
# 2026-09-24. A title overrides any of them, and any clip's motion class, under
# the manifest's top-level `bench_gates` ({"foot_contact_frac": ..., "motion":
# {"Crawl": "travel"}}). Measured on one 70-stud character's benches
# (2026-09-23/24), six clips accepted on sight and five rejected:
#   foot_contact_frac 0.029 (2.03 studs): the accepted in-place clips' lowest
#     soles read -0.54..-0.08; the two rejected for floating read +8.32 and +6.68.
#   foot_contact_travel_frac 0.06 (4.20): the accepted walk's lowest sole reads
#     +0.271 (+0.004 of height) over every frame; the walk rejected for landing
#     high and then sinking read -5.251 (-0.075 of height).
#   root_travel_max_frac 0.25 (17.5): the accepted in-place clips' hips travelled
#     4.19..13.63 at most; the one rejected for sliding, 62.25.
#   root_travel_end_frac 0.10 (7.0): the accepted ones ended 0.01..5.73 from
#     their start; the slide ended 62.25 away.
#   fall_end_max_frac 0.10 (7.0): the accepted fall's lowest end point read
#     +4.44; the bench samples bones inside the body, so a body lying on the
#     ground reads above it. The rejected fall read -26.11 (sunk).
BENCH_GATES = {
    "foot_contact_frac": 0.029,         # ruled 2026-09-24: in-place lowest sole within +-0.029 x height
    "foot_contact_travel_frac": 0.06,   # ruled 2026-09-24: travel lowest sole within +-0.06 x height
    "root_travel_max_frac": 0.25,       # ruled 2026-09-24: in-place hips travel <= 0.25 x height
    "root_travel_end_frac": 0.10,       # ruled 2026-09-24: in-place end pose <= 0.10 x height from start
    "fall_end_max_frac": 0.10,          # ruled 2026-09-24: fall end lowest point -0.029 .. +0.10 x height
}
# How a clip moves, which decides the gates it answers to (ruled 2026-09-24):
#   in_place  plays where it stands: foot contact and root travel (E30, E31)
#   travel    a locomotion cycle: foot contact in its own, looser band (E30);
#             no root travel, since it is meant to move
#   fall      ends on the ground: never below it, and the end pose on it (E30, E32)
# A catalog clip's class is here; a declared key's is its declaration's
# `motion`; anything else is in_place, the strictest.
MOTIONS = ("in_place", "travel", "fall")
# E13's gate: the rest pose's lowest vertex within this many studs of the plane
# with the rig stood at its measured settled height. The ground-fit settle
# loop's verification (studio.SETTLE_VERIFY_TOL) reads the same gap at the root
# and uses this number, so the loop never verifies a fit this row fails.
E13_GAP_TOL = 0.5
CATALOG_MOTION = {"Walk": "travel", "Death": "fall"}
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
        self.gates = bench_gates(m)
        self.bench = _bench_verdicts(self)
        self.clip_poses = {}
        self.clip_traj = {}
        for clip in CLIP_NAMES:
            self.clip_poses[clip] = _load_json(self.out / "clips" / ("%s.poses.json" % clip))
            self.clip_traj[clip] = _load_json(self.out / "clips" / ("%s.traj.json" % clip))

    def feet_y(self):
        """The sole plane in the rig's own frame, the frame rest.json and the
        clip trajectories are in. groundfit measures the plane (`feetPlane`)
        and the hips (`lowerTorsoY`) in the WORLD, where the imported rig sits
        wherever the place put it; the hips' rest height in the rig frame
        (rest.json) carries the plane across. None when any of the three is
        missing: a world plane compared with rig-frame heights reads hundreds
        of studs off and passes any gate."""
        plane = _dig(self.m, "stages.groundfit.result.feetPlane")
        hips = _dig(self.m, "stages.groundfit.result.lowerTorsoY")
        if plane is None or hips is None or not self.rest or "LowerTorso" not in self.rest:
            return None
        return metrics._world_y(self.rest, "LowerTorso") - (float(hips) - float(plane))


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


def _verification_miss(ctx):
    miss = _dig(ctx.m, "stages.groundfit.verification_miss")
    return miss if isinstance(miss, dict) and _is_number(miss.get("gap")) else None


def _row_E13(ctx):
    """The close-LOD probe's gap, or the ground-fit settle's recorded miss.

    A verification settle that missed the sole offset stops the loop at ingest
    (studio.SETTLE_VERIFY_TOL), and probe_feet then has no measured height to
    stand the rig at. The miss is the same gap read at the root, so the row
    scores it rather than reading PEND; a later verified settle clears it."""
    miss = _verification_miss(ctx)
    if miss is not None:
        return miss["gap"]
    return _probe_gap(ctx, "close")


def _row_E13_readings(ctx):
    """Both numbers behind a recorded settle miss, or None (no readings block)."""
    miss = _verification_miss(ctx)
    if miss is None:
        return None
    height = float(ctx.m["height_studs"])
    bottom, sole = miss.get("settledBottom"), miss.get("soleOffset")
    return {"settled_bottom": bottom, "settled_bottom_frac": None if bottom is None else bottom / height,
            "sole_offset": sole, "sole_offset_frac": None if sole is None else sole / height,
            "gated": None}


def _row_E14(ctx):
    return _probe_gap(ctx, "far", require_play=True)


def _clip_metric(ctx, clip, fn):
    poses = ctx.clip_poses.get(clip)
    if not poses or "frames" not in poses:
        return None
    return fn(poses)


def _row_E15(ctx):
    """Walk cycle length as the game PLAYS it. `<Clip>.poses.json`'s frame
    `t`s are raw, authored seconds (kfs.write, not transfer(), applies the
    build's scale), so the raw cycle is scaled the way the built Walk plays
    (its own time_scale when `clips build` set one, else the height stretch),
    then divided by `stages.clips.animSpeedScale`, the speed the game plays
    the walk at, when the clip stage records one. The gate grows with the
    square root of the height (`E15_LIMIT_S` at `E15_REF_HEIGHT`, the cadence
    law): a clip authored for a giant and built at time_scale 1 reads its
    authored length until the played speed is applied."""
    poses = ctx.clip_poses.get("Walk")
    if not poses:
        return None
    times = [f["t"] for f in poses.get("frames", [])]
    if not times:
        return None
    raw = metrics.cycle_seconds(times)
    # as the built Walk plays: its own time_scale when `clips build` set one
    built = timing.clip_time(_dig(ctx.m, "stages.clips.items.Walk"), raw, ctx.m["height_studs"])
    speed = _dig(ctx.m, "stages.clips.animSpeedScale")
    return built if speed is None else built / float(speed)


# E15: the played walk cycle is at least E15_LIMIT_S at E15_REF_HEIGHT studs,
# scaled by sqrt(height / E15_REF_HEIGHT) (the sqrt-height cadence law).
E15_LIMIT_S = 2.0
E15_REF_HEIGHT = 50.0


def e15_limit(height_studs):
    return E15_LIMIT_S * math.sqrt(float(height_studs) / E15_REF_HEIGHT)


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
    """The Attack clip's own impact delay (`items.Attack.impact_delay_secs`,
    clips.impact() records one per clip). The stages.clips mirror of the clip
    measured last stands in only where it can be the Attack clip's: it names
    Attack (or no clip, as before the mirror recorded one) on a manifest
    measured before per-clip impacts, or the title has no Attack item at all.
    A re-transferred Attack beside another clip's mirror reads None."""
    st = _dig(ctx.m, "stages.clips") or {}
    attack = (st.get("items") or {}).get("Attack")
    if attack is not None and attack.get("impact_delay_secs") is not None:
        return attack["impact_delay_secs"]
    if attack is None or st.get("attackImpactClip") in (None, "Attack"):
        return st.get("attackImpactDelaySecs")
    return None


def _row_E21(ctx):
    """How far from the sole plane the Slam clip's striking limb makes CONTACT,
    in studs (+ above, - through the ground): the lowest vertex skinned to the
    striker or a bone under it, at the strike frame, as `clips contact`
    measured it (`items.Slam.contact.lowest_y`, rig frame), less the sole plane
    in the rig frame (`Ctx.feet_y`). The measurement names the rig file, and
    the sha256 of that file, rest.json and the Slam's poses doc; it is read
    only while all three still match the files on disk. None otherwise, or when
    it was never measured or the plane cannot be placed; E21 is a gate only for
    a title with a Slam clip (`_has_slam`), so there a missing or stale
    measurement reads FAIL (missing)."""
    item = _dig(ctx.m, "stages.clips.items.Slam") or {}
    c = item.get("contact")
    feet_y = ctx.feet_y()
    if not c or feet_y is None:
        return None
    files = ((c.get("rig_mesh"), c.get("rig_sha256")), (str(ctx.out / "rest.json"), c.get("rest_sha256")),
             (item.get("poses"), c.get("poses_sha256")))
    for path, sha in files:
        if not path or not sha or not Path(path).is_file() or request.sha256_of(Path(path)) != sha:
            return None
    return float(c["lowest_y"]) - feet_y


# E21: the slam's contact is within the in-place foot-contact band of the sole
# plane either way, +- `bench_gates.foot_contact_frac` x height (0.029, the band
# the bench holds a planted sole to, E30). A PROPOSAL, not a ruling on the number.
def e21_limit(m):
    return foot_band(m, "in_place")


def _has_slam(m):
    return _dig(m, "stages.clips.items.Slam") is not None


def _row_E22(ctx):
    return _dig(ctx.m, "stages.clips.clip_names")


def _row_E23(ctx):
    return _dig(ctx.m, "stages.wire.result")


def _row_E24(ctx):
    return _dig(ctx.eval_prior, "wire.walk_probe")


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


def bench_gates(m):
    """BENCH_GATES with the title's `bench_gates` overrides applied. Each override
    is a number strictly between 0 and 1 (a fraction of height) and names a
    known gate; anything else is refused by name."""
    overrides = m.get("bench_gates") or {}
    if not isinstance(overrides, dict):
        raise ValueError("bench_gates: must be an object of gate fractions and `motion`, got %r" % (overrides,))
    gates = dict(BENCH_GATES)
    for k, v in overrides.items():
        if k == "motion":
            if not isinstance(v, dict):
                raise ValueError("bench_gates.motion: an object of {clip: class}, got %r" % (v,))
            continue
        if k not in BENCH_GATES:
            raise ValueError("bench_gates.%s: not a bench gate (one of %s, or motion)"
                             % (k, ", ".join(sorted(BENCH_GATES))))
        if not _is_number(v) or not 0 < v < 1:
            raise ValueError("bench_gates.%s: a fraction of height strictly between 0 and 1, got %r" % (k, v))
        gates[k] = float(v)
    return gates


def foot_band(m, motion):
    """The +- band, in studs, the lowest sole of a clip of this motion must stay
    within (a fall's is its never-below floor)."""
    gates = bench_gates(m)
    frac = gates["foot_contact_travel_frac"] if motion == "travel" else gates["foot_contact_frac"]
    return frac * float(m["height_studs"])


def clip_motion(m, clip):
    """The clip's motion class: the title's `bench_gates.motion` override, then a
    declared key's `motion`, then the catalog's, then in_place."""
    override = ((m.get("bench_gates") or {}).get("motion") or {}).get(clip)
    entry = _dig(m, "stages.clips.declared.%s" % clip)
    declared = entry.get("motion") if isinstance(entry, dict) else None
    motion = override or declared or CATALOG_MOTION.get(clip) or "in_place"
    if motion not in MOTIONS:
        raise ValueError("clip %s: motion %r is none of %s" % (clip, motion, ", ".join(MOTIONS)))
    return motion


def _bench_timeline(m, clip, bench):
    canonical = Path(m["out_dir"]) / "clips" / ("%s.bench.json" % clip)
    for p in (bench.get("timeline_file"), canonical):
        if p and Path(p).is_file():
            return _load_json(p)
    return None


# A bench is read only when it is HELD AT THE CLIP'S END: frozen, with its last
# sampled TimePosition within BENCH_END_SLACK sample intervals of the clip's
# length. The sampler reads every 0.25 s of wall time (0.25 x speed of track
# time), and the freeze lands within three frames of the end, so one sample
# interval admits every freeze that reached the end while refusing the
# 0.76-1.01 s shortfalls the wall-time freeze produced (7 of 10 benches,
# witnessed 2026-09-24; the three that reached the end were 0.029-0.049 short).
BENCH_SAMPLE_SECONDS = 0.25
BENCH_END_SLACK = 1
# Limits are inclusive, compared with this much slack in studs so a reading of
# exactly the limit is not failed on float noise.
BENCH_LIMIT_EPS = 1e-6


def _bench_unusable(bench, timeline):
    """Why a bench cannot be judged, or None when it can."""
    if not isinstance(bench, dict):
        return "no bench recorded"
    if bench.get("frozen") is not True:
        # endedPlaying is track.IsPlaying when the bench stopped sampling.
        if bench.get("endedPlaying") is True:
            return "not frozen: the bench's max wait ran out with the track still playing (raise --max-wait)"
        if bench.get("endedPlaying") is False:
            return "not frozen: the track ran out and blended back to the bind pose"
        return "not frozen"
    if not timeline:
        return "no timeline"
    length = bench.get("length")
    last_tp = bench.get("lastTp", timeline[-1].get("tp"))
    if not _is_number(length) or not _is_number(last_tp):
        return "no clip length or last TimePosition"
    slack = BENCH_END_SLACK * BENCH_SAMPLE_SECONDS * float(bench.get("speed") or 1)
    if last_tp < length - slack:
        return "held at TimePosition %.3f of %.3f, %.3f s short of the end" % (last_tp, length, length - last_tp)
    return None


def judge_readings(m, clip, motion, readings):
    """`(checks, breaches)` for bench readings against the gates of `motion`:
    `checks` maps each gate onto True/False (None when unmeasured), `breaches`
    names each failed check with its measured value and inclusive limit."""
    height = float(m["height_studs"])
    gates = bench_gates(m)
    tol = gates["foot_contact_frac"] * height
    band = foot_band(m, motion)
    limits = {
        "foot_contact": ("lowest_sole", -band, band),
        "root_travel": ("root_travel_max", None, gates["root_travel_max_frac"] * height),
        "root_travel_end": ("root_travel_end", None, gates["root_travel_end_frac"] * height),
        "never_below": ("lowest_point", -tol, None),
        "fall_end": ("end_lowest", -tol, gates["fall_end_max_frac"] * height),
    }
    names = {"in_place": ("foot_contact", "root_travel", "root_travel_end"),
             "fall": ("never_below", "fall_end"),
             "travel": ("foot_contact",)}[motion]
    checks, breaches = {}, []
    for name in names:
        key, lo, hi = limits[name]
        v = readings.get(key) if readings else None
        if v is None:
            checks[name] = None
            continue
        ok = (lo is None or v >= lo - BENCH_LIMIT_EPS) and (hi is None or v <= hi + BENCH_LIMIT_EPS)
        checks[name] = ok
        if not ok:
            breaches.append("%s %s: %s %.2f studs (%.3f of height), limit %s"
                            % (clip, name, key, v, v / height,
                               " .. ".join("%.2f" % b if b is not None else "-" for b in (lo, hi))))
    return checks, breaches


def bench_verdict(m, clip):
    """One benched clip against the bench gates: `{motion, readings, checks,
    breaches, unusable}`. `unusable` says why the bench cannot be judged (none
    recorded, not frozen, or held short of the clip's end); then `readings` is
    None and every check is None. Otherwise `readings` is metrics.bench_readings
    and `checks`/`breaches` are judge_readings'."""
    motion = clip_motion(m, clip)
    bench = _dig(m, "stages.clips.items.%s.bench" % clip)
    timeline = _bench_timeline(m, clip, bench) if isinstance(bench, dict) else None
    unusable = _bench_unusable(bench, timeline)
    readings = None
    if unusable is None:
        readings = metrics.bench_readings(timeline, bench.get("soleY"), bench.get("restAnkleY"),
                                          bench.get("extrema"))
        if readings is None:
            unusable = "timeline has no played samples or no sole plane"
    checks, breaches = judge_readings(m, clip, motion, readings)
    return {"motion": motion, "readings": readings, "checks": checks, "breaches": breaches,
            "unusable": unusable}


def _bench_verdicts(ctx):
    items = _dig(ctx.m, "stages.clips.items")
    if not isinstance(items, dict):
        return {}
    return {clip: bench_verdict(ctx.m, clip) for clip in sorted(items)}


def _bench_row(ctx, checks, motions):
    """Clips failing any of `checks` (a clip with no usable bench is listed as
    `<clip> (no bench: <why>)`), over the clips whose motion is in `motions`; None when
    no clip is in scope."""
    scoped = {c: v for c, v in ctx.bench.items() if v["motion"] in motions}
    if not scoped:
        return None
    failing = []
    for clip, v in scoped.items():
        results = [v["checks"].get(c) for c in checks if c in v["checks"]]
        if any(r is None for r in results):
            failing.append("%s (no bench: %s)" % (clip, v.get("unusable") or "unmeasured"))
        elif not all(results):
            failing.append(clip)
    return failing


def _bench_readings_fn(keys_by_motion, label=None):
    """Each in-scope clip's gated readings, `{"<clip> <reading>[ <label>]": studs}`;
    `label(ctx, motion)` names the band the reading is held to."""
    def readings(ctx):
        out, height = {"gated": None}, float(ctx.m["height_studs"])
        for clip, v in ctx.bench.items():
            for key in keys_by_motion.get(v["motion"], ()):
                val = (v["readings"] or {}).get(key)
                name = "%s %s" % (clip, key)
                if label is not None:
                    name += " " + label(ctx, v["motion"])
                out[name] = val
                out[name + "_frac"] = None if val is None else val / height
        return out
    return readings


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
    # noCollidingParts: every part but the HumanoidRootPart read back
    # non-colliding and massless; an extra colliding part rests on the ground
    # and holds the body up. singleAssembly: every part's AssemblyRootPart is
    # the HumanoidRootPart. Same rule for a result that predates them.
    for k in ("primaryAxisCorrect", "automaticScalingDisabled", "fallStatesDisabled",
              "rigTypeR15", "noAnimationController", "noCollidingParts", "singleAssembly"):
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
            # A readings function may return None when it has nothing to show;
            # the row then carries no readings block at all.
            readings = readings_fn(ctx)
            if readings is not None:
                row["readings"] = readings
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
    # (groundfit -> wire -> park -> settle -> sethip -> settle -> probe_feet);
    # posed at the hip instead it reads the hover constant back and passes
    # without verifying.
    # E14 is PEND until the vertex read itself happens in Play, which waits on
    # the experience's Mesh & Image API setting -- in Edit the far read is the
    # close read again (RenderFidelity does not change vertex data, and the pose
    # is held). It was PEND on all three bake-off legs for that reason.
    add("E13", "groundfit", "feet grounded, close LOD", "auto", False, "eval.groundfit.probe_close", _row_E13,
        _between(-E13_GAP_TOL, E13_GAP_TOL),
        "-%g <= gap <= %g studs, at the measured settled HRP height (or the settle's recorded miss)"
        % (E13_GAP_TOL, E13_GAP_TOL), readings_fn=_row_E13_readings)
    add("E14", "groundfit", "feet grounded, far LOD", "auto", False, "eval.groundfit.probe_far", _row_E14,
        _between(-1.0, 1.0), "-1.0 <= gap <= 1.0 studs, measured in Play (PEND until the Mesh & Image API is on)")
    add("E15", "clips", "Walk cadence (played cycle seconds)", "auto", True, "eval.clips.Walk.cycle_seconds",
        _row_E15, _ge(e15_limit(ctx.m["height_studs"])),
        ">= %g s x sqrt(height / %g) = %.2f s, the cycle over animSpeedScale"
        % (E15_LIMIT_S, E15_REF_HEIGHT, e15_limit(ctx.m["height_studs"])))
    add("E16", "clips", "Walk foot lift", "auto", True, "eval.clips.Walk.foot_lift", _row_E16,
        lambda v: v >= 0.03 * ctx.m["height_studs"], ">= 0.03 x height")
    # E18's 0.25 threshold is a discriminator, not an arbitrary round number:
    # a library-authored walk measured 0.042 knee twist against 0.25-0.31 for
    # an archive retarget of the same motion (2026-09-04 bake-off findings).
    add("E17", "clips", "Walk hip twist", "auto", True, "eval.clips.Walk.hip_twist_deg", _row_E17, _le(25.0), "<= 25 deg")
    add("E18", "clips", "Walk knee twist fraction", "auto", True, "eval.clips.Walk.knee_twist_frac", _row_E18, _le(0.25), "<= 0.25")
    add("E19", "clips", "no slide (treadmill)", "auto", True, "stages.clips.treadmill_scaled", _row_E19,
        _le(0.10), "post-scale stride within 10% of walkSpeed")
    # the impact delay (v) is SCALED (clips.impact() applies
    # timing.scale_time); clip_poses["Attack"]["clip_seconds"] is the RAW,
    # unscaled duration poses.py wrote -- comparing a scaled t against a raw
    # upper bound makes this gate unpassable for any character taller than
    # REF_HEIGHT (e.g. 0.2 < 2.0 < 1.1 is False at 50 studs). Compare against
    # stages.clips.items.Attack.scaled_seconds instead, the same scaled
    # duration transfer() already recorded alongside the raw one.
    add("E20", "clips", "attack impact defined", "auto", True,
        "stages.clips.items.Attack.impact_delay_secs, else stages.clips.attackImpactDelaySecs", _row_E20,
        lambda v: 0.2 < v < (_dig(ctx.m, "stages.clips.items.Attack.scaled_seconds") or float("inf")) - 0.1,
        "0.2s < t < scaled clip_seconds - 0.1s")
    # a gate only for a title with a Slam clip: without one the row reads PEND
    # (not applicable), and an Attack answers to no ground gate
    add("E21", "clips", "slam reaches the ground", "auto", _has_slam(ctx.m), "eval.clips.Slam.impact_height",
        _row_E21, _between(-e21_limit(ctx.m), e21_limit(ctx.m)),
        "contact within +-%g x height = +-%.2f studs of the sole plane (proposal)"
        % (bench_gates(ctx.m)["foot_contact_frac"], e21_limit(ctx.m)))
    add("E22", "clips", "naming law", "auto", True, "file name", _row_E22,
        lambda v: isinstance(v, list) and v and all(_no_brand(n) for n in v), "no brand word")
    add("E23", "wire", "recipe applied", "auto", True, "stages.wire.result", _row_E23, _wire_all_true, "all true")
    add("E24", "wire", "spawns and walks", "auto", True, "eval.wire.walk_probe", _row_E24, _walk_probe_check,
        "travel >= 25, falls == 0, tilt <= 5deg")
    # E25 is retired (no stage ever wrote its input, stages.wire.attack_capture_media_id;
    # it could only ever report PENDING). The id is left unused; E26-E32 keep their numbers.
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
    # E30-E32 read the bench timelines (`clips bench`) against BENCH_GATES; each
    # names the failing clips, and the readings under it give every clip's number.
    # A row with no clip of its motion class in scope reads PEND.
    fc_scope = ("in_place", "travel", "fall")

    def fc_label(c, motion):
        if motion == "fall":
            return "(>= -%.2f)" % foot_band(c.m, "in_place")
        return "(+-%.2f)" % foot_band(c.m, motion)

    add("E30", "clips", "foot contact (bench)", "auto", _bench_row(ctx, ("foot_contact", "never_below"), fc_scope) is not None,
        "stages.clips.items.<Clip>.bench + <Clip>.bench.json",
        lambda c: _bench_row(c, ("foot_contact", "never_below"), fc_scope), lambda v: len(v) == 0,
        "lowest sole within +-%.3f x height in place, +-%.3f x height travelling; fall: nothing below -%.3f x height"
        % (ctx.gates["foot_contact_frac"], ctx.gates["foot_contact_travel_frac"], ctx.gates["foot_contact_frac"]),
        readings_fn=_bench_readings_fn({"in_place": ("lowest_sole",), "travel": ("lowest_sole",),
                                        "fall": ("lowest_point",)}, label=fc_label))
    add("E31", "clips", "root travel, in-place (bench)", "auto", _bench_row(ctx, ("root_travel", "root_travel_end"), ("in_place",)) is not None,
        "stages.clips.items.<Clip>.bench + <Clip>.bench.json",
        lambda c: _bench_row(c, ("root_travel", "root_travel_end"), ("in_place",)), lambda v: len(v) == 0,
        "hips travel <= %.2f x height, end <= %.2f x height from start"
        % (ctx.gates["root_travel_max_frac"], ctx.gates["root_travel_end_frac"]),
        readings_fn=_bench_readings_fn({"in_place": ("root_travel_max", "root_travel_end")}))
    add("E32", "clips", "fall ends on the ground (bench)", "auto", _bench_row(ctx, ("fall_end",), ("fall",)) is not None,
        "stages.clips.items.<Clip>.bench + <Clip>.bench.json",
        lambda c: _bench_row(c, ("fall_end",), ("fall",)), lambda v: len(v) == 0,
        "lowest end point within -%.3f .. +%.2f x height" % (ctx.gates["foot_contact_frac"], ctx.gates["fall_end_max_frac"]),
        readings_fn=_bench_readings_fn({"fall": ("end_lowest",)}))
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
            "impact_height": _row_E21(ctx) if clip == "Slam" else None,
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
    result["bench"] = ctx.bench
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
