"""Eval-matrix measurements from the runner's own artifacts (rest dump, poses JSON, trajectories).
Pure functions; every threshold lives in eval_cmd.THRESHOLDS, not here."""
import math

import rigtables

def _rot3(entry):
    """A rest-dump entry's 3x3 row-major rotation, or None when the entry is not
    the documented `{"parent":..., "rot": [9], "pos": [3]}` shape."""
    if not isinstance(entry, dict):
        return None
    r, pos = entry.get("rot"), entry.get("pos")
    if not isinstance(r, (list, tuple)) or len(r) != 9:
        return None
    if not isinstance(pos, (list, tuple)) or len(pos) != 3:
        return None
    try:
        r = [float(x) for x in r]
        [float(x) for x in pos]
    except (TypeError, ValueError):
        return None
    return [r[0:3], r[3:6], r[6:9]]

def rest_dump_detail(rest, tol=1e-3):
    """Which R15 bones the dump_rest output is missing, which of its entries are
    malformed (an extra bone's included; both are listed as `missing`), and
    which carry a frame that is not a rotation (`R @ R^T != I` within `tol`, or
    a mirrored frame, `det <= 0`). Every dumped bone is checked, the R15 ones
    and any extra bones the rig carries. Diagnostics for the manifest; the
    booleans the E11 gate reads come from rest_dump_checks."""
    rest = rest if isinstance(rest, dict) else {}
    missing, non_orthonormal, worst = [], [], 0.0
    extras = sorted(b for b in rest if b not in rigtables.R15_BONES)
    for bone in list(rigtables.R15_BONES) + extras:
        r = _rot3(rest.get(bone))
        if r is None:
            missing.append(bone)
            continue
        err = 0.0
        for i in range(3):
            for j in range(3):
                dot = sum(r[i][k] * r[j][k] for k in range(3))
                err = max(err, abs(dot - (1.0 if i == j else 0.0)))
        det = (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
               - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
               + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))
        worst = max(worst, err)
        if err > tol or det <= 0:
            non_orthonormal.append(bone)
    return {"missing": missing, "non_orthonormal": non_orthonormal,
            "max_orthonormality_error": worst}

def rest_dump_checks(rest, tol=1e-3):
    """E11's two named conditions ("dump complete/orthonormal"), COMPUTED.

    Booleans only, deliberately: eval_cmd's E11 predicate is
    `all(bool(x) for x in value.values())`, so an empty missing-list or a 0.0
    error carried in here would read as a FAILING check on a good dump, and a
    list of bone names would read as a passing one on any dump at all. The
    diagnostics live in rest_dump_detail and stay out of the gate's reach."""
    d = rest_dump_detail(rest, tol)
    return {"complete": not d["missing"], "orthonormal": not d["non_orthonormal"]}

