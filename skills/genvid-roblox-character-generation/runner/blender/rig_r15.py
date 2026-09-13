#!/usr/bin/env python
"""Stage 3 (runner): convert a vendor-rigged character (Mixamo-convention
skeleton) into an R15-compatible skinned FBX for the Roblox 3D Importer. No
Auto-Setup anywhere: the mesh that ships is the mesh the vendor skinned.

Run headless:
  blender --background --python rig_r15.py -- <rigged.glb|.fbx> <out.fbx> [stylized.png]

What it does: normalize vendor bone spellings, rename the 15 keeper bones to
R15 names, fold the extra bones' weights into their R15 neighbors (leaf-up so
chains reparent cleanly), add a Root bone, export FBX with embedded textures,
decimate back under Roblox's 20,000-triangle skinned-mesh cap when the vendor
re-meshed over it, and write `rig.report.json` beside the output.

The optional third argument swaps the material's base-color image for a
stylized texture BEFORE export. This is the only reliable way to deliver a
texture change: the Roblox importer packages the texture into the mesh asset
itself, and runtime SurfaceAppearance/TextureID overrides never re-texture a
skinned MeshPart (verified live in Edit AND Play, 2026-07-17). A preview
render (front + three-quarter view, <out.fbx>.view0.png / .view1.png) is
written alongside every export so the look can be judged without spending a
Studio import; those two frames are the rig-preview media the runner binds.

Ported from the retired pipeline's stage_f_rig.py. Changes from that source:
the RENAME/MERGE tables now come from the runner's `rigtables` module (single
source shared with the pose transfer); every bone name is normalized first so
a Tripo `spec=mixamo` skeleton (`mixamorig:` prefixes, `Spine1`/`Spine2`)
lands on the same table; `.fbx` input is accepted alongside `.glb`; a missing
keeper bone is a recorded WARN rather than a hard assert, with the verdict
carried in rig.report.json and a non-zero exit.

The FBX is exported once and, beside it, the SAME scene is exported a second
time as glTF-binary: Genvid's roblox/r15-rigged conformance profile (spec
1.1.0) reads gltf-binary only and fails an FBX outright at container.format,
so the GLB twin is what the profile can actually measure. That twin's
rig.forward-axis check needs its own fix, separate from container.format:
three untouched twins (witnessed 2026-09-04)
measured +Z against a profile that requires -Z, while those same rigs' FBX
faced -Z once Studio imported it. The FBX was never wrong: Blender's FBX
and glTF exporters write IDENTICAL raw coordinates for one scene (see the
GLB_TWIN_YAW_DEG comment below for how that was checked); the two
CONSUMERS -- the Roblox 3D Importer and Genvid's roblox/r15-rigged profile
-- read that one scene's handedness two different ways, and which side
holds the convention is not witnessed. So the twin is exported from a
scene turned a half turn about up (GLB_TWIN_YAW_DEG, armature and mesh
together, turned back afterwards so the FBX export is unaffected). A
turned twin passed the profile outright. The turn is read back off the
armature after being applied, not assumed landed, because an object-level
write on an armature still driven by an imported action gets re-driven away
by the next depsgraph evaluation; `rig.report.json` carries whatever
actually landed as `glb_twin_yaw_deg` (0 when it did not).
"""
import json
import sys
from pathlib import Path

import bpy

# rigtables lives in the runner package dir, one level up from blender/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rigtables import RENAME, merge_plan, normalize  # noqa: E402


