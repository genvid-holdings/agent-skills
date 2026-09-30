"""Decimate each mesh part of a GLB to the Roblox skinned-mesh cap and report topology.
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
# The cap is per mesh object: the engine caps each skinned MeshPart, so a model of
# several parts may carry more than the cap in total. Each part is capped on its
# own and kept apart (joining them first would decimate every part to fit one
# cap); the total belongs to a class triangle budget, which the caller checks.
def tri_count(o): return sum(len(p.vertices) - 2 for p in o.data.polygons)
tris_in = sum(tri_count(o) for o in meshes)
for obj in meshes:
    t = tri_count(obj)
    if t <= cap:
        continue
    # import's merge_vertices=True only welds seams the glTF importer itself
    # introduces; it does not touch flat-shaded input, where every face already
    # arrives as its own disconnected vertex island (split normals per face) before
    # the Decimate modifier ever runs -- hard-surface armor plausibly ships flat-
    # shaded. Weld here, on the actual mesh data, so the Decimate modifier's
    # collapse operates on a single connected shell regardless of input shading.
    # Scoped to the over-cap path only: this writes back into obj.data, which is
    # the mesh exported to dst, so a part under the cap that needs no processing
    # must pass through unchanged rather than come out silently smoothed.
    bm = bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.to_mesh(obj.data); bm.free()
    obj.data.update()
    t = tri_count(obj)
    if t <= cap:
        continue
    mod = obj.modifiers.new("dec", "DECIMATE"); mod.ratio = cap / t * 0.98
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier="dec")
parts = {o.name: {"tris": tri_count(o)} for o in meshes}
tris_out = sum(p["tris"] for p in parts.values())


def topology(o):
    """(V, E, F, shells) of one part, coincident vertices welded."""
    bm = bmesh.new(); bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    V, E, F = len(bm.verts), len(bm.edges), len(bm.faces)
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
                w = e.other_vert(cur)
                if w.index not in seen: stack.append(w)
    bm.free()
    return V, E, F, shells


# Euler characteristic and shells add across disjoint parts.
V = E = F = shells = 0
for o in meshes:
    v, e, f, sh = topology(o)
    V += v; E += e; F += f; shells += sh
euler = V - E + F
genus0 = (euler == 2 * shells) and shells == 1
bpy.ops.object.select_all(action="DESELECT")
for o in meshes: o.select_set(True)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True)
print(json.dumps({"tris_in": tris_in, "tris_out": tris_out, "euler": euler, "genus0": genus0, "shells": shells,
                  "parts": parts}))
