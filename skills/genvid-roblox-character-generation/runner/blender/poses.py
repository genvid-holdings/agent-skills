#!/usr/bin/env python
"""Stage 5 (runner): convert a skeletal animation clip (glTF or FBX, Blender-readable)
into Roblox Bone.Transform pose data for the KeyframeSequence writer.

Run headless:
  blender --background --python poses.py -- <clip.fbx|glb> <rest.json> <out.json> \\
      [--rename|--donor|--mixamo|--ual] [--action=NAME] [--rig-height=<studs>] \\
      [--g=<candidate>] [--no-root] [--root-ref=first|bind] [--trim=START:END] \\
      [--root-y=hips|ground --rig-mesh=<rig.glb>] [--root-xz=keep|none] \\
      [--translate=BONE[,BONE...]] [--bind-from=<rig.fbx|glb>|clip]

`--bind-from=<rig file>` takes the bind the transfer measures from (Bw below,
and the hips the `bind` root reference starts at) from the fbx or glb of the
skeleton the clip was authored on, in its rest, instead of from the clip file;
bones are matched by rest.json name, after the same rename `--rename` gives the
clip. A DCC can export "the pose at export" as a clip's bind (its first frame,
its end pose), and every frame then transfers wrong by that difference.
Without the flag, on the empirical axis-map branch (below), a clip whose bind
sits off rest.json by more than `BIND_TOL_DEG` is REFUSED, naming each bone
and its angle: a transfer from a mismatched bind has no correct output.
`--bind-from=clip` transfers from the clip's own bind anyway (a clip on
another skeleton whose rest is in no file at hand), printing and recording
the same bones and angles. The comparison is frame-free (bone directions after
the best rigid fit of the bind onto the rest), so a bone with no child in the
clip is not measured, and a bone rolled about its own length is not seen. A
rig file is refused when its bind is off rest.json by more than the tolerance
(it is not the rig rest.json was dumped from), when its leg chain is not the
clip's length within 1% (another skeleton or scale: the rest hips would land
in other units), or when its world is turned from the clip's (`frame_check`: a
glb twin exported a half turn from the fbx the clip was authored against
passes every frame-free check and flips every frame). That check is printed
and recorded as `bind_frame`: `aligned`, `inconclusive` (a bind posed off the
rest on most bones cannot confirm the frame; the transfer continues) or
`turned` (refused). The bones where the
clip's own bind differs from the rig file's by more than the tolerance are
printed. A rig file placed elsewhere in the world moves the `bind` root
reference, and cannot be told from a clip whose bind is itself displaced (a
flying pose), so the distance between the two hips is printed and recorded
(`bind_hips_offset_studs`): under `--root-ref=bind` it is a constant offset
on every frame's root motion, and the default `first` reference does not read
it.
Either way the doc records `bind_from` and those bones under
`bind_mismatch_deg`. The
flag is refused with `--mixamo` and `--ual`: those clips are on another
skeleton, whose own bind the analytic branch re-rests onto by design.

`--root-y=ground` locks the vertical root motion to the ground: every frame's
vertical offset puts the rig's lowest skinned vertex (the mesh in `--rig-mesh`,
the skinned glb of the rig `rest.json` was dumped from, fitted to it and
refused above a 1%-of-height fit error) back on its rest level. The horizontal
root motion still follows `--root-ref`. The default, `hips`, carries the clip's
hips height change scaled by the leg-chain ratio `k`.

`--root-xz=none` keeps the root's vertical motion and drops its travel: every
frame's root delta has its rig-frame X and Z zeroed before it is expressed in
the root bone's rest frame, and Y stays as `--root-y` sets it. A clip whose
root travels forward and never returns (a lunge, a flight that lands far
ahead) then plays in place with its lift, instead of leaving the mesh away
from its collider to snap back on the next clip. Across the ground the hips
stay where the reference puts them on every frame: the bind pose's place under
`--root-ref=bind`, the first frame's under `first`. The `traj` block carries
the same in-place motion. The axis-map scoring reads the authored motion
unstripped, so the pick, and every bone's rotation, is the same with the
option as without it. Refused with `--no-root`. The default, `keep`, carries
the travel.

`--trim=START:END` keeps only the source clip's frames between START and END
seconds (authored time, from the clip's first frame) and re-bases them so the
kept range starts at 0: a library clip that repeats its action is cut to one
action before anything else reads it (root reference, axis scoring,
trajectories, `clip_seconds`). A range outside the clip is refused.

`--translate=BONE[,BONE...]` carries the named non-root bones' authored
translation into their Pose positions (see below). Name a bone the clip
animates by translation, such as a brow or lid sliding on the face; a root
bone is refused, because its translation is the root motion. Every other
non-root bone the clip translates is reported as dropped, by name and by how
far it moves.

`rest.json` is the target rig's actual bone rest data dumped from Studio by
`runner/luau/dump_rest.luau` (per bone: parent, rot 3x3 row-major from
CFrame:GetComponents, pos), ingested by `studio.py` to `<out>/rest.json`. The rig
is scaled to its final height BEFORE that dump, so every number here is at final
scale. It carries every bone of the rig but the root node: the fifteen R15 bones
and any extra ones (wings, a jaw, cloth). The clip must drive every R15 bone; an
extra bone it does not key is held at its rest, left out of the frames, and
listed under `held` in the output.
`--rename` applies the Meshy->R15 bone rename/merge first (raw vendor clips need
it; clips authored on an already-R15-named skeleton, e.g. Mixamo retargets of our
exported rig, do not). `--donor` is an ALIAS for `--rename`: a Meshy-library clip
played on the Meshy-rigged donor of the same mesh arrives on a skeleton that still
carries the vendor's bone names, so it takes exactly the same path.
`--mixamo` reads a native Mixamo skeleton (mixamorig:/mixamorig1: prefix,
e.g. an X Bot download) through a name map instead. Prefer this over
retargeting on Mixamo's site: retargets onto our uploaded 16-bone rig DROP
the head/hand/foot channels and freeze the hips (live find 2026-07-18),
while the native download keys every bone. World-space reads make the map
collapse safe: UpperTorso reads Spine2 (accumulates the 3-bone spine),
upper arms read Arm bones (accumulate the shoulders).
`--ual` reads the Quaternius Universal Animation Library's Rigify DEF- skeleton.

Why not just play the clip's local rotations as Bone.Transform: Roblox
re-orients bone local frames per bone at FBX import, so source-local
rotations land on the wrong axes (knee flexion becomes knee twist — the
"marionette" walk, live find 2026-07-18). This script transfers WORLD-space
rotation deltas instead: W_i(t) = g·(A_i·B_i^-1)·g^T·R_i, then
T_i(t) = rest_i^-1·Wp^-1·W_i recursively, where A/B are the clip skeleton's
world anim/rest rotations, R/rest are the ROBLOX rig's actual world/local
rests, and g is one global axis conversion chosen EMPIRICALLY: the candidate
whose predicted foot trajectory best matches the authored clip (lateral vs
forward swing and height range) wins. Below the root, translations are
dropped unless `--translate` names the bone: a rotation-only transfer is
immune to the scale pitfalls (clip units against studs, the model scale the
Animator applies), and a non-root bone's authored offset belongs to the source
skeleton's proportions, which the rig's own rest replaces. A named bone's
translation is its head's displacement from where its parent's animated
frame puts it at rest, in clip world, mapped by the same `g` and scaled by
the same `k` as the root motion, then expressed in the bone's rest frame
under its parent's transferred rotation.

Ported from the retired pipeline's stage_h_poses.py. Changes from that source:
the RENAME/MERGE/MIXAMO_MAP/UAL_MAP tables come from the runner's `rigtables`
module (single source shared with the rig conversion); `--rename` normalizes
vendor bone spellings before the rename/merge, as rig_r15.py does; the `.luau`
writer is dropped (kfs.py builds the KeyframeSequence from the JSON); the JSON
carries the world-space `traj` block that impact.py and metrics.py score, plus
`clip_seconds` and `source`; and the clip-to-rig scale `k` (root motion and
the g-scoring ratio) is the leg-chain ratio between the rig's rest and the
clip's bind, recorded as `k` in the doc. `--rig-height` is still accepted
(clips.py passes the manifest's `height_studs`) and only reported.
"""
import bpy
import json
import math
import os
import sys