def _world_y(rest, bone):
    """World-space Y of `bone`'s rest position.

    `rest[b]["pos"]` is `Bone.CFrame`'s translation, PARENT-relative (Roblox's
    `Bone.CFrame` convention, confirmed against the dump_rest.luau template and
    against a real rest dump: naive accumulation gives feet above head as soon
    as any ancestor bone has a non-identity rotation, which is the normal case
    for a real skeleton). `rest[b]["rot"]` is the matching 3x3 row-major
    rotation, also parent-relative. Compose root-to-leaf: `world = parent_world
    * local`, i.e. `T' = T + R @ p`, `R' = R @ r`.
    """
    chain = []
    b = bone
    while b in rest:
        chain.append(rest[b])
        b = rest[b]["parent"]
    r_acc = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    t_acc = [0.0, 0.0, 0.0]
    for node in reversed(chain):
        r = node["rot"]
        r = [[r[0], r[1], r[2]], [r[3], r[4], r[5]], [r[6], r[7], r[8]]]
        p = node["pos"]
        rp = [sum(r_acc[i][k] * p[k] for k in range(3)) for i in range(3)]
        t_acc = [t_acc[i] + rp[i] for i in range(3)]
        r_acc = [[sum(r_acc[i][k] * r[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return t_acc[1]

def shoulder_ratio(rest, feet_y):
    sh = (_world_y(rest, "LeftUpperArm") + _world_y(rest, "RightUpperArm")) / 2.0
    head = _world_y(rest, "Head")
    return (sh - feet_y) / (head - feet_y)

def _quat_to_axis_angle(q):
    x, y, z, w = q
    w = max(-1.0, min(1.0, w))
    ang = 2.0 * math.acos(w)
    s = math.sqrt(max(1e-12, 1.0 - w * w))
    return (x / s, y / s, z / s), ang

def _yaw_deg(q):
    # rotation about +Y extracted from the quaternion's Y component projection
    (ax, ay, az), ang = _quat_to_axis_angle(q)
    return math.degrees(ang * ay)

def hip_twist_deg(frames):
    return max(abs(_yaw_deg(f["p"]["LowerTorso"])) for f in frames if "LowerTorso" in f["p"])

def knee_twist_frac(frames, bones=("LeftLowerLeg", "RightLowerLeg")):
    twist, total = 0.0, 0.0
    for f in frames:
        for b in bones:
            if b not in f["p"]:
                continue
            (ax, ay, az), ang = _quat_to_axis_angle(f["p"][b])
            twist += abs(ang * ay)      # about the bone's own Y axis
            total += abs(ang)
    return twist / total if total > 1e-9 else 0.0

def foot_lift(traj, bones=("LeftFoot", "RightFoot")):
    best = 0.0
    for b in bones:
        ys = [p[2] for p in traj.get(b, [])]
        if ys:
            best = max(best, max(ys) - min(ys))
    return best

def cycle_seconds(times):
    return float(times[-1] - times[0]) if len(times) > 1 else 0.0

def impact_height(traj, impact_t, feet_y, bones=("LeftFoot", "RightFoot", "LeftHand", "RightHand")):
    best = None
    for b in bones:
        for t, _x, y, _z in traj.get(b, []):
            if abs(t - impact_t) < 1e-6:
                v = y - feet_y
                best = v if best is None else min(best, v)
    return best if best is not None else float("inf")

# bench_clip readings. A timeline sample is {t, tp, hips, head, lfoot, rfoot},
# each point [x, y, z] relative to the anchored HumanoidRootPart; soleY is the
# sole plane (the ground) on the same axes. The feet are ANKLE bones, which sit
# above the sole, so a foot's sole is read as ankle - (restAnkle - soleY): the
# ankle-to-sole distance the bind pose stands on, carried through the clip.
# restAnkle is the lower ankle at rest (a bind pose need not stand both feet at
# one height). A bench that did not report it falls back to its first sample
# played at track time 0, which is the bind pose: the Animator has not stepped
# yet. That offset ignores foot pitch, so a toe-down foot reads low.
BENCH_POINTS = ("hips", "head", "lfoot", "rfoot")


def _bench_rest_ankle(timeline, rest_ankle):
    if rest_ankle is not None:
        return float(rest_ankle)
    for s in timeline:
        if s.get("tp") == 0 and s.get("lfoot") and s.get("rfoot"):
            return min(s["lfoot"][1], s["rfoot"][1])
    return None


def bench_readings(timeline, sole_y, rest_ankle=None, extrema=None):
    """Heights above the ground and hip travel over a benched clip, in studs,
    read off the samples the clip actually played (track time > 0; the held end
    pose is the last one). None when the timeline cannot answer:

      lowest_sole        the lower foot's sole at its lowest over the clip
                         (0 on the ground, + floating, - sunk)
      lowest_point       the lowest of the hips, head and both soles over the clip
      end_lowest         that lowest point in the end pose
      root_travel_max    the hips' largest horizontal distance from where they start
      root_travel_end    the hips' horizontal distance from the start in the end pose
      source             "frames" when the over-the-clip readings include the
                         bench's per-frame `extrema`, else "samples"

    `extrema` (a bench that reports it) holds the per-frame minima of the lower
    ankle, the hips and the head (`ankleMinY`, `hipsMinY`, `headMinY`) and the
    hips' largest horizontal distance from rest (`hipsTravelMax`), over every
    frame once the track has advanced, including the held end. The 0.25 s samples miss a clip's deepest frames, so each
    over-the-clip reading takes the more extreme of the frames and the samples
    (the samples are frames too); the end-pose readings come from the last
    sample, the held pose.
    """
    if not timeline or sole_y is None:
        return None
    rest = _bench_rest_ankle(timeline, rest_ankle)
    played = [s for s in timeline if (s.get("tp") or 0) > 0 and all(s.get(k) for k in BENCH_POINTS)]
    if rest is None or not played:
        return None
    offset = rest - sole_y

    def soles(s):
        return min(s["lfoot"][1], s["rfoot"][1]) - offset - sole_y

    def lowest(s):
        return min(soles(s), s["hips"][1] - sole_y, s["head"][1] - sole_y)

    start = timeline[0]["hips"] if timeline[0].get("hips") else [0, 0, 0]

    def travel(s):
        return math.hypot(s["hips"][0] - start[0], s["hips"][2] - start[2])

    out = {
        "sole_offset": offset,
        "lowest_sole": min(soles(s) for s in played),
        "lowest_point": min(lowest(s) for s in played),
        "end_lowest": lowest(played[-1]),
        "root_travel_max": max(travel(s) for s in played),
        "root_travel_end": travel(played[-1]),
        "source": "samples",
    }
    frames = extrema if isinstance(extrema, dict) and (extrema.get("frames") or 0) > 0 else None
    if frames is not None:
        def num(key):
            v = frames.get(key)
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        ankle, hips, head, far = num("ankleMinY"), num("hipsMinY"), num("headMinY"), num("hipsTravelMax")
        if ankle is not None:
            out["lowest_sole"] = min(out["lowest_sole"], ankle - offset - sole_y)
        points = [v for v in (None if ankle is None else ankle - offset - sole_y,
                              None if hips is None else hips - sole_y,
                              None if head is None else head - sole_y) if v is not None]
        if points:
            out["lowest_point"] = min([out["lowest_point"]] + points)
        if far is not None:
            out["root_travel_max"] = max(out["root_travel_max"], far)
        out["source"] = "frames"
    return out
