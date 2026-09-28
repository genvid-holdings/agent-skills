"""Bone-name tables shared by the runner and its Blender scripts.

Single source for the Mixamo-convention -> R15 rename, the leaf-up merge
order, and the per-source name maps the pose transfer reads. Stdlib only so
`blender --python` can import it after a sys.path insert.
"""
R15_BONES = (
    "LowerTorso", "UpperTorso", "Head",
    "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
    "RightUpperLeg", "RightLowerLeg", "RightFoot",
)

# Meshy/Mixamo-convention keeper bones -> R15 names (stage_f_rig RENAME).
RENAME = {
    "Hips": "LowerTorso", "Spine02": "UpperTorso",
    "LeftUpLeg": "LeftUpperLeg", "LeftLeg": "LeftLowerLeg", "LeftFoot": "LeftFoot",
    "RightUpLeg": "RightUpperLeg", "RightLeg": "RightLowerLeg", "RightFoot": "RightFoot",
    "LeftArm": "LeftUpperArm", "LeftForeArm": "LeftLowerArm", "LeftHand": "LeftHand",
    "RightArm": "RightUpperArm", "RightForeArm": "RightLowerArm", "RightHand": "RightHand",
    "Head": "Head",
}

# Folded bones, LEAF-UP order: children reparent to the removed bone's parent.
# "neck" is the one entry whose target depends on the skeleton: use merge_plan()
# with the rig's own parent map rather than this table's default (see below).
MERGE = [
    ("head_end", "Head"), ("headfront", "Head"), ("neck", "Head"),
    ("LeftToeBase", "LeftFoot"), ("RightToeBase", "RightFoot"),
    ("LeftShoulder", "LeftUpperArm"), ("RightShoulder", "RightUpperArm"),
    ("Spine01", "UpperTorso"), ("Spine", "LowerTorso"),
    # Tripo's spec=mixamo rig hangs a weightless top-level "Root" ABOVE Hips
    # (witnessed 2026-09-04 on leg C: Mixamo names with the mixamorig: prefix,
    # metre scale, Root above Hips). Leaf-up order puts it last: by the time it
    # is removed its only child is LowerTorso (Hips, already renamed), which
    # reparents to Root's own parent -- nothing -- and then becomes the child of
    # the HumanoidRootNode the conversion adds. Left in place it is a 17th bone
    # and the R15 bone-count gate (E7) fails on a rig that is otherwise fine.
    # Carrying no weights, its vertex-group fold is a no-op; the entry is the
    # bone removal.
    ("Root", "LowerTorso"),
]

# Native Mixamo skeleton (X Bot download) read in world space (stage_h).
MIXAMO_MAP = {
    "LowerTorso": "Hips", "UpperTorso": "Spine2", "Head": "Head",
    "LeftUpperArm": "LeftArm", "LeftLowerArm": "LeftForeArm", "LeftHand": "LeftHand",
    "RightUpperArm": "RightArm", "RightLowerArm": "RightForeArm", "RightHand": "RightHand",
    "LeftUpperLeg": "LeftUpLeg", "LeftLowerLeg": "LeftLeg", "LeftFoot": "LeftFoot",
    "RightUpperLeg": "RightUpLeg", "RightLowerLeg": "RightLeg", "RightFoot": "RightFoot",
}

# Quaternius Universal Animation Library (Rigify DEF- skeleton).
UAL_MAP = {
    "LowerTorso": "DEF-hips", "UpperTorso": "DEF-spine.003", "Head": "DEF-head",
    "LeftUpperArm": "DEF-upper_arm.L", "LeftLowerArm": "DEF-forearm.L", "LeftHand": "DEF-hand.L",
    "RightUpperArm": "DEF-upper_arm.R", "RightLowerArm": "DEF-forearm.R", "RightHand": "DEF-hand.R",
    "LeftUpperLeg": "DEF-thigh.L", "LeftLowerLeg": "DEF-shin.L", "LeftFoot": "DEF-foot.L",
    "RightUpperLeg": "DEF-thigh.R", "RightLowerLeg": "DEF-shin.R", "RightFoot": "DEF-foot.R",
}

# The Meshy/Mixamo vendor convention (RENAME's own keys), inverted: R15 name ->
# the vendor's own spelling for it. `--rename`/`--donor` clips (poses.py) used
# to physically rename the CLIP's Blender armature onto R15 names before
# matching by name; a rig kept on its own skeleton may not carry R15 names to
# rename onto, so the match now runs the other way, through this table,
# exactly like MIXAMO_MAP/UAL_MAP -- no bone in either the clip or the rig is
# ever renamed.
RENAME_TARGET_MAP = {r15: vendor for vendor, r15 in RENAME.items()}

CLIP_MODES = {"names": None, "mixamo": MIXAMO_MAP, "ual": UAL_MAP, "rename": RENAME_TARGET_MAP}


