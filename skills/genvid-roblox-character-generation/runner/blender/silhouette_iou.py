"""E5/E6: does the decimated mesh still read as the approved plate, silhouette-wise?

Renders an orthographic front view of the mesh (Workbench, flat white on black),
masks it and the plate PNG by distance-from-border-median color, crops each mask
to its own bounding box, resizes both to the same height (nearest-neighbor),
centers them, and reports IoU. `has_basecolor` is true iff any material on the
mesh has an Image Texture feeding a Principled BSDF's Base Color input.

Run: blender --background --python silhouette_iou.py -- mesh.20k.glb plate.png out.json
Prints exactly one line: RUNNER_RESULT {"iou": x, "has_basecolor": bool}
"""
import json, sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The mask/IoU maths lives in maskutil so this measurement and the facing pick
# (blender/facing.py) cannot drift apart while still reporting numbers that look
# comparable.
from maskutil import (  # noqa: E402
    BORDER_THRESHOLD, crop_to_bbox, foreground_mask as _foreground_mask, iou as _iou,
    load_rgb as _load_rgb, resize_nearest,
)

argv = sys.argv[sys.argv.index("--") + 1:]
mesh_path, plate_path, out_path = argv[0], argv[1], argv[2]

WIDTH, HEIGHT = 512, 768


def _has_basecolor(objs):
    for obj in objs:
        for slot in obj.material_slots:
            mat = slot.material
            if not mat or not mat.use_nodes:
                continue
            for node in mat.node_tree.nodes:
                if node.type != "BSDF_PRINCIPLED":
                    continue
                base = node.inputs.get("Base Color")
                if base and base.is_linked:
                    src = base.links[0].from_node
                    if src.type == "TEX_IMAGE" and src.image is not None:
                        return True
    return False


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=mesh_path)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh objects imported from %r" % mesh_path)
    has_basecolor = _has_basecolor(meshes)

    # frame all mesh geometry
    min_c = np.array([1e9, 1e9, 1e9]); max_c = np.array([-1e9, -1e9, -1e9])
    for obj in meshes:
        for corner in obj.bound_box:
            world = obj.matrix_world @ __import__("mathutils").Vector(corner)
            for i in range(3):
                min_c[i] = min(min_c[i], world[i]); max_c[i] = max(max_c[i], world[i])
    center = (min_c + max_c) / 2.0
    size = max_c - min_c
    # Front view: world X is screen-horizontal, world Z is screen-vertical. Fit the
    # camera to the VERTICAL sensor explicitly (not AUTO, whose choice of axis
    # depends on which resolution dimension is larger) and grow ortho_scale so the
    # horizontal extent also fits once the resolution aspect ratio is applied --
    # otherwise a portrait render (HEIGHT > WIDTH) silently clips the sides.
    aspect = WIDTH / HEIGHT
    needed_vertical = max(size[2], 1e-3)
    needed_horizontal = max(size[0], 1e-3)
    ortho_scale = max(needed_vertical, needed_horizontal / aspect) * 1.2

    cam_data = bpy.data.cameras.new("SilhouetteCam")
    cam_data.type = "ORTHO"
    cam_data.sensor_fit = "VERTICAL"
    cam_data.ortho_scale = ortho_scale
    cam = bpy.data.objects.new("SilhouetteCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    # Blender front view: camera on -Y looking toward +Y (up = +Z)
    cam.location = (center[0], center[1] - max(size[1], 1.0) * 2.0, center[2])
    cam.rotation_euler = (1.5707963, 0.0, 0.0)  # 90 deg about X: -Y-facing camera looks +Y
    bpy.context.scene.camera = cam

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "FLAT"
    scene.display.shading.color_type = "SINGLE"
    scene.display.shading.single_color = (1.0, 1.0, 1.0)
    scene.display.render_aa = "OFF"
    scene.display.shading.show_shadows = False
    scene.display.shading.show_cavity = False
    scene.view_settings.view_transform = "Standard"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.0, 0.0, 0.0)
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    render_path = out_path + ".render.png"
    scene.render.filepath = render_path
    bpy.ops.render.render(write_still=True)

    mesh_rgb = _load_rgb(render_path)
    mesh_mask = _foreground_mask(mesh_rgb)

    plate_rgb = _load_rgb(plate_path)
    plate_mask = _foreground_mask(plate_rgb)

    iou = _iou(mesh_mask, plate_mask)

    result = {"iou": iou, "has_basecolor": has_basecolor}
    with open(out_path, "w") as f:
        json.dump(result, f)
    print("RUNNER_RESULT " + json.dumps(result))


main()
