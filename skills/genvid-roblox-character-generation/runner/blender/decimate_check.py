"""Decimate a GLB to the Roblox skinned-mesh cap and report topology.
Run: blender --background --python decimate_check.py -- in.glb out.glb 20000"""
import json, sys
import bpy, bmesh

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst, cap = argv[0], argv[1], int(argv[2])
bpy.ops.wm.read_factory_settings(use_empty=True)
# merge_vertices=True: glTF export duplicates each vertex on a UV/normal seam
# (any textured mesh has at least one). Left split, the Decimate modifier's
# collapse treats each seam-side as its own disconnected island and can strand
# fragments as separate shells even at a mild ratio -- shells/euler genus0
# check below would then read a topologically sound mesh as broken. Welding
# coincident duplicates back together before decimating fixes that; UV/normal
# data on the surviving vertex is Blender's own merge choice, unrelated to the
# mesh.report.json topology numbers this script exists to produce.
bpy.ops.import_scene.gltf(filepath=src, merge_vertices=True)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
# join multi-object exports into one mesh so the cap is per shipped MeshPart
if len(meshes) > 1:
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes: o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
# meshes[0] (post-join, the sole surviving mesh) rather than whatever the glTF
# importer left active: a GLB with an Empty root node or an armature+mesh rig
# (both common vendor/rig shapes) leaves a non-mesh object active, and
# `.active or meshes[0]` never falls through to meshes[0] because a non-None
# non-mesh object is still truthy.
obj = meshes[0]
def tri_count(o): return sum(len(p.vertices) - 2 for p in o.data.polygons)
tris_in = tri_count(obj)
if tris_in > cap:
    # import's merge_vertices=True only welds seams the glTF importer itself
    # introduces; it does not touch flat-shaded input, where every face already
    # arrives as its own disconnected vertex island (split normals per face) before
    # the Decimate modifier ever runs -- hard-surface armor plausibly ships flat-
    # shaded. Weld here, on the actual mesh data, so the Decimate modifier's
    # collapse operates on a single connected shell regardless of input shading.
    # Scoped to the over-cap path only: this writes back into obj.data, which is
    # the mesh exported to dst, so an under-cap input that needs no processing
    # must pass through unchanged rather than come out silently smoothed.
    bm = bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.to_mesh(obj.data); bm.free()
    obj.data.update()
    mod = obj.modifiers.new("dec", "DECIMATE"); mod.ratio = cap / tris_in * 0.98
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier="dec")
tris_out = tri_count(obj)
bm = bmesh.new(); bm.from_mesh(obj.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
V, E, F = len(bm.verts), len(bm.edges), len(bm.faces)
euler = V - E + F
# shells: connected components over vertices
seen, shells = set(), 0
for v in bm.verts:
    if v.index in seen: continue
    shells += 1; stack = [v]
    while stack:
        cur = stack.pop()
        if cur.index in seen: continue
        seen.add(cur.index)
        for e in cur.link_edges:
            o = e.other_vert(cur)
            if o.index not in seen: stack.append(o)
bm.free()
genus0 = (euler == 2 * shells) and shells == 1
bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True)
print(json.dumps({"tris_in": tris_in, "tris_out": tris_out, "euler": euler, "genus0": genus0, "shells": shells}))