def clip_bone_map(rest_names, clip_bone_names, *, mode="names", prefix=""):
    """Which clip bone drives each rest bone, as `(src, held)`.

    `rest_names` are the bones of the rig's rest dump: every bone the rig
    carries, however it names them -- a rig kept on its own skeleton has no
    fixed 15-bone target. A rest bone is read through the mode's table when it
    has one (`names`: none, matched by its own name; `mixamo`: MIXAMO_MAP
    behind the skeleton's `prefix`; `ual`: UAL_MAP; `rename`: RENAME_TARGET_MAP,
    the Meshy/Mixamo vendor spelling of an R15-shaped name), else by its own
    name (`prefix` + name tried first in `mixamo` mode). `rename` mode also
    matches a clip bone by its NORMALIZED name (`normalize()`: vendor prefix
    stripped, alias folded) -- the same first pass the retired
    `rename_to_r15` applied to the clip's own armature before matching it by
    name, now applied to the lookup instead of the bones.

    A rest bone the clip does not drive by any of these is `held`: the
    transfer leaves it at its rest pose, whether it is one of the fifteen
    classic R15 names or any other bone the rig carries. Nothing is ever
    refused here -- a clip authored for a different rig than the one asked for
    simply drives fewer bones (the caller sees this in `held`).
    """
    if mode not in CLIP_MODES:
        raise ValueError("unknown clip bone mode %r (one of %s)" % (mode, ", ".join(CLIP_MODES)))
    table = CLIP_MODES[mode]
    if mode == "rename":
        have = {}
        for c in clip_bone_names:
            have.setdefault(normalize(c), c)
    else:
        have = {c: c for c in clip_bone_names}
    src, held = {}, []
    for n in rest_names:
        candidates = []
        if table is not None and n in table:
            candidates.append(prefix + table[n])
        if mode == "mixamo":
            candidates.append(prefix + n)
        candidates.append(n)
        original = next((have[c] for c in candidates if c in have), None)
        if original is None:
            held.append(n)
        else:
            src[n] = original
    return src, held


# Vendor spellings folded onto the RENAME/MERGE keys (Tripo spec=mixamo, raw Mixamo).
PREFIXES = ("mixamorig:", "mixamorig1:", "mixamorig_", "Armature|")
ALIASES = {
    "Spine1": "Spine01", "Spine2": "Spine02", "Neck": "neck", "HeadTop_End": "head_end",
    "Head_End": "head_end",
    # Meshy 7: a weightless bone between Spine and Head, the same leaf the Mixamo
    # convention spells HeadTop_End (witnessed 2026-09-04 on both bake-off legs).
    "Head1": "head_end",
}

def strip_vendor_prefix(name):
    """Strip a vendor prefix only -- no alias fold. What the rig prep calls
    (blender/rig_prep.py): with no RENAME/MERGE downstream of it any more, an
    alias fold has no purpose there, and would rename an own-skeleton rig's
    own bone if it happened to be spelled like an ALIASES key -- e.g. a bone
    literally named `Neck` becoming `neck`. `normalize()` below still folds
    aliases for callers that resolve names against RENAME/MERGE."""
    for p in PREFIXES:
        if name.startswith(p):
            return name[len(p):]
    return name


def normalize(name):
    """Strip a vendor prefix and fold aliases so RENAME/MERGE keys match. Used
    by callers that read names against those tables -- the clip-transfer pose
    reader (blender/poses.py) -- not by the rig prep, which uses
    strip_vendor_prefix() instead (see its docstring)."""
    stripped = strip_vendor_prefix(name)
    return ALIASES.get(stripped, stripped)


def ancestors(parents, name):
    """Normalized ancestor names of `name`, closest first. `parents` maps a
    normalized bone name to its normalized parent (or None). Cycle-safe: a
    malformed hierarchy stops rather than hanging the conversion."""
    seen, out, cur = {name}, [], parents.get(name)
    while cur and cur not in seen:
        seen.add(cur)
        out.append(cur)
        cur = parents.get(cur)
    return out


def merge_plan(parents):
    """MERGE resolved against THIS rig's hierarchy.

    Only "neck" is hierarchy-dependent, and getting it wrong is a witnessed
    defect rather than a nicety:

      - Meshy 7 (fal-ai/meshy/rigging, witnessed 2026-09-04 on both bake-off
        legs) names the CHEST bone "neck": it is the PARENT of Spine02 and its
        weights sit at Spine02's height. Folding it into Head hangs the whole
        chest off the head bone.
      - A Mixamo-convention rig (Tripo spec=mixamo, raw Mixamo) has a real neck
        UNDER the spine top, whose weights belong to Head.

    So: an ANCESTOR of Spine02 folds into UpperTorso (Spine02's R15 name), and
    anything else -- a descendant, or a rig with no Spine02 at all -- folds into
    Head, which is the table's default and what every rig before Meshy 7 needed.
    `parents` maps normalized bone name -> normalized parent name (or None).
    """
    neck_target = "UpperTorso" if "neck" in ancestors(parents, "Spine02") else "Head"
    return [(old, neck_target if old == "neck" else target) for old, target in MERGE]