# rigtables lives in the runner package dir, one level up from blender/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rigtables import RENAME, MERGE, clip_bone_map, normalize  # noqa: E402

import numpy as np


def m3(v):
    return np.array(v, dtype=float).reshape(3, 3)


def mat9(m):
    return [[m[i][j] for j in range(3)] for i in range(3)]


def quat(M):
    t = np.trace(M)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w = 0.25 * s
        x = (M[2, 1] - M[1, 2]) / s
        y = (M[0, 2] - M[2, 0]) / s
        z = (M[1, 0] - M[0, 1]) / s
    else:
        i = int(np.argmax([M[0, 0], M[1, 1], M[2, 2]]))
        if i == 0:
            s = math.sqrt(1.0 + M[0, 0] - M[1, 1] - M[2, 2]) * 2
            x = 0.25 * s; w = (M[2, 1] - M[1, 2]) / s
            y = (M[0, 1] + M[1, 0]) / s; z = (M[0, 2] + M[2, 0]) / s
        elif i == 1:
            s = math.sqrt(1.0 + M[1, 1] - M[0, 0] - M[2, 2]) * 2
            y = 0.25 * s; w = (M[0, 2] - M[2, 0]) / s
            x = (M[0, 1] + M[1, 0]) / s; z = (M[1, 2] + M[2, 1]) / s
        else:
            s = math.sqrt(1.0 + M[2, 2] - M[0, 0] - M[1, 1]) * 2
            z = 0.25 * s; w = (M[1, 0] - M[0, 1]) / s
            x = (M[0, 2] + M[2, 0]) / s; y = (M[1, 2] + M[2, 1]) / s
    return x, y, z, w


def rotation_part(M):
    """The nearest pure rotation to a 3x3 (polar decomposition by SVD). A pose
    matrix carries any scale the clip keys on a bone; left in, the transferred
    matrices stop being rotations and the emitted quaternions stop being unit
    length (witnessed 2026-09-23: a library idle keys a uniform 1.176 scale on
    Hips on every frame, and every bone's quaternion came out at norm
    1.06-1.15)."""
    u, _s, vt = np.linalg.svd(M)
    R = u @ vt
    if np.linalg.det(R) < 0:
        u[:, -1] = -u[:, -1]
        R = u @ vt
    return R


# The trajectory bones impact.py and metrics.py score: the two feet (stomp,
# foot lift) and the two hands (a giant's slam lands with the hands).
TRAJ_BONES = ("LeftFoot", "RightFoot", "LeftHand", "RightHand")

RIG_HEIGHT_DEFAULT = 28.0  # studs, feet-to-crown; reported only (k is the leg-chain ratio)


def rx(deg):
    a = math.radians(deg)
    return np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])


def ry(deg):
    a = math.radians(deg)
    return np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])


# The ground lock's rig-mesh fit refuses when a rest bone origin lands farther
# than this fraction of the mesh height from where the mesh's own armature puts
# it: the mesh is then not the rig rest.json was dumped from.
GROUND_FIT_TOL = 0.01

# A clip's bind is refused (no --bind-from) or reported (with it) when a bone
# sits more than this many degrees off the rig's rest. A rig file against its
# own rest dump, and vendor-library clips whose bind is the rig's rest, read
# 0.0 on every bone; the smallest mismatch witnessed that moves a limb (a
# stance exported as the bind) reads 6.7.
BIND_TOL_DEG = 5.0
# A --bind-from rig's leg chain must be the clip's length within this fraction.
BIND_LEG_TOL = 0.01


def rest_origins(rb, order, Rw, Pw):
    """Each bone's rest origin in the rig frame (studs): parent origin plus
    the parent's world rest rotation applied to the bone's offset."""
    P0 = {}
    for n in order:
        pr = rb[n]["parent"]
        P0[n] = P0.get(pr, np.zeros(3)) + Rw.get(pr, np.eye(3)) @ Pw[n]
    return P0


def segments(to, frm, rb, order):
    """Each bone's direction (its origin to a child's) in two skeletons, as
    (parent, direction in `to`, direction in `frm`), for the bones both carry.
    A zero-length offset is left out."""
    segs = []
    for n in order:
        pr = rb[n]["parent"]
        if n not in to or pr not in to or n not in frm or pr not in frm:
            continue
        a, b = np.asarray(to[n]) - np.asarray(to[pr]), np.asarray(frm[n]) - np.asarray(frm[pr])
        la, lb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        if la >= 1e-6 and lb >= 1e-9:
            segs.append((pr, a / la, b / lb))
    return segs


def angle_deg(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, float(a @ b)))))


def trimmed_fit(segs, tol=BIND_TOL_DEG):
    """The rotation taking the `frm` directions onto the `to` ones (best rigid
    fit), and each direction's angle after it. The worst-fitting direction is
    dropped from the fit and the fit redone while one is over `tol` and more
    than half remain, so a few bones posed differently do not tilt the fit for
    the others."""
    keep = list(range(len(segs)))
    while True:
        U, _S, Vt = np.linalg.svd(np.array([segs[i][1] for i in keep]).T @ np.array([segs[i][2] for i in keep]))
        D = np.eye(3)
        D[2, 2] = np.sign(np.linalg.det(U @ Vt))
        R = U @ D @ Vt
        ang = [angle_deg(a, R @ b) for _pr, a, b in segs]
        worst = max(keep, key=lambda i: ang[i])
        if ang[worst] <= tol or len(keep) - 1 <= len(segs) // 2:
            return R, ang
        keep.remove(worst)


