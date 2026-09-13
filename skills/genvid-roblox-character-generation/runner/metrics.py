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
    """Which R15 bones the dump_rest output is missing or malformed, and which
    carry a frame that is not a rotation (`R @ R^T != I` within `tol`, or a
    mirrored frame, `det <= 0`). Diagnostics for the manifest; the booleans the
    E11 gate reads come from rest_dump_checks."""
    rest = rest if isinstance(rest, dict) else {}
    missing, non_orthonormal, worst = [], [], 0.0
    for bone in rigtables.R15_BONES:
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