def swap_basecolor(meshes, texture_path):
    """Point ONLY the Base Color image at the stylized texture, and strip
    every other texture input (normal/metallic/roughness). Swapping all
    TEX_IMAGE nodes blindly poisons the shading maps with the stylized
    atlas (live find 2026-07-17: the importer packaged it as a normal map
    and the body rendered as a pale sky-lit wash), and the cartoon read
    wants a matte material with no PBR maps anyway."""
    img = bpy.data.images.load(texture_path)
    swapped = 0
    for me in meshes:
        for slot in me.material_slots:
            mat = slot.material
            if mat is None or not mat.use_nodes:
                continue
            tree = mat.node_tree
            bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf is None:
                continue
            base = bsdf.inputs["Base Color"]
            for link in list(base.links):
                if link.from_node.type == "TEX_IMAGE":
                    link.from_node.image = img
                    swapped += 1
            # strip all other image-fed inputs (normal maps arrive via a
            # NORMAL_MAP node; metallic/roughness/specular link directly)
            for inp in bsdf.inputs:
                if inp.name == "Base Color":
                    continue
                for link in list(inp.links):
                    tree.links.remove(link)
            bsdf.inputs["Metallic"].default_value = 0.0
            bsdf.inputs["Roughness"].default_value = 0.9
            # The vendor wires the SAME atlas into Emission Color; with the
            # link cut, a nonzero default would white-glow the whole model.
            # In-engine glow is Highlight+PointLight, never material emission.
            bsdf.inputs["Emission Strength"].default_value = 0.0
            bsdf.inputs["Emission Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            # drop now-orphaned texture nodes so the exporter can't embed them
            for node in list(tree.nodes):
                if node.type in ("TEX_IMAGE", "NORMAL_MAP") and node.type == "TEX_IMAGE" and node.image is not img:
                    tree.nodes.remove(node)
                elif node.type == "NORMAL_MAP":
                    tree.nodes.remove(node)
    print("swapped %d base-color node(s) -> %s" % (swapped, texture_path))
    assert swapped > 0, "no base-color image node found to swap"


def preview_render(out_path):
    """Two-angle turntable still of the textured mesh on a neutral bg."""
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    # Standard view transform: the default AgX crushes midtone textures to
    # near-black in previews (live find 2026-07-18, small/large mid-gray
    # bodies); Roblox renders base color close to plain sRGB
    scene.view_settings.view_transform = "Standard"
    scene.render.resolution_x = 640
    scene.render.resolution_y = 900
    scene.render.film_transparent = False
    from mathutils import Vector as _V

    all_pts = []
    for o in bpy.data.objects:
        if o.type == "MESH":
            all_pts += [o.matrix_world @ _V(c) for c in o.bound_box]
    if not all_pts:
        print("WARN: no mesh to preview-render")
        return []
    zs = [p.z for p in all_pts]
    xs = [p.x for p in all_pts]
    ys = [p.y for p in all_pts]
    cx, cy, cz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    h = max(zs) - min(zs)
    cam_data = bpy.data.cameras.new("PrevCam")
    cam = bpy.data.objects.new("PrevCam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    import math
    from mathutils import Vector

    frames = []
    for i, ang in enumerate((0.0, math.radians(40))):
        d = h * 2.6
        cam.location = (cx + d * math.sin(ang), cy - d * math.cos(ang), cz)
        direction = Vector((cx, cy, cz)) - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = out_path + ".view%d.png" % i
        bpy.ops.render.render(write_still=True)
        frames.append(scene.render.filepath)
    print("preview frames:", frames)
    return frames


def load_input(path):
    """Import the vendor rig and put its meshes in the armature's own frame.

    `.fbx` as well as `.glb`: the Tripo direct-API rig leg returns FBX only, and
    fal's rigging endpoint returns both.

    `use_anim=False` on the FBX is load-bearing, not tidiness. A vendor FBX
    carries object-level location/rotation_euler/scale fcurves on the armature
    (witnessed 2026-09-04 on the bake-off rig): with that action attached the
    depsgraph re-drives those channels on its next evaluation -- the armature's
    edit-mode pass below -- so anything this script does to the armature OBJECT
    silently reverts before export. An applied unit scale came back as 0.01 (a
    100x-too-small export) and the origin relocation at the end of main() was
    undone, both while rig.report.json still read PASS.
    """
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path, use_anim=False)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
    flatten_into_armature_space()


def flatten_into_armature_space():
    """Bake each skinned mesh's transform RELATIVE TO THE ARMATURE into its
    vertex data, so mesh data coordinates and bone (edit-space) coordinates are
    one frame. World positions are unchanged: the object matrix is set to the
    armature's own by the same step that removes it from the data.

    glTF hands the mesh over in the armature's frame already, so this is a
    no-op there. A vendor FBX does not: witnessed 2026-09-04 on the bake-off
    rig, the armature imports with an identity rotation and a 0.01 unit scale
    while the skinned mesh imports as its CHILD carrying a 90-degree X rotation
    over Y-up vertex data. Every `me.data.transform(...)` in main() -- the
    root-origin shift AND the facing yaw -- is computed from bone positions, so
    on that input a `Matrix.Rotation(..., 'Z')` on mesh data turns the character
    about world Y: the bones yaw upright and the mesh lies down.
    """
    import mathutils
    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm is None:
        return
    identity = mathutils.Matrix.Identity(4)
    inv = arm.matrix_world.inverted()
    for me in [o for o in bpy.data.objects if o.type == "MESH"]:
        rel = inv @ me.matrix_world
        if all(abs(rel[r][c] - identity[r][c]) < 1e-6 for r in range(4) for c in range(4)):
            continue
        me.data.transform(rel)
        me.parent = arm
        me.matrix_parent_inverse = identity.copy()
        me.matrix_basis = identity.copy()
        print("flattened %s into the armature's frame" % me.name)


def unweighted_fraction(meshes, final_bones):
    """Fraction of skinned-mesh vertices carrying no weight on any surviving
    R15 bone (eval-matrix row E8, threshold <= 0.01). Weight on a vertex group
    that is not one of the final bones does not deform anything after the
    conversion, so it does not count as weighted."""
    total, unweighted = 0, 0
    keep_names = set(final_bones)
    for me in meshes:
        keep = set(vg.index for vg in me.vertex_groups if vg.name in keep_names)
        for v in me.data.vertices:
            total += 1
            w = sum(g.weight for g in v.groups if g.group in keep)
            if w <= 1e-6:
                unweighted += 1
    return (float(unweighted) / total) if total else 1.0


# Offline skeleton-fit gate (eval row E10b). Shoulder-bone separation over the
# mesh's largest span, measured on the RAW vendor rig before any Studio step.
# Witnessed 2026-09-04 on the bake-off: leg A 0.48 m over a 1.80 m span = 0.27
# (a skeleton that fits its mesh); leg B v1, rigged from an unrotated Tripo mesh
# facing the wrong way, 0.12 over 1.59 = 0.075 -- both shoulders 12 cm apart
# INSIDE the torso, with forearm weight bleed to match. The gate is 0.15.
MIN_SHOULDER_SEP_FRAC = 0.15
# Beyond this, the shoulder axis is not a 90-degree axis-convention mismatch --
# it is a skeleton sitting crooked in its mesh, and snapping it to the nearest
# quarter turn would hide that. Recorded as a warning, snap still applied.
MAX_YAW_SNAP_DEVIATION_DEG = 20.0

# Half-turn about the UP axis, applied to the scene for the glTF twin export only
# and undone straight after. WHY (witnessed, not inferred): Blender 5.2's FBX and
# glTF exporters write IDENTICAL raw coordinates for one scene (checked by
# re-reading both files), so the exporters do not disagree. The two CONSUMERS do:
# the Roblox 3D Importer reads the R15 FBX as facing -Z (what Studio shows), while
# Genvid's roblox/r15-rigged profile (spec 1.1.0) read the untouched GLB twin of
# the same rig as +Z on all three bake-off legs (2026-09-04). Which side holds the
# handedness convention is not witnessed; what is witnessed is the fix: a twin
# exported after this half-turn measures -Z and the profile passes outright
# (leg A twin, 2026-09-04). The FBX is exported first and is
# untouched by this.
GLB_TWIN_YAW_DEG = 180

LR_PAIRS = (
    ("LeftUpperArm", "RightUpperArm"), ("LeftLowerArm", "RightLowerArm"), ("LeftHand", "RightHand"),
    ("LeftUpperLeg", "RightUpperLeg"), ("LeftLowerLeg", "RightLowerLeg"), ("LeftFoot", "RightFoot"),
)


def weighted_vertex_counts(meshes, final_bones):
    """Vertices carrying a non-zero weight, per surviving R15 bone. Read after
    the fold, so it reports where the weights ACTUALLY ended up -- which is how
    a wrong fold target (the Meshy 7 "neck" chest bone landing on Head) shows
    up as a number rather than as a shrug."""
    counts = dict((n, 0) for n in final_bones)
    for me in meshes:
        by_index = dict((vg.index, vg.name) for vg in me.vertex_groups if vg.name in counts)
        for v in me.data.vertices:
            for g in v.groups:
                name = by_index.get(g.group)
                if name is not None and g.weight > 1e-6:
                    counts[name] += 1
    return counts


def symmetry(counts):
    """Worst left/right weighted-vertex balance over the keeper pairs, as
    min/max in [0, 1], with the pair that scored it.

    Witnessed 2026-09-04 (bake-off leg B, before the facing fix): LeftLowerArm
    8062 weighted vertices against RightLowerArm 734 -- skinning bleed from a
    skeleton fitted to a mesh facing the wrong way. A symmetric character's
    pairs sit near 1.0, so the minimum over the pairs is the diagnostic; no
    threshold is calibrated for it yet, so it is reported, not gated."""
    worst, worst_pair = None, None
    for left, right in LR_PAIRS:
        if left not in counts or right not in counts:
            continue
        hi = max(counts[left], counts[right])
        if hi == 0:
            continue
        frac = float(min(counts[left], counts[right])) / hi
        if worst is None or frac < worst:
            worst, worst_pair = frac, "%s/%s" % (left, right)
    return worst, worst_pair


# Roblox's skinned-mesh cap, and the post-rig decimate target under it. The
# cap is the game engine's; the target leaves the same headroom mesh prep's own
# decimate leaves (19,599 of 20,000), because a triangulating exporter can add a
# few triangles to a quad it did not have to split.
TRI_CAP = 20000
TRI_TARGET = 19600


def triangle_count(meshes):
    """Triangles the exporter will write: a quad counts as two, so a raw
    polygon count under the cap can still export over it."""
    total = 0
    for me in meshes:
        me.data.calc_loop_triangles()
        total += len(me.data.loop_triangles)
    return total


def decimate_to_cap(meshes, cap=TRI_CAP, target=TRI_TARGET):
    """Collapse-decimate the skinned meshes under `cap`, returning (tris, applied).

    Vendors re-mesh: Tripo's animate_rig came back at 101,184 triangles
    regardless of the mesh task's face_limit, and Meshy's rigging returned
    21,023 for a 19,599-triangle input (both witnessed 2026-09-04). So the cap
    has to be enforced AFTER the rig, on the artifact that actually ships.

    COLLAPSE keeps vertex groups -- the 15 R15 weight groups survive the
    decimate, which is what makes this safe to do to a skinned mesh (witnessed
    on both bake-off legs decimated to 19,404 with textures and silhouette IoU
    unchanged). Run AFTER the weight fold so the groups being preserved are the
    final R15 ones, and before the report, so unweighted_frac and the weighted-
    vertex counts describe the mesh that ships.
    """
    tris = triangle_count(meshes)
    if tris <= cap:
        return tris, False
    ratio = float(target) / float(tris)
    for me in meshes:
        mod = me.modifiers.new("R15Decimate", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = ratio
        mod.use_collapse_triangulate = True
        bpy.context.view_layer.objects.active = me
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return triangle_count(meshes), True


def mesh_span(meshes):
    """Largest bounding-box dimension of the skinned mesh data, in the space the
    armature's bones are read in (this script's standing assumption, the same one
    the root-offset shift below already makes). The denominator of
    shoulder_sep_frac: on a humanoid it is the height."""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for me in meshes:
        for v in me.data.vertices:
            for i in range(3):
                lo[i] = min(lo[i], v.co[i])
                hi[i] = max(hi[i], v.co[i])
    if lo[0] == float("inf"):
        return 0.0
    return max(hi[i] - lo[i] for i in range(3))


def facing_yaw(shoulder_axis):
    """Yaw about Z, in degrees, that turns this shoulder axis (LeftUpperArm ->
    RightUpperArm reversed, i.e. right-to-left) onto +X.

    A character facing -Y with +Z up has its own LEFT at +X (left = up x
    forward), which is the convention Meshy's meshes and its auto-rig assume and
    the one Roblox's importer wants. Tripo H3.1 meshes face +/-X instead
    (witnessed 2026-09-04, leg B), so a rig built on one walks sideways in Studio
    unless this turn is applied. Returns (snapped_deg in [0, 360), raw_deg).
    """
    import math
    raw = -math.degrees(math.atan2(shoulder_axis[1], shoulder_axis[0]))
    snapped = (round(raw / 90.0) * 90) % 360
    return snapped, raw


def turn_rig(matrix):
    """Left-multiply `matrix` onto every unparented armature and mesh object.

    Only those two types: `preview_render` leaves a camera and lights in the
    scene, and the export selects everything, so turning objects by type keeps
    the turn on the rig instead of on the lighting. A skinned mesh parented to
    the armature (what `flatten_into_armature_space` leaves behind, and what both
    importers produce) follows its parent and must not be turned twice.

    Returns the names turned; the caller checks the turn actually LANDED, because
    an object-level write on an armature that still has an action attached is
    re-driven away on the next depsgraph evaluation (`load_input`'s docstring
    carries that witness) and would leave a silently untouched twin.
    """
    turned = []
    for o in bpy.data.objects:
        if o.type in ("ARMATURE", "MESH") and o.parent is None:
            o.matrix_world = matrix @ o.matrix_world
            turned.append(o.name)
    bpy.context.view_layer.update()
    return turned


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    in_path, out_fbx = argv[0], argv[1]
    stylized = argv[2] if len(argv) > 2 else None
    warnings = []
    bpy.ops.wm.read_factory_settings(use_empty=True)
    load_input(in_path)

    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    print("imported:", arm.name, "meshes:", [m.name for m in meshes])
    # Vendors ship a stray unskinned Icosphere (bounding placeholder) — drop
    # every mesh that carries no skin weights
    for me in list(meshes):
        if len(me.vertex_groups) == 0:
            print("dropping unskinned mesh:", me.name)
            bpy.data.objects.remove(me, do_unlink=True)
            meshes.remove(me)

    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    # Disconnect every bone before any head or tail is written. Blender slaves a
    # CONNECTED bone's head to its parent's tail, so each write below -- the
    # facing turn, the fold's reparenting, the root-origin shift -- would drag
    # its neighbours by a second, order-dependent amount. Witnessed 2026-09-04
    # on the bake-off vendor FBX: Blender's FBX importer connects 5 of its 24
    # bones while the glTF import of the SAME rig connects none, and the export
    # put LeftUpperArm and RightUpperArm on one point -- the collapsed-shoulder
    # shape E10b exists to catch, arrived at after the gate had already read the
    # rig. Clearing the flag moves nothing; it only releases the slaving.
    for b in eb:
        b.use_connect = False
    # Normalize FIRST: a Tripo `spec=mixamo` skeleton spells the same bones
    # `mixamorig:Spine1` / `mixamorig:Spine2`, which match no RENAME/MERGE key
    # as shipped. Renaming a bone also renames the matching vertex group
    # (Blender syncs them), so the weight fold below still finds its groups.
    for b in list(eb):
        b.name = normalize(b.name)
    # Resolve the fold table against THIS skeleton's hierarchy before the rename
    # flattens Spine02 into UpperTorso: on Meshy 7 the bone spelled "neck" is the
    # chest (the PARENT of Spine02) and folds into UpperTorso, while a Mixamo-
    # convention neck under the spine top folds into Head. rigtables.merge_plan
    # carries the rule and the witness.
    parents = dict((b.name, b.parent.name if b.parent else None) for b in eb)
    MERGE = merge_plan(parents)
    print("merge plan (neck ->", dict(MERGE)["neck"], "):", MERGE)
    for old, new in RENAME.items():
        if old in eb:
            eb[old].name = new  # vertex groups auto-rename with the bone
        else:
            msg = "WARN: keeper bone %s missing" % old
            print(msg)
            warnings.append(msg)
    # FACING + skeleton fit, measured on the raw vendor rig before anything is
    # folded away. Both numbers land in rig.report.json (eval rows E10b and the
    # facing record); the rotation turns the rig -- armature AND mesh together --
    # so leg C (a Tripo-direct rig, which cannot be yaw-corrected before rigging
    # because Tripo rigs its own task id) faces -Y like every other character.
    import mathutils
    span = mesh_span(meshes)
    yaw_matrix = mathutils.Matrix.Identity(4)
    facing = {"shoulder_sep": None, "shoulder_sep_frac": None, "mesh_span": span,
              "facing_yaw_deg": None, "facing_yaw_raw_deg": None, "shoulder_axis": None}
    if "LeftUpperArm" in eb and "RightUpperArm" in eb:
        axis = eb["LeftUpperArm"].head - eb["RightUpperArm"].head
        sep = axis.length
        facing["shoulder_axis"] = [float(axis.x), float(axis.y), float(axis.z)]
        facing["shoulder_sep"] = float(sep)
        facing["shoulder_sep_frac"] = float(sep / span) if span > 0 else None
        frac = facing["shoulder_sep_frac"]
        if frac is None or frac < MIN_SHOULDER_SEP_FRAC:
            # Both shoulders inside the torso: the axis direction is noise, and
            # snapping a noise vector to a quarter turn would rotate the rig by a
            # confident wrong amount. Leave the rig alone and say so.
            msg = ("WARN: shoulder separation %s of mesh span %.4f is below %.2f -- the skeleton "
                   "does not fit the mesh; facing left uncorrected"
                   % ("%.4f" % sep if span else "unmeasurable", span, MIN_SHOULDER_SEP_FRAC))
            print(msg)
            warnings.append(msg)
        else:
            snapped, raw = facing_yaw(axis)
            facing["facing_yaw_deg"] = snapped
            facing["facing_yaw_raw_deg"] = raw
            deviation = abs(((raw - snapped + 180) % 360) - 180)
            if deviation > MAX_YAW_SNAP_DEVIATION_DEG:
                msg = ("WARN: shoulder axis is %.1f deg off the nearest quarter turn (%d deg) -- "
                       "a crooked skeleton, not an axis convention" % (deviation, snapped))
                print(msg)
                warnings.append(msg)
            if snapped:
                yaw_matrix = mathutils.Matrix.Rotation(__import__("math").radians(snapped), 4, "Z")
                for b in eb:
                    b.transform(yaw_matrix)  # head, tail AND roll
                print("facing: turned the rig %d deg about Z so its left is +X (faces -Y)" % snapped)
    else:
        msg = "WARN: no LeftUpperArm/RightUpperArm; facing and skeleton fit not measured"
        print(msg)
        warnings.append(msg)

    for old, _target in MERGE:
        if old in eb:
            b = eb[old]
            for child in list(b.children):
                child.parent = b.parent
            eb.remove(b)
    # Root bone must sit AT the torso, not at the origin: the importer maps it
    # to HumanoidRootPart and every child bone's rest offset rides on top of
    # the hovering root — an origin-rooted skeleton floats the visual mesh a
    # full body-height above the ground (live find, 2026-07-17).
    root = eb.new("HumanoidRootNode")  # Roblox avatar template root name — "Root" fails the R15 guideline check
    if "LowerTorso" in eb:
        lt = eb["LowerTorso"].head.copy()
        root.head = lt
        root.tail = (lt.x, lt.y, lt.z + 0.1)
        eb["LowerTorso"].parent = root
    else:
        msg = "WARN: no LowerTorso; root placed at the origin"
        print(msg)
        warnings.append(msg)
        root.head = (0, 0, 0)
        root.tail = (0, 0, 0.1)
    # The importer places HumanoidRootPart at the ARMATURE ORIGIN and hangs
    # every bone's rest offset off it. With the origin at the feet, the whole
    # visual skeleton floats a body-height above the hovering root (live
    # find, import round 3 — needed a hand-calibrated 19-stud bone drop).
    # Relocate the armature origin to the root bone: shift all bones so the
    # root head is (0,0,0), then move the object by the same amount so world
    # positions are unchanged.
    off = root.head.copy()
    for b in eb:
        b.head -= off
        b.tail -= off
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.location = arm.location + arm.matrix_world.to_3x3() @ off
    # shift the MESH VERTEX DATA by the same offset: Roblox's distance render
    # draws the raw mesh anchored at the root bone node, so feet-origined
    # vertex data floats the far-LOD visual by exactly the hip height (live
    # find, 2026-07-17 — part CFrame/Size moves never affect that draw). The
    # skinned close render is unaffected either way (bind matrices recompute
    # at export from the shifted state).
    # The same yaw the bones were turned by, applied to the mesh data in the same
    # step as the origin shift: rotate first, then translate (`off` was read after
    # the bones had already turned), so armature and mesh stay in one frame.
    for me in meshes:
        me.data.transform(mathutils.Matrix.Translation(-off) @ yaw_matrix)
    print("armature origin relocated to root bone (offset", tuple(round(c, 3) for c in off), "); mesh data shifted to match")

    # fold the removed bones' skin weights into their R15 neighbors
    for me in meshes:
        vgs = me.vertex_groups
        for old, target in MERGE:
            og = vgs.get(old)
            if og is None:
                continue
            tgt = vgs.get(target) or vgs.new(name=target)
            oi = og.index
            for v in me.data.vertices:
                for g in v.groups:
                    if g.group == oi and g.weight > 0:
                        tgt.add([v.index], g.weight, "ADD")
            vgs.remove(og)

    # Post-rig triangle cap. Every measurement below (bone list aside) is taken
    # after this, so the report describes the exported mesh rather than the one
    # the vendor handed back.
    tris_r15, decimated = decimate_to_cap(meshes)
    print("R15 triangles:", tris_r15, "(decimated)" if decimated else "(under the cap already)")
    if tris_r15 > TRI_CAP:
        msg = "WARN: %d triangles after the decimate, still over the %d cap" % (tris_r15, TRI_CAP)
        print(msg)
        warnings.append(msg)

    final = [b.name for b in arm.data.bones]
    print("final bones:", sorted(final))
    if len(final) != 16:
        msg = "WARN: expected 16 bones (15 R15 + HumanoidRootNode), got %d" % len(final)
        print(msg)
        warnings.append(msg)

    # Write the report BEFORE the preview render and the export: a render or
    # exporter crash downstream still leaves the evidence of what the skeleton
    # became, which is what the eval matrix (E7/E8/E9) reads.
    weighted_verts = weighted_vertex_counts(meshes, final)
    symmetry_min_frac, symmetry_min_pair = symmetry(weighted_verts)
    report = {
        "bones": sorted(final),
        "root_offset": [float(off.x), float(off.y), float(off.z)],
        "unweighted_frac": unweighted_fraction(meshes, final),
        "tris_r15": tris_r15,
        "tris_decimated": decimated,
        "neck_fold_target": dict(MERGE)["neck"],
        "shoulder_sep": facing["shoulder_sep"],
        "shoulder_sep_frac": facing["shoulder_sep_frac"],
        "mesh_span": facing["mesh_span"],
        "facing_yaw_deg": facing["facing_yaw_deg"],
        "facing_yaw_raw_deg": facing["facing_yaw_raw_deg"],
        "shoulder_axis": facing["shoulder_axis"],
        "weighted_verts": weighted_verts,
        "symmetry_min_frac": symmetry_min_frac,
        "symmetry_min_pair": symmetry_min_pair,
        "warnings": warnings,
    }
    report_path = Path(out_fbx).parent / "rig.report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    print("wrote", report_path)

    if stylized:
        swap_basecolor(meshes, stylized)
    preview_render(out_fbx)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(
        filepath=out_fbx,
        use_selection=True,
        add_leaf_bones=False,
        use_armature_deform_only=True,
        path_mode="COPY",
        embed_textures=True,
        bake_anim=False,
    )
    print("exported", out_fbx)
    # Export the SAME scene as glTF-binary beside the FBX. Genvid's
    # roblox/r15-rigged conformance profile (spec 1.1.0) reads gltf-binary only
    # and fails an FBX at container.format (witnessed 2026-09-04), so the rig
    # needs a GLB twin to be measurable at all; the FBX stays the artifact the
    # Roblox 3D Importer takes. Same skeleton, same weights, same textures --
    # one conversion, two containers.
    #
    # Turned a half-turn about up FIRST (GLB_TWIN_YAW_DEG): the raw coordinates
    # the two exporters write are identical, but Genvid's glTF reader measured
    # the untouched twin as +Z where the Roblox importer reads the FBX as -Z;
    # the half-turn is what makes the profile read -Z (witnessed on the turned twin).
    # Diagonal(-1, -1, 1) is that half-turn exactly -- no sin(pi) tail -- and is
    # its own inverse, so the same matrix turns the scene back afterwards and the
    # scene the FBX was exported from is restored byte-for-byte.
    half_turn = mathutils.Matrix.Diagonal((-1.0, -1.0, 1.0, 1.0))
    before = (arm.matrix_world.to_3x3() @ mathutils.Vector((1.0, 0.0, 0.0))).copy()
    turned = turn_rig(half_turn)
    after = arm.matrix_world.to_3x3() @ mathutils.Vector((1.0, 0.0, 0.0))
    landed = (after + before).length <= 1e-4
    if not landed:
        # Not a fact about the twin unless it is read back: an armature still
        # driven by an imported action has object-level writes re-driven away.
        msg = ("WARN: the glTF twin's %d-degree turn did not land (armature X axis %s -> %s); "
               "the twin faces the way the FBX does and will read as the wrong forward axis"
               % (GLB_TWIN_YAW_DEG, tuple(round(c, 4) for c in before),
                  tuple(round(c, 4) for c in after)))
        print(msg)
        warnings.append(msg)
    else:
        print("glTF twin: turned %s %d deg about up so the twin faces -Z like the FBX"
              % (turned, GLB_TWIN_YAW_DEG))
    out_glb = str(Path(out_fbx).with_suffix(".glb"))
    bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB", use_selection=True)
    print("exported", out_glb)
    turn_rig(half_turn)  # scene back in the frame the FBX was exported from
    # Re-write the report now that the twin exists, carrying the turn that was
    # READ BACK (0 when it did not land) rather than the one intended -- a reader
    # of the twin needs to know it is a half-turn off the FBX, and the report is
    # the machine-readable place to say so. The earlier write still stands as the
    # crash evidence it exists for; this only adds to it.
    report["glb_twin_yaw_deg"] = GLB_TWIN_YAW_DEG if landed else 0
    report["warnings"] = warnings
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    if len(final) != 16:
        # Non-zero exit is the contract rig.py's r15() checks; the report and
        # the FBX are both on disk either way so the failure is inspectable.
        sys.exit(1)


if __name__ == "__main__":
    main()