def bind_off_rest(heads, rb, order, P0, tol=BIND_TOL_DEG):
    """Degrees each bone's bind direction sits off its rest direction, frame
    free: `heads` is {rest.json name: bind origin} in any frame and unit, and
    its directions are rotated onto the rest's by `trimmed_fit`. Each bone
    keeps its largest angle over its children; a bone with no measured child
    is left out. Directions only: a bone rolled about its own length is not
    seen."""
    segs = segments(P0, heads, rb, order)
    if not segs:
        return {}
    _R, ang = trimmed_fit(segs, tol)
    off = {}
    for (pr, _a, _b), deg in zip(segs, ang):
        off[pr] = max(off.get(pr, 0.0), deg)
    return off


def frame_check(rig_heads, clip_heads, rb, order, tol=BIND_TOL_DEG):
    """Whether the --bind-from file's world is the clip's: one of three states,
    as {"state", "turn_deg", "agree", "bones"}. The rig's bone directions are
    fitted onto the clip bind's (`trimmed_fit`). `turned`: the fit turns by
    more than `tol`, at least half the bones agree after it and more of them
    than agree unturned (a skeleton that matches only once turned); `agree` is
    the bones agreeing after the turn. `aligned`: otherwise, when at least half
    the bones agree unturned. `inconclusive`: neither; a clip whose bind is
    posed far from the rest on most bones cannot tell a turned file from its
    own pose. For both, `agree` is the bones agreeing unturned."""
    segs = segments(clip_heads, rig_heads, rb, order)
    if not segs:
        return {"state": "inconclusive", "turn_deg": None, "agree": 0, "bones": 0}
    R, ang = trimmed_fit(segs, tol)
    turn = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))
    fitted = sum(1 for d in ang if d <= tol)
    unturned = sum(1 for _pr, a, b in segs if angle_deg(a, b) <= tol)
    if turn > tol and 2 * fitted >= len(segs) and fitted > unturned:
        state, agree = "turned", fitted
    else:
        state, agree = ("aligned" if 2 * unturned >= len(segs) else "inconclusive"), unturned
    return {"state": state, "turn_deg": round(turn, 1), "agree": agree, "bones": len(segs)}
    R, ang = trimmed_fit(segs, tol)
    turn = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))
    fitted = sum(1 for d in ang if d <= tol)
    unturned = sum(1 for _pr, a, b in segs if angle_deg(a, b) <= tol)
    if turn > tol and 2 * fitted >= len(segs) and fitted > unturned:
        return turn, fitted, len(segs)
    return None


def over(offsets, tol=BIND_TOL_DEG):
    """The bones over `tol`, worst first, as {bone: degrees rounded to 0.1}."""
    return {n: round(d, 1) for n, d in sorted(offsets.items(), key=lambda kv: -kv[1]) if d > tol}


def listed(offsets):
    return ", ".join(f"{n} {d:0.1f} deg" for n, d in offsets.items())


def leg_length(heads):
    """Hip joint -> knee -> ankle on both sides, from bone origins."""
    return sum(float(np.linalg.norm(np.asarray(heads[side + b]) - np.asarray(heads[side + a])))
               for side in ("Left", "Right") for a, b in (("UpperLeg", "LowerLeg"), ("LowerLeg", "Foot")))


def rename_to_r15(arm):
    """The Meshy->R15 bone rename/merge (`--rename`), on `arm` in place."""
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    # Normalize FIRST, as rig_r15.py does: a Tripo `spec=mixamo` skeleton
    # spells the same bones `mixamorig:Spine1` / `mixamorig:Spine2`, which
    # match no RENAME/MERGE key as shipped.
    for b in list(eb):
        b.name = normalize(b.name)
    for old, new in RENAME.items():
        if old in eb:
            eb[old].name = new
    for old, _t in MERGE:
        if old in eb:
            b = eb[old]
            for child in list(b.children):
                child.parent = b.parent
            eb.remove(b)
    bpy.ops.object.mode_set(mode="OBJECT")


