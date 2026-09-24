#!/usr/bin/env python
"""Convert a caller's FBX or OBJ into the static GLB mesh prep reads.

    blender --background --python to_glb.py -- <in.fbx|in.obj> <fbx|obj> <out.glb>

The mesh stage binds an unrigged mesh: the rig stage rigs it afterwards, and
decimate_check.py exports the mesh alone anyway. So a skeleton that arrives with
the model is dropped here, and the mesh is kept in its REST shape (the geometry
it was bound to the skeleton in), never whatever pose the file was exported in.
Every mesh object is kept; images are packed into the GLB, so a texture the
source file embeds, or one sitting beside it, travels with the mesh.

Blender imports binary FBX 7.1 or later only; mesh ingest refuses the others
before this runs. Prints exactly one line on success:
RUNNER_RESULT {"format": ..., "meshes": n, "bones_dropped": n, "images": n, "has_basecolor": bool}
and exits nonzero, writing nothing, when the file holds no mesh.
"""
import json
import sys
import traceback

import bpy


def _import(src, kind):
    if kind == "fbx":
        bpy.ops.import_scene.fbx(filepath=src, use_anim=False)
    elif kind == "obj":
        bpy.ops.wm.obj_import(filepath=src)
    else:
        raise ValueError("unsupported kind %r: fbx or obj" % kind)


def _has_basecolor(objs):
    """True when some material's Base Color is fed by an image that has pixels."""
    for obj in objs:
        for slot in obj.material_slots:
            mat = slot.material
            if not (mat and mat.use_nodes and mat.node_tree):
                continue
            for node in mat.node_tree.nodes:
                if node.type != "BSDF_PRINCIPLED":
                    continue
                for link in node.inputs["Base Color"].links:
                    img = getattr(link.from_node, "image", None)
                    # size loads the pixels on demand; a missing file reads as 0 x 0.
                    if img is not None and img.size[0] > 0:
                        return True
    return False


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    src, kind, out = argv[0], argv[1], argv[2]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _import(src, kind)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh objects imported from %r" % src)
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    bones = sum(len(a.data.bones) for a in armatures)
    for obj in meshes:
        # Without its Armature modifier the mesh evaluates in its rest shape.
        for mod in [md for md in obj.modifiers if md.type == "ARMATURE"]:
            obj.modifiers.remove(mod)
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = world
        obj.animation_data_clear()
        if obj.data.shape_keys:
            obj.shape_key_clear()
    for obj in [o for o in bpy.data.objects if o.type != "MESH"]:
        bpy.data.objects.remove(obj, do_unlink=True)
    for img in bpy.data.images:
        if img.source == "FILE" and not img.packed_file and img.has_data:
            img.pack()
    basecolor = _has_basecolor(meshes)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True, export_skins=False,
                              export_animations=False)
    result = {"format": kind, "meshes": len(meshes), "bones_dropped": bones,
              "images": len([i for i in bpy.data.images if i.has_data]), "has_basecolor": basecolor}
    print("RUNNER_RESULT " + json.dumps(result))


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
