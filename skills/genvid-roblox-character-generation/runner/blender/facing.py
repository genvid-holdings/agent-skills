#!/usr/bin/env python
"""Normalize which way a generated mesh faces, before it is rigged.

Witnessed 2026-09-04 (bake-off leg B): Tripo H3.1 meshes face +/-X with their
span along Y, while Meshy meshes -- and Meshy's auto-rig, which is what rigs
both legs -- assume facing -Y with the span along X. Rigging an unrotated Tripo
mesh produced a skeleton with both shoulders 12 cm apart inside the torso on a
1.59 m body, and forearm weight bleed to match. Nothing downstream recovers from
that, so the mesh is turned here, before the rig call.

How the turn is picked, in two stages, because neither alone is enough:

  1. SILHOUETTE. Render the mesh from the front at yaw 0/90/180/270 and score
     each against the approved plate with the same IoU the E6 gate uses. This
     finds the AXIS -- whether the character's span lies along X or Y.
  2. FRONT vs BACK. Silhouette cannot separate them on a symmetric character:
     leg B scored 0.449 at yaw 90 against 0.448 at yaw 270. So the winner is
     compared against its own 180-degree partner on COLOR, over the head region
     of a textured render -- the face is where a character's front and back
     differ most. Lower mean patch distance wins.

Run headless:
  blender --background --python facing.py -- mesh.glb plate.png out.json [out.glb]

With `out.glb`, the mesh is written back turned by the chosen yaw (mesh data, so
the file needs no object transform to be correct). Prints exactly one line:
RUNNER_RESULT {"yaw_deg": ..., "iou": {...}, "head_distance": {...}, ...}
"""
import json
import math
import sys
from pathlib import Path

import bpy
import mathutils
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskutil import (  # noqa: E402
    alpha_mask, foreground_mask, head_patch, iou, load_rgb, load_rgba, patch_distance, patch_ncc,
)

WIDTH, HEIGHT = 512, 768
YAWS = (0, 90, 180, 270)


def meshes():
    return [o for o in bpy.data.objects if o.type == "MESH"]


def turn(objs, degrees):
    """Rotate mesh DATA about Z (the same space every other runner Blender step
    reads geometry in, so the written file needs no object transform)."""
    if not degrees:
        return
    R = mathutils.Matrix.Rotation(math.radians(degrees), 4, "Z")
    for obj in objs:
        obj.data.transform(R)
    # obj.bound_box is cached: without this the NEXT frame_camera would fit the
    # camera to the pre-turn bounds and, on an off-center mesh, clip the render
    # this yaw is scored from.
    bpy.context.view_layer.update()


def frame_camera(objs):
    lo = np.array([1e9, 1e9, 1e9])
    hi = np.array([-1e9, -1e9, -1e9])
    for obj in objs:
        for corner in obj.bound_box:
            world = obj.matrix_world @ mathutils.Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], world[i])
                hi[i] = max(hi[i], world[i])
    center = (lo + hi) / 2.0
    size = hi - lo
    aspect = WIDTH / HEIGHT
    ortho = max(max(size[2], 1e-3), max(size[0], 1e-3) / aspect) * 1.2
    cam = bpy.context.scene.camera
    if cam is None:
        cam_data = bpy.data.cameras.new("FacingCam")
        cam_data.type = "ORTHO"
        cam_data.sensor_fit = "VERTICAL"
        cam = bpy.data.objects.new("FacingCam", cam_data)
        bpy.context.scene.collection.objects.link(cam)
        bpy.context.scene.camera = cam
    cam.data.ortho_scale = ortho
    # Blender front view: camera on -Y looking toward +Y, up = +Z. A character
    # facing -Y therefore faces the camera, which is the convention this script
    # normalizes to.
    cam.location = (center[0], center[1] - max(size[1], 1.0) * 2.0, center[2])
    cam.rotation_euler = (1.5707963, 0.0, 0.0)


def setup_scene():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.render_aa = "OFF"
    scene.display.shading.show_shadows = False
    scene.display.shading.show_cavity = False
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    # Transparent film: the alpha channel is the silhouette, so a dark texture
    # cannot be mistaken for background the way it can against a black backdrop.
    scene.render.film_transparent = True


def render(path, textured):
    scene = bpy.context.scene
    if textured:
        scene.display.shading.light = "FLAT"
        scene.display.shading.color_type = "TEXTURE"
    else:
        scene.display.shading.light = "FLAT"
        scene.display.shading.color_type = "SINGLE"
        scene.display.shading.single_color = (1.0, 1.0, 1.0)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    mesh_path, plate_path, out_path = argv[0], argv[1], argv[2]
    out_glb = argv[3] if len(argv) > 3 else None

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=mesh_path)
    objs = meshes()
    if not objs:
        raise RuntimeError("no mesh objects imported from %r" % mesh_path)
    setup_scene()

    plate_rgb = load_rgb(plate_path)
    plate_mask = foreground_mask(plate_rgb)
    plate_head = head_patch(plate_rgb, plate_mask)

    scores = {}
    heads = {}
    # Rotate a quarter turn at a time, so after the fourth render the mesh is
    # back where it started and the chosen yaw can be applied once, cleanly.
    for yaw in YAWS:
        frame_camera(objs)
        sil = load_rgba(render(out_path + (".yaw%d.png" % yaw), textured=False))
        mask = alpha_mask(sil)
        scores[yaw] = iou(mask, plate_mask)
        tex = load_rgba(render(out_path + (".yaw%d.tex.png" % yaw), textured=True))
        heads[yaw] = head_patch(tex[:, :, :3], alpha_mask(tex))
        turn(objs, 90)

    best = max(YAWS, key=lambda y: scores[y])
    partner = (best + 180) % 360
    head_distance = {best: patch_distance(heads[best], plate_head),
                     partner: patch_distance(heads[partner], plate_head)}
    head_ncc = {best: patch_ncc(heads[best], plate_head),
                partner: patch_ncc(heads[partner], plate_head)}
    chosen = best
    flipped = False
    if head_distance[best] is not None and head_distance[partner] is not None \
            and head_distance[partner] < head_distance[best]:
        # Same silhouette, better face match the other way round: the IoU winner
        # was the character's BACK.
        chosen = partner
        flipped = True

    turn(objs, chosen)
    if out_glb:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objs:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objs[0]
        bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB", use_selection=True)

    result = {
        "yaw_deg": chosen,
        "iou": dict((str(y), scores[y]) for y in YAWS),
        "iou_best_yaw_deg": best,
        "head_distance": dict((str(y), head_distance[y]) for y in head_distance),
        "head_ncc": dict((str(y), head_ncc[y]) for y in head_ncc),
        "flipped_by_head": flipped,
        "out_glb": out_glb,
    }
    with open(out_path, "w") as f:
        json.dump(result, f)
    print("RUNNER_RESULT " + json.dumps(result))


main()