def bind_armature(path, names, rename=False):
    """The bind of the armature in `path` (a rig fbx or glb): per bone in
    `names` its world bind rotation and origin, read in the same Blender world
    the clip was imported into. `rename` puts its bones through the same
    rename/merge the clip took. The import cannot move the clip's timing: the
    scene's frame rate and range are put back as they were."""
    sc = bpy.context.scene
    kept = (sc.render.fps, sc.render.fps_base, sc.frame_start, sc.frame_end, sc.frame_current)
    before = set(bpy.data.objects)
    if path.lower().endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        bpy.ops.import_scene.fbx(filepath=path)
    sc.render.fps, sc.render.fps_base, sc.frame_start, sc.frame_end, _cur = kept
    sc.frame_set(kept[4])
    rig = next((o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"), None)
    if rig is None:
        raise ValueError(f"--bind-from={path}: no armature in it")
    if rename:
        rename_to_r15(rig)
    missing = [n for n in names if n not in rig.data.bones]
    if missing:
        raise ValueError(f"--bind-from={path}: armature lacks bones {missing}")
    _u, _s, _vt = np.linalg.svd(np.array(mat9(rig.matrix_world))[:3, :3])
    AW = _u @ _vt
    Bw = {n: AW @ np.array(mat9(rig.data.bones[n].matrix_local))[:3, :3] for n in names}
    heads = {n: np.array((rig.matrix_world @ rig.data.bones[n].matrix_local).translation) for n in names}
    return Bw, heads


# A non-root bone whose translation moves it less than this fraction of the
# rig's leg chain is treated as not translated (float noise in a location key).
DROPPED_TRANSLATION_TOL = 0.001


def ground_lows(rig_mesh, clip_arm, rb, order, Rw, Pw, poses):
    """Lowest skinned vertex height (rig frame, studs) per frame, for the ground
    lock. `poses` is [(W, WPr)] per frame: each bone's rig-frame world rotation
    and origin with no root motion. The rig glb is imported beside the clip,
    its armature's R15 bone heads are fitted to rest.json's rest origins by a
    similarity (scale, rotation, offset), and the mesh is skinned per frame
    with its own weights: v' = sum_b w_b (W_b Rw_b^T (v - P0_b) + P_b). Every
    skinned mesh parented to the armature is read: a multi-mesh rig can list a
    head or accessory mesh first, and the soles are wherever they are."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=rig_mesh)
    new = [o for o in bpy.data.objects if o not in before]
    rig = next((o for o in new if o.type == "ARMATURE"), None)
    meshes = [o for o in new if o.type == "MESH" and o.parent is rig and o.vertex_groups] if rig else []
    if rig is None or not meshes:
        raise ValueError(f"--rig-mesh={rig_mesh}: no armature with a skinned mesh in it")
    missing = [n for n in order if n not in rig.data.bones]
    if missing:
        raise ValueError(f"--rig-mesh={rig_mesh}: armature lacks bones {missing}")
    rig.data.pose_position = "REST"
    bpy.context.view_layer.update()
    parts = []
    for mesh in meshes:
        ev = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        mw = np.array(ev.matrix_world)
        ev.to_mesh_clear()
        parts.append(co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3])
    V = np.concatenate(parts)
    # rest origins in the rig frame, and the same bones' heads in Blender world
    P0 = rest_origins(rb, order, Rw, Pw)
    src = np.array([P0[n] for n in order])
    dst = np.array([list(rig.matrix_world @ rig.data.bones[n].head_local) for n in order])
    ms, md = src.mean(0), dst.mean(0)
    X, Y = src - ms, dst - md
    U, S, Vt = np.linalg.svd(Y.T @ X)
    D = np.eye(3)
    D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ D @ Vt
    s = float((S * np.diag(D)).sum() / (X ** 2).sum())
    off = md - s * R @ ms
    Vr = ((V - off) @ R) / s                     # mesh in the rig frame, studs
    # the largest distance between a rest bone origin and where the mesh's
    # armature puts it, in studs
    fit_err = float(np.linalg.norm((s * (R @ src.T)).T + off - dst, axis=1).max() / s) if s > 0 else math.inf
    height = float(np.ptp(Vr[:, 1]))
    tol = GROUND_FIT_TOL * height
    print(f"ground lock: rig mesh {os.path.basename(rig_mesh)} fitted at {1 / s:0.3f} studs per unit, "
          f"max bone-origin error {fit_err:0.4f} studs (tolerance {tol:0.3f}), mesh height {height:0.2f} studs")
    if not fit_err <= tol:
        raise ValueError(f"--rig-mesh={rig_mesh} does not fit rest.json: a bone origin is {fit_err:0.3f} studs off "
                         f"(tolerance {tol:0.3f}); pass the skinned glb of the rig rest.json was dumped from")
    Wt = np.zeros((len(Vr), len(order)))
    col = {n: i for i, n in enumerate(order)}
    base = 0
    for mesh, part in zip(meshes, parts):
        gi = {g.index: g.name for g in mesh.vertex_groups}
        for v in mesh.data.vertices:
            for ge in v.groups:
                c = col.get(gi[ge.group])
                if c is not None:
                    Wt[base + v.index, c] += ge.weight
        base += len(part)
    keep = Wt.sum(1) > 0
    Vr, Wt = Vr[keep], Wt[keep] / Wt[keep].sum(1, keepdims=True)
    rest_low = float(Vr[:, 1].min())
    lows = []
    for W, WPr in poses:
        y = np.zeros(len(Vr))
        for n, c in col.items():
            w = Wt[:, c]
            if w.any():
                y += w * (((Vr - P0[n]) @ (W[n] @ Rw[n].T).T)[:, 1] + WPr[n][1])
        lows.append(float(y.min()))
    info = {"rig_mesh": os.path.basename(rig_mesh), "fit_err_studs": round(fit_err, 5),
            "tolerance_studs": round(tol, 5), "studs_per_unit": round(1 / s, 5),
            "vertices": int(len(Vr)), "meshes": len(meshes), "rest_low": round(rest_low, 5)}
    return lows, info


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :]
    clip_path, rest_path, out_path = argv[0], argv[1], argv[2]
    # --donor is an alias for --rename: the Meshy-rigged donor skeleton a library
    # clip is played on carries the vendor's bone names, so it needs the same
    # normalize + rename/merge pass a raw vendor clip does.
    do_rename = "--rename" in argv or "--donor" in argv
    do_mixamo = "--mixamo" in argv
    do_ual = "--ual" in argv
    # Root motion (2026-09-08): the library clips MOVE the hips (a stomp drops
    # them, a charged slam kneels, a fall lies down) and a rotation-only
    # transfer plays every one of those as legs folding under a pelvis pinned
    # at standing height, which reads as tangled legs rather than the motion
    # the clip encodes. The root bone's translation is emitted per frame unless
    # --no-root asks for the old rotation-only doc (the walk and idle were
    # accepted on it and are not rebuilt).
    emit_root = "--no-root" not in argv
    # --g=<candidate name> forces the axis map. The map is a property of the
    # SOURCE SKELETON convention, not of the clip, but the empirical pick
    # scores foot trajectories against a walk-shaped truth (lateral vs
    # forward swing) and picks wrong on clips that are not walks (witnessed
    # 2026-09-08: Electrocuted_Fall picked p(1, 0, 2)s(-1, 1, 1), up mapped to
    # forward, while Monster_Walk on the same skeleton picked
    # p(0, 2, 1)s(-1, 1, 1)). Transfer the walk first, then force its pick.
    forced_g = next((a.split("=", 1)[1] for a in argv if a.startswith("--g=")), None)
    # Root-motion reference: the clip's FIRST FRAME by default. Library clips
    # do not all start at the bind pose -- Meshy 171 (stun) and 127 (slam)
    # start with the hips 17-43 studs from the T-pose hips at giant-character scale
    # (witnessed 2026-09-08), and bind-relative root motion would throw the
    # mesh off its collider for the whole clip and snap it back at the end.
    # Measured from the first frame, a clip that starts in a stance starts on
    # the collider and returns to it. --root-ref=bind keeps the bind reference
    # (a clip that starts mid-air or crouched and should read that way).
    root_ref = next((a.split("=", 1)[1] for a in argv if a.startswith("--root-ref=")), "first")
    assert root_ref in ("first", "bind"), "--root-ref must be first or bind"
    # Vertical root motion: "hips" (default) is the proportional hips delta
    # from the root reference, like the horizontal; "ground" locks the rig's
    # lowest skinned vertex to the ground on every frame instead, which needs
    # the rig's own skinned mesh (`--rig-mesh=<rig glb>`, the file rest.json
    # was dumped from). The horizontal follows --root-ref either way.
    root_y = next((a.split("=", 1)[1] for a in argv if a.startswith("--root-y=")), "hips")
    assert root_y in ("hips", "ground"), "--root-y must be hips or ground"
    rig_mesh = next((a.split("=", 1)[1] for a in argv if a.startswith("--rig-mesh=")), None)
    # Horizontal root motion: "keep" (default) carries the hips' travel from
    # the root reference; "none" zeroes it on every frame, so a clip whose
    # root travels and never returns plays in place with its vertical motion.
    root_xz = next((a.split("=", 1)[1] for a in argv if a.startswith("--root-xz=")), "keep")
    if root_xz not in ("keep", "none"):
        raise ValueError(f"--root-xz must be keep or none, not {root_xz!r}")
    if root_xz == "none" and not emit_root:
        raise ValueError("--root-xz=none with --no-root: a rotation-only doc has no root motion to keep the lift of")
    if root_y == "ground":
        if not emit_root:
            raise ValueError("--root-y=ground with --no-root: a rotation-only doc has no root motion to lock")
        if not rig_mesh:
            raise ValueError("--root-y=ground needs --rig-mesh=<the rig's skinned glb>")
    # The bind the transfer measures from: the clip file's own, or the rig
    # file's (a clip authored on the rig and exported with another pose as its
    # bind). Only a clip on the rig's own skeleton can take the rig's bind.
    bind_from = next((a.split("=", 1)[1] for a in argv if a.startswith("--bind-from=")), None)
    if bind_from and (do_mixamo or do_ual):
        raise ValueError(f"--bind-from with {'--mixamo' if do_mixamo else '--ual'}: that clip is on another "
                         "skeleton, and the transfer re-rests onto its own bind; --bind-from is for a clip "
                         "authored on the rig's skeleton")
    trim = next((a.split("=", 1)[1] for a in argv if a.startswith("--trim=")), None)
    if trim is not None:
        t_start, t_end = (float(v) for v in trim.split(":"))
        if not 0.0 <= t_start < t_end:
            raise ValueError(f"--trim={trim}: need 0 <= START < END (seconds of the source clip)")
    action_name = None
    rig_h = RIG_HEIGHT_DEFAULT
    for a in argv:
        if a.startswith("--action="):
            action_name = a.split("=", 1)[1]
        if a.startswith("--rig-height="):
            rig_h = float(a.split("=", 1)[1])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    if clip_path.lower().endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=clip_path)
    else:
        bpy.ops.import_scene.fbx(filepath=clip_path)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")

    if do_rename:
        rename_to_r15(arm)

    if action_name is not None:
        act = bpy.data.actions[action_name]
        if arm.animation_data is None:
            arm.animation_data_create()
        arm.animation_data.action = act
        try:
            arm.animation_data.action_slot = act.slots[0]
        except Exception:
            pass
        print(f"selected action {action_name}")

    rb = json.load(open(rest_path))
    prefix = ""
    mode = "names"
    if do_mixamo:
        prefix = next((b.name[: -len("Hips")] for b in arm.data.bones if b.name.endswith(":Hips")), "")
        mode = "mixamo"
        print(f"mixamo mode, bone prefix '{prefix}'")
    elif do_ual:
        mode = "ual"
        print("ual mode (Rigify DEF- skeleton)")
    # The rest dump carries every bone of the rig, the fifteen R15 ones and any
    # extra bones (wings, a jaw, cloth). A clip must drive every R15 bone; an
    # extra bone it does not key is HELD: posed at its rest, following its
    # parent, and left out of the frames (kfs.write leaves it out of the
    # sequence unless it must stay as a structural node, so lower-priority
    # tracks keep its joint), so a clip library authored without those bones
    # still plays.
    src, held = clip_bone_map(list(rb.keys()), [b.name for b in arm.data.bones], mode=mode, prefix=prefix)
    names = list(src)
    if held:
        print(f"held at rest (the clip does not key them): {held}")
    translate = next((a.split("=", 1)[1] for a in argv if a.startswith("--translate=")), "")
    translate = [b for b in translate.split(",") if b]
    for b in translate:
        if b not in rb:
            raise ValueError(f"--translate: {b} is not in rest.json (bones: {', '.join(sorted(rb))})")
        if rb[b]["parent"] == "HumanoidRootPart":
            raise ValueError(f"--translate: {b} is a root bone; its translation is the root motion")
        if b not in src:
            raise ValueError(f"--translate: {b} is held at rest (the clip does not key it), so it has no translation")
        # a named bone's translation is measured from its clip parent's frame
        if arm.pose.bones[src[b]].parent is None:
            raise ValueError(f"--translate: {b} ({src[b]} in the clip) has no parent bone in the clip, "
                             "so it has no rest offset to measure a translation from")

    kids = {}
    for n, d in rb.items():
        kids.setdefault(d["parent"], []).append(n)
    order = []
    # every bone hanging off the root part, not only LowerTorso: an extra bone
    # parented to the root node would otherwise never be posed
    stack = sorted(kids.get("HumanoidRootPart", []), reverse=True)
    while stack:
        n = stack.pop()
        order.append(n)
        stack.extend(kids.get(n, []))
    unreached = sorted(set(rb) - set(order))
    if unreached:
        # the transfer walks the chain from the root part: these get no track at all
        print(f"warning: rest.json bones not reached from HumanoidRootPart get no track: {', '.join(unreached)}")

    # Roblox world rests (HRP frame)
    Rw = {}
    for n in order:
        pr = rb[n]["parent"]
        Rw[n] = Rw.get(pr, np.eye(3)) @ m3(rb[n]["rot"])

    # clip skeleton world rests + per-frame world anim (armature space)
    # WORLD space, not armature space: the FBX importer parks a rotation on
    # the armature OBJECT (glTF does not), and armature-space matrices then
    # live in a tilted frame that breaks both the transfer and the g-scoring
    # (live find 2026-07-18: near-tied candidate scores = this bug).
    # matrix_world carries the FBX import scale (0.01 on Mixamo files);
    # SVD-orthonormalize to the pure rotation or every product stops being
    # a rotation and quaternions collapse (live find: constant w=0.5 quats)
    _u, _s, _vt = np.linalg.svd(np.array(mat9(arm.matrix_world))[:3, :3])
    AW = _u @ _vt
    # a bone's rest matrix is built from head, tail and roll, so it is a pure
    # rotation whatever scale the armature carried (witnessed 2026-09-23: after
    # applying a (2, 0.5, -1.5) object scale, and on vendor glb and fbx rigs,
    # every singular value is 1 within 1e-6); only the POSE matrices need
    # rotation_part
    Bw = {n: AW @ np.array(mat9(arm.data.bones[src[n]].matrix_local))[:3, :3] for n in names}
    AWfull = arm.matrix_world
    clip_heads = {n: np.array((AWfull @ arm.data.bones[src[n]].matrix_local).translation) for n in names}
    Pw = {n: np.array(rb[n]["pos"]) for n in order}
    P0 = rest_origins(rb, order, Rw, Pw)
    # The analytic axis map (a native Mixamo or Rigify skeleton with a toe
    # bone) re-rests every bone onto the clip's own bind; every other clip
    # takes the empirical branch, which transfers deltas from the bind as-is
    # and so needs the bind to be the rig's rest.
    toe_name = (prefix + "LeftToeBase") if do_mixamo else ("DEF-toe.L" if do_ual else None)
    toe = arm.data.bones.get(toe_name) if toe_name is not None else None
    bind_mismatch = {}
    rig_hips = None
    hips_offset = None
    bind_frame = None
    if bind_from and bind_from != "clip":
        rig_Bw, rig_heads = bind_armature(bind_from, names, rename=do_rename)
        rig_off = over(bind_off_rest(rig_heads, rb, order, P0))
        if rig_off:
            raise ValueError(f"--bind-from={bind_from} is not the rig rest.json was dumped from: its bind is off "
                             f"rest.json by more than {BIND_TOL_DEG} deg at {listed(rig_off)}")
        bind_frame = frame_check(rig_heads, clip_heads, rb, order)
        if bind_frame["state"] == "turned":
            raise ValueError(f"--bind-from={bind_from} is in another world frame than the clip: its skeleton matches "
                             f"the clip's bind only after a {bind_frame['turn_deg']:0.1f} deg turn "
                             f"({bind_frame['agree']} of {bind_frame['bones']} bones), and its bind would flip every "
                             "frame; pass the file of the skeleton the clip was authored against, exported in the "
                             "clip's world")
        print(f"frame check: {bind_frame['state']} ({bind_frame['agree']} of {bind_frame['bones']} bones agree)"
              + ("; the clip's bind is posed too far from the rest to confirm the file's world is the clip's"
                 if bind_frame["state"] == "inconclusive" else ""))
        rig_leg_len, clip_leg_len = leg_length(rig_heads), leg_length(clip_heads)
        if not abs(rig_leg_len - clip_leg_len) <= BIND_LEG_TOL * clip_leg_len:
            raise ValueError(f"--bind-from={bind_from}: its leg chain is {rig_leg_len:0.4f} units and the clip's "
                             f"{clip_leg_len:0.4f}; pass the rig file at the clip's scale")
        bind_mismatch = over({n: math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(Bw[n] @ rig_Bw[n].T) - 1) / 2))))
                              for n in names})
        if bind_mismatch:
            print(f"the clip's own bind is off the rig's by more than {BIND_TOL_DEG} deg at {listed(bind_mismatch)}; "
                  f"transferring from the rig's bind ({os.path.basename(bind_from)})")
        Bw = rig_Bw
        rig_hips = rig_heads["LowerTorso"]
        # A file placed elsewhere in the world, or a clip whose bind is itself
        # displaced (a flying pose), moves the `bind` root reference by the
        # same vector; the two cannot be told apart, so the distance is
        # reported rather than refused. The `first` reference does not read it.
        hips_offset = float(np.linalg.norm(clip_heads["LowerTorso"] - rig_hips))
    elif toe is None:
        clip_off = over(bind_off_rest(clip_heads, rb, order, P0))
        if clip_off and bind_from != "clip":
            raise ValueError(f"the clip's bind pose is off the rig's rest (rest.json) by more than {BIND_TOL_DEG} deg "
                             f"at {listed(clip_off)}; every frame would transfer wrong by that difference. Pass "
                             "--bind-from=<the fbx or glb of the skeleton the clip was authored on, in its rest>, "
                             "or --bind-from=clip to transfer from the clip's own bind anyway")
        if clip_off:
            print(f"the clip's own bind is off the rig's rest by more than {BIND_TOL_DEG} deg at {listed(clip_off)}; "
                  "transferring from it as asked (--bind-from=clip)")
        bind_mismatch = clip_off
    act = arm.animation_data.action
    f0, f1 = act.frame_range
    fps = bpy.context.scene.render.fps
    fnums = list(range(int(f0), int(f1 + 0.999) + 1))
    times = [max(0.0, (f - f0) / fps) for f in fnums]
    if trim is not None:
        # half a frame of slack at each end: a boundary typed from a frame
        # time rounds either way
        half = 0.5 / fps
        if t_end > times[-1] + half:
            raise ValueError(f"--trim={trim} ends past the clip, which is {times[-1]:0.3f}s long")
        keep = [(f, t) for f, t in zip(fnums, times) if t_start - half <= t <= t_end + half]
        if len(keep) < 2:
            raise ValueError(f"--trim={trim} keeps fewer than two frames of a {times[-1]:0.3f}s clip")
        base = keep[0][1]
        fnums = [f for f, _t in keep]
        times = [round(t - base, 6) for _f, t in keep]
        print(f"trimmed to source frames {fnums[0]}..{fnums[-1]} ({len(fnums)} frames, {times[-1]:0.3f}s)")
    frames = []
    # per frame, each non-root bone's own translation: its head's displacement
    # (clip world, clip units) from where its parent's animated frame puts it
    # at rest; zero for a bone the clip only rotates
    moves = []
    # each such bone's rest offset in its clip parent's frame
    offsets = {n: (pb.parent.bone.matrix_local.inverted() @ pb.bone.matrix_local).translation
               for n in names for pb in (arm.pose.bones[src[n]],)
               if rb[n]["parent"] != "HumanoidRootPart" and pb.parent is not None}
    for f, t in zip(fnums, times):
        bpy.context.scene.frame_set(f)
        A, D = {}, {}
        for n in names:
            pb = arm.pose.bones[src[n]]
            pm = pb.matrix
            A[n] = AW @ rotation_part(np.array(mat9(pm))[:3, :3])
            if n in offsets:
                at_rest = AWfull @ (pb.parent.matrix @ offsets[n])
                D[n] = np.array(AWfull @ pm.translation) - np.array(at_rest)
        frames.append((t, A))
        moves.append(D)

    # pick g by foot-trajectory fidelity vs the authored clip
    # authored foot ranges, measured in WORLD frame: X lateral, Y forward
    # (Mixamo faces -Y in Blender world), Z up
    fl, ff, fh = [], [], []
    # hips world position per frame (clip units, Blender world frame) and at
    # the bind pose (the rig's with --bind-from): their difference is the root
    # motion the transfer carries
    hips = []
    rest_hips = rig_hips if rig_hips is not None else clip_heads["LowerTorso"]
    for f_, _A in enumerate(frames):
        bpy.context.scene.frame_set(fnums[f_])
        wp = AWfull @ arm.pose.bones[src["LeftFoot"]].matrix
        fl.append(wp[0][3])
        ff.append(wp[1][3])
        fh.append(wp[2][3])
        hp = AWfull @ arm.pose.bones[src["LowerTorso"]].matrix
        hips.append(np.array([hp[0][3], hp[1][3], hp[2][3]]))
    if root_ref == "first" and hips:
        rest_hips = hips[0]
    truth_lat = max(fl) - min(fl)
    truth_fwd = max(ff) - min(ff)
    truth_h = max(fh) - min(fh)

    def corr(a, b):
        a = np.array(a) - np.mean(a)
        b = np.array(b) - np.mean(b)
        d = float(np.linalg.norm(a) * np.linalg.norm(b))
        return float(a @ b) / d if d > 1e-9 else 0.0
    # k converts clip units to rig studs, for the root motion and the
    # g-scoring truth ranges. It is the LEG-CHAIN ratio (hip joint -> knee ->
    # ankle, both sides) between the rig's rest and the clip's bind: the
    # hips' height over the feet is what root motion must keep in proportion.
    # The overall-height ratio it replaces measured the clip's bone-head span
    # after the rename/merge had removed the head-end and toe bones, which on
    # a library skeleton spans about hips-to-skull (1.24 of a 1.70 mesh) while
    # the rig height is feet-to-crown, so root motion came out 1.37x too large
    # (witnessed 2026-09-23: a death's 0.84-unit hip drop moved 47 studs where
    # the rig-to-clip scale, 41.2 studs a unit by a fit of the rig mesh, gives
    # 34.5; the leg ratio gives 41.15).
    clip_leg = leg_length(clip_heads)

    # all 24 proper axis-aligned rotations (signed permutation matrices,
    # det +1): the 5-candidate shortlist missed the right frame on the
    # native Mixamo X Bot skeleton (near-tied scores, live find 2026-07-18)
    import itertools
    CANDS = {}
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            M = np.zeros((3, 3))
            for row, (col, s) in enumerate(zip(perm, signs)):
                M[row, col] = s
            if np.linalg.det(M) > 0.5:
                CANDS[f"p{perm}s{signs}"] = M
    # the rig's leg bones in its rest: a bone's pos is its offset from the parent
    rig_leg = sum(float(np.linalg.norm(Pw[side + b])) for side in ("Left", "Right") for b in ("LowerLeg", "Foot"))
    if clip_leg <= 1e-9 or rig_leg <= 1e-9:
        raise ValueError(f"leg chain has no length (clip {clip_leg}, rig {rig_leg}): cannot scale root motion")
    k = rig_leg / clip_leg
    if hips_offset is not None:
        print(f"the rig's bind hips sit {hips_offset * k:0.3f} studs from the clip bind's; --root-ref=bind measures "
              "root motion from the rig's")
    print(f"k = {k:0.4f} studs per clip unit (leg chain: rig {rig_leg:0.3f} studs, clip {clip_leg:0.4f} units)")
    def min_rot(a, b):
        """Smallest rotation matrix taking unit-ish vector a onto b."""
        a = a / np.linalg.norm(a)
        b = b / np.linalg.norm(b)
        c = float(a @ b)
        v = np.cross(a, b)
        s = float(np.linalg.norm(v))
        if s < 1e-8:
            if c > 0:
                return np.eye(3)
            p = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
            axis = np.cross(a, p)
            axis /= np.linalg.norm(axis)
            K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
            return np.eye(3) + 2 * K @ K
        K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        return np.eye(3) + K + K @ K * ((1 - c) / (s * s))

    def _world(n, pr, A, W, g, F):
        """Bone `n`'s rig-frame world rotation this frame: the transferred
        clip delta on its rest, or, for a held bone, its parent's world
        rotation times its own rest local (it rides its parent unchanged)."""
        if n in src:
            return (g @ (A[n] @ Bw[n].T) @ g.T) @ F[n] @ Rw[n]
        return W.get(pr, np.eye(3)) @ m3(rb[n]["rot"])

    def foot_traj(g, F):
        lx, fz, hy = [], [], []
        for _t, A in frames:
            W, WP = {}, {}
            for n in order:
                pr = rb[n]["parent"]
                W[n] = _world(n, pr, A, W, g, F)
                WP[n] = WP.get(pr, np.zeros(3)) + (W.get(pr, np.eye(3)) @ Pw[n])
            lx.append(WP["LeftFoot"][0])
            hy.append(WP["LeftFoot"][1])
            fz.append(WP["LeftFoot"][2])
        return lx, fz, hy

    ID_F = {n: np.eye(3) for n in names}
    yhat = np.array([0.0, 1.0, 0.0])
    print(f"truth (rig units): lateral={truth_lat*k:5.2f} forward={truth_fwd*k:5.2f} height={truth_h*k:5.2f}")
    if toe is not None:
        # ANALYTIC g: the conversion is fully determined, no search — it must
        # map clip world up (+Z in Blender) to rig up (+Y) and the clip
        # character's facing (measured toe-heel) to rig facing (-Z). The
        # empirical range scoring near-tied physically impossible candidates
        # (up mapped to DOWN) on the X Bot clip (live find 2026-07-18).
        heel = arm.data.bones[src["LeftFoot"]]
        dw = AW @ (np.array(toe.head_local) - np.array(heel.head_local))
        f = np.array([dw[0], dw[1], 0.0])
        f /= np.linalg.norm(f)
        u = np.array([0.0, 0.0, 1.0])
        g = np.stack([np.cross(f, u), u, -f])  # rows: rig X/Y/Z <- clip right/up/back
        g_name = "analytic"
        # PER-BONE REST CORRECTION F: delta transfer preserves deviation-from-
        # rest, so a rest mismatch (X Bot T-pose vs our A-pose) bakes a
        # constant error into every frame — deformed limbs + feet tucked off
        # the ground (witnessed 2026-07-18). Re-rest each
        # Roblox bone onto the clip's rest DIRECTION first (both rigs keep
        # local Y along the bone; verified dot +1.00 on every parented bone),
        # then apply the delta: the character adopts the clip's absolute pose.
        F = {n: min_rot(Rw[n] @ yhat, g @ (Bw[n] @ yhat)) for n in names}
        lx, fz, hy = foot_traj(g, F)
        print(f"analytic g (clip faces {tuple(round(c, 2) for c in f)}): lateral={max(lx)-min(lx):5.2f} forward={max(fz)-min(fz):5.2f} height={max(hy)-min(hy):5.2f} hcorr={corr(hy, fh):+0.2f} fcorr={abs(corr(fz, ff)):0.2f}")
    else:
        # no toe bone to measure facing (Meshy/own-rig clips; the bind is the
        # rig's rest, checked above or taken from --bind-from, so F stays
        # identity): empirical search over the 24 axis-aligned frames
        best, bestScore = None, math.inf
        scored = []
        for gname, gc in CANDS.items():
            lx, fz, hy = foot_traj(gc, ID_F)
            lat = max(lx) - min(lx)
            h = max(hy) - min(hy)
            fwd = max(fz) - min(fz)
            range_score = abs(lat - truth_lat * k) + abs(h - truth_h * k) + abs(fwd - truth_fwd * k)
            # shape terms: the foot-height curve must match the authored one
            # in sign (an inverted conversion flips the lift arc); forward
            # matches unsigned (clip facing sign is unknown here)
            ch = corr(hy, fh)
            cf = abs(corr(fz, ff))
            score = range_score + 5.0 * (1.0 - ch) + 5.0 * (1.0 - cf)
            scored.append((score, gname, lat, fwd, h, ch, cf))
            if score < bestScore:
                best, bestScore = gname, score
        scored.sort()
        for score, gname, lat, fwd, h, ch, cf in scored[:5]:
            print(f"  g={gname:24s} lateral={lat:5.2f} forward={fwd:5.2f} height={h:5.2f} hcorr={ch:+0.2f} fcorr={cf:0.2f} score={score:5.2f}")
        g = CANDS[best]
        F = ID_F
        print(f"empirical pick g = {best} (score {bestScore:0.2f}, runner-up {scored[1][0]:0.2f})")
        g_name = best
        if forced_g is not None:
            assert forced_g in CANDS, f"--g={forced_g} is not one of the 24 candidates"
            g = CANDS[forced_g]
            g_name = forced_g
            print(f"FORCED g = {forced_g} (empirical would have been {best})")

    # JSON for the KeyframeSequence writer (kfs.py) + the world-space trajectories
    # impact.py scores for attackImpactDelaySecs and metrics.py for foot_lift /
    # impact_height. The retired script also emitted a `.luau` twin that built the
    # sequence Studio-side; the rbxmx writer replaces it, so it is gone.
    jhier = {n: (d["parent"] if d["parent"] != "HumanoidRootPart" else False) for n, d in rb.items()}
    # Pass 1: every frame's transferred rotations, the Bone.Transform quats and
    # each bone origin's rig-frame position with NO root motion (WPr), plus the
    # proportional hips delta. Root motion is added in pass 2, once the
    # vertical is known: root motion shifts every bone by the same vector, so
    # it can be added after the fact.
    roots = [n for n in order if rb[n]["parent"] == "HumanoidRootPart"]
    # a non-root bone the clip translates but --translate does not name: its
    # largest displacement in studs, reported as dropped
    dropped = {}
    for D in moves:
        for n, d in D.items():
            if n not in translate:
                dropped[n] = max(dropped.get(n, 0.0), k * float(np.linalg.norm(d)))
    dropped = {n: v for n, v in dropped.items() if v > DROPPED_TRANSLATION_TOL * rig_leg}
    for n in sorted(dropped):
        print(f"translation dropped on {n} (up to {dropped[n]:0.3f} studs); --translate={n} carries it")
    per_frame = []
    for fi, (t, A) in enumerate(frames):
        W, WPr, p, tr = {}, {}, {}, {}
        for n in order:
            pr = rb[n]["parent"]
            W[n] = _world(n, pr, A, W, g, F)
            Wp = W.get(pr, np.eye(3))
            # same accumulation foot_traj scores with, kept for every bone so the
            # hand chains resolve too: rig-frame position of each bone's origin
            WPr[n] = WPr.get(pr, np.zeros(3)) + (Wp @ Pw[n])
            if n in src:
                p[n] = [round(v, 5) for v in quat(m3(rb[n]["rot"]).T @ Wp.T @ W[n])]
            if n in translate:
                # the bone's own translation, mapped and scaled like the root
                # motion, then expressed in its rest frame under the parent's
                # transferred rotation (where the Animator applies a Pose
                # position); its children ride along
                d = k * (g @ moves[fi].get(n, np.zeros(3)))
                WPr[n] = WPr[n] + d
                tr[n] = [round(float(v), 4) for v in m3(rb[n]["rot"]).T @ Wp.T @ d]
        # root motion: hips delta from the reference, mapped into the rig frame
        # by the same g the rotations use and scaled to studs by k
        per_frame.append((t, W, WPr, p, k * (g @ (hips[fi] - rest_hips)), tr))
    ground = None
    if emit_root and root_y == "ground":
        # Ground lock: the vertical root offset puts the rig's lowest skinned
        # vertex on its rest level (the ground the rig was fitted to) on every
        # frame; the horizontal keeps the proportional delta. A proportional
        # hips delta cannot do this: library clips are not grounded against
        # their own bind (a walk's lowest foot swings 8 studs under and 4 over
        # it, a death sinks 14, an idle with a keyed hips scale hovers 3-4),
        # and the rig drops the clip's toe joints (witnessed 2026-09-23).
        low, ground = ground_lows(rig_mesh, arm, rb, order, Rw, Pw, [(W, WPr) for _t, W, WPr, _p, _h, _tr in per_frame])
    jframes = []
    traj = {n: [] for n in TRAJ_BONES}
    root_range = np.zeros(3)
    for fi, (t, W, WPr, p, hdelta, tr) in enumerate(per_frame):
        droot = np.zeros(3)
        frame_doc = {"t": round(t, 4), "p": p}
        if tr:
            frame_doc["r"] = dict(tr)
        if emit_root:
            droot = hdelta.copy()
            if ground is not None:
                droot[1] = ground["rest_low"] - low[fi]
            if root_xz == "none":
                droot[0] = droot[2] = 0.0
            # expressed in the root bone's own rest frame (a Pose CFrame
            # position is applied inside the bone's rest rotation, like
            # Bone.Transform). The HumanoidRootPart itself never moves: the
            # rig's physics box keeps standing, the mesh crouches, kneels or
            # lies down inside it.
            frame_doc.setdefault("r", {}).update(
                {n: [round(float(v), 4) for v in m3(rb[n]["rot"]).T @ droot] for n in roots})
            root_range = np.maximum(root_range, np.abs(droot))
        jframes.append(frame_doc)
        for n in TRAJ_BONES:
            if n in WPr:
                q = WPr[n] + droot
                traj[n].append([round(t, 4), float(q[0]), float(q[1]), float(q[2])])
    doc = {"hier": jhier, "frames": jframes, "traj": traj,
           "clip_seconds": frames[-1][0], "source": os.path.basename(clip_path),
           "root_motion": bool(emit_root), "root_ref": root_ref, "g": g_name, "g_forced": forced_g is not None,
           "root_range_studs": [round(float(v), 3) for v in root_range],
           "k": round(float(k), 5), "k_source": "leg_chain",
           "root_y": root_y if emit_root else None, "root_xz": root_xz if emit_root else None,
           "ground": ground, "held": held,
           "bind_from": (bind_from if bind_from == "clip" else os.path.basename(bind_from)) if bind_from else None,
           "bind_mismatch_deg": bind_mismatch, "bind_tolerance_deg": BIND_TOL_DEG,
           "bind_hips_offset_studs": round(hips_offset * k, 4) if hips_offset is not None else None,
           "bind_frame": bind_frame,
           "translate": sorted(translate), "translation_dropped": {n: round(v, 4) for n, v in sorted(dropped.items())},
           "trim": [t_start, t_end] if trim is not None else None}
    if emit_root:
        print(f"root motion: max |hips delta| xyz {[round(float(v), 2) for v in root_range]} studs")
    with open(out_path, "w") as fh:
        json.dump(doc, fh)
    print(f"emitted {out_path}: {len(jframes)} frames, clip duration {frames[-1][0]:0.2f}s, rig height {rig_h:0.1f}")


main()
