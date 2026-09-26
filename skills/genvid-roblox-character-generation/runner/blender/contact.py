#!/usr/bin/env python
"""Where a clip's striking limb makes contact, measured on the skin at the strike.

Run headless:
  blender --background --python contact.py -- <rig.glb|fbx> <rest.json> <poses.json> <out.json>

The rig file (the skinned rig rest.json was dumped from) is fitted to rest.json
by the ground lock's similarity fit (`rigmesh.skinned_rest`, refused past 1% of
the mesh height). The strike is read off the poses doc's trajectory, hands
first (`impact.strike`: a hand whenever one drops at least half as far as the
largest drop, a foot only when none does). That frame's pose is rebuilt from the
poses doc: each bone's world rotation from its Bone.Transform quaternion and its
rest, each origin by accumulation, a translated bone's Pose position added, and
the root motion added to all; the rebuilt striking bone must land on the doc's
own trajectory sample, or the doc is refused as not from this rest.json. The
mesh is skinned at that pose, and the contact is the lowest vertex whose
dominant skin weight is the striking bone or a bone under it, in the rig frame
(studs). Eval row E21 compares it with the sole plane.

out.json: {"bone", "t", "lowest_y", "bones", "vertices", "fit"}.
"""
import bpy
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from rigmesh import m3, quat_matrix, rest_order, rest_origins, rest_rotations, skin, skinned_rest  # noqa: E402
import impact  # noqa: E402

# the rebuilt striking bone must land within this of the doc's trajectory (studs;
# the doc rounds quaternions to 5 decimals)
REBUILD_TOL = 0.01


def under(rb, bone):
    """`bone` and every bone below it."""
    out, stack = [], [bone]
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(c for c, d in rb.items() if d["parent"] == n)
    return out


def main():
    rig_path, rest_path, poses_path, out_path = sys.argv[sys.argv.index("--") + 1:][:4]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rb = json.load(open(rest_path))
    doc = json.load(open(poses_path))
    order, _unreached = rest_order(rb)
    Rw = rest_rotations(rb, order)
    Pw = {n: np.array(rb[n]["pos"]) for n in order}
    P0 = rest_origins(rb, order, Rw, Pw)
    hit = impact.strike(doc["traj"], prefer=impact.HANDS)
    if hit is None:
        raise ValueError(f"{poses_path}: no limb drops, so the clip has no strike to measure")
    bone, t = hit
    frame = next((f for f in doc["frames"] if abs(f["t"] - t) < 1e-6), None)
    if frame is None:
        raise ValueError(f"{poses_path}: no frame at the strike time {t}")
    p, r = frame["p"], frame.get("r") or {}
    roots = [n for n in order if rb[n]["parent"] == "HumanoidRootPart"]
    droot = next((m3(rb[n]["rot"]) @ np.array(r[n]) for n in roots if n in r), np.zeros(3))
    W, WPr = {}, {}
    for n in order:
        pr = rb[n]["parent"]
        Wp = W.get(pr, np.eye(3))
        W[n] = Wp @ m3(rb[n]["rot"]) @ (quat_matrix(p[n]) if n in p else np.eye(3))
        WPr[n] = WPr.get(pr, np.zeros(3)) + Wp @ Pw[n]
        if n in r and n not in roots:
            WPr[n] = WPr[n] + Wp @ m3(rb[n]["rot"]) @ np.array(r[n])
    sample = next(s for s in doc["traj"][bone] if abs(s[0] - t) < 1e-6)
    miss = float(np.linalg.norm(WPr[bone] + droot - np.array(sample[1:])))
    if miss > REBUILD_TOL:
        raise ValueError(f"{poses_path}: the rebuilt {bone} misses the doc's own trajectory by {miss:0.4f} studs "
                         f"at t={t}; the doc was not transferred onto {rest_path}")
    V, Wt, col, info = skinned_rest(rig_path, P0, order, "rig")
    posed = skin(V, Wt, col, P0, Rw, W, WPr) + droot
    bones = [b for b in under(rb, bone) if b in col]
    mine = np.isin(Wt.argmax(1), [col[b] for b in bones])
    if not mine.any():
        raise ValueError(f"{rig_path}: no vertex is skinned mainly to {bone} or a bone under it")
    lowest = float(posed[mine][:, 1].min())
    with open(out_path, "w") as fh:
        json.dump({"bone": bone, "t": t, "lowest_y": round(lowest, 5), "bones": bones,
                   "vertices": int(mine.sum()), "fit": info}, fh)
    print(f"contact: {bone} (with {', '.join(bones[1:]) or 'no bones under it'}) at t={t}, lowest skin vertex "
          f"{lowest:0.3f} studs (rig frame), {int(mine.sum())} vertices")


main()
