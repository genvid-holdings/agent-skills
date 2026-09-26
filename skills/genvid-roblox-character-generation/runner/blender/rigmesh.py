"""The rig's rest frame from rest.json, and the rig's own skinned mesh fitted into it.

Shared by poses.py (the ground lock skins the fitted mesh per frame) and
contact.py (each striking bone's rest offset down to the skin). rest.json is
the rig's bone rest data dumped from Studio (per bone: parent, rot 3x3
row-major, pos, parent-relative), at the rig's final scale; the rig frame is
the HumanoidRootPart's, in studs.
"""
import bpy
import math
import os

import numpy as np

# The mesh fit refuses when a rest bone origin lands farther than this fraction
# of the mesh height from where the mesh's own armature puts it: the mesh is
# then not the rig rest.json was dumped from.
GROUND_FIT_TOL = 0.01


def m3(v):
    return np.array(v, dtype=float).reshape(3, 3)


def rest_order(rb):
    """Every bone reachable from the root part, parents first, and the sorted
    names of those it does not reach."""
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
    return order, sorted(set(rb) - set(order))


def rest_rotations(rb, order):
    """Each bone's world rest rotation in the rig frame."""
    Rw = {}
    for n in order:
        Rw[n] = Rw.get(rb[n]["parent"], np.eye(3)) @ m3(rb[n]["rot"])
    return Rw


def rest_origins(rb, order, Rw, Pw):
    """Each bone's rest origin in the rig frame (studs): parent origin plus
    the parent's world rest rotation applied to the bone's offset."""
    P0 = {}
    for n in order:
        pr = rb[n]["parent"]
        P0[n] = P0.get(pr, np.zeros(3)) + Rw.get(pr, np.eye(3)) @ Pw[n]
    return P0


def skinned_rest(path, P0, order, flag):
    """The rig file's skinned mesh at rest, in the rig frame. The file (glb or
    fbx) is imported beside whatever the scene holds; its armature's bone
    heads for `order` are fitted to rest.json's origins `P0` by a similarity
    (scale, rotation, offset), refused past GROUND_FIT_TOL of the mesh height.
    Every skinned mesh parented to the armature is read: a multi-mesh rig can
    list a head or accessory mesh first. Returns (V, W, col, info): vertices
    (studs, rig frame) carrying any weight on `order`, their weights per bone
    normalised to 1, the bone -> column map, and the fit. `flag` names the
    option the file came in on, for the refusals."""
    before = set(bpy.data.objects)
    if path.lower().endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        bpy.ops.import_scene.fbx(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    rig = next((o for o in new if o.type == "ARMATURE"), None)
    meshes = [o for o in new if o.type == "MESH" and o.parent is rig and o.vertex_groups] if rig else []
    if rig is None or not meshes:
        raise ValueError(f"{flag}={path}: no armature with a skinned mesh in it")
    missing = [n for n in order if n not in rig.data.bones]
    if missing:
        raise ValueError(f"{flag}={path}: armature lacks bones {missing}")
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
    print(f"rig mesh {os.path.basename(path)} fitted at {1 / s:0.3f} studs per unit, "
          f"max bone-origin error {fit_err:0.4f} studs (tolerance {tol:0.3f}), mesh height {height:0.2f} studs")
    if not fit_err <= tol:
        raise ValueError(f"{flag}={path} does not fit rest.json: a bone origin is {fit_err:0.3f} studs off "
                         f"(tolerance {tol:0.3f}); pass the skinned file of the rig rest.json was dumped from")
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
    info = {"rig_mesh": os.path.basename(path), "fit_err_studs": round(fit_err, 5),
            "tolerance_studs": round(tol, 5), "studs_per_unit": round(1 / s, 5),
            "vertices": int(len(Vr)), "meshes": len(meshes)}
    return Vr, Wt, col, info


def skin(V, W, col, P0, Rw, Wd, WPr):
    """The fitted rest mesh `V` posed, in the rig frame: each vertex blended
    over its bones' rigid motions, v' = sum_b w_b (Wd_b Rw_b^T (v - P0_b) +
    WPr_b), with `Wd`/`WPr` each bone's posed world rotation and origin (no
    root motion; add it after)."""
    out = np.zeros_like(V)
    for n, c in col.items():
        w = W[:, c]
        if w.any():
            out += w[:, None] * ((V - P0[n]) @ (Wd[n] @ Rw[n].T).T + WPr[n])
    return out


def quat_matrix(q):
    """The rotation matrix of quaternion (x, y, z, w)."""
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])

