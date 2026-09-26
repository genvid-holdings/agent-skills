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

CLIP_MODES = {"names": None, "mixamo": MIXAMO_MAP, "ual": UAL_MAP}


def clip_bone_map(rest_names, clip_bone_names, *, mode="names", prefix=""):
    """Which clip bone drives each rest bone, as `(src, held)`.

    `rest_names` are the bones of the rig's rest dump: the fifteen R15 bones,
    plus any extra bones the rig carries (wings, a jaw, cloth). An R15 bone is
    read through the mode's table (`names`: its own name; `mixamo`: MIXAMO_MAP
    behind the skeleton's `prefix`; `ual`: UAL_MAP), and a clip that lacks one
    is refused. An extra bone is read by its own name (`prefix` + name first in
    `mixamo` mode) when the clip has it; otherwise it is `held`: the transfer
    leaves it at its rest pose, so one clip library serves rigs with and
    without the extra bones.
    """
    if mode not in CLIP_MODES:
        raise ValueError("unknown clip bone mode %r (one of %s)" % (mode, ", ".join(CLIP_MODES)))
    table, have = CLIP_MODES[mode], set(clip_bone_names)
    src, held, missing = {}, [], []
    for n in rest_names:
        if n in R15_BONES:
            name = prefix + table[n] if table else n
            if name in have:
                src[n] = name
            else:
                missing.append(name)
            continue
        name = next((c for c in ((prefix + n, n) if mode == "mixamo" else (n,)) if c in have), None)
        if name is None:
            held.append(n)
        else:
            src[n] = name
    if missing:
        raise ValueError("clip lacks bones: %s" % missing)
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

def normalize(name):
    """Strip a vendor prefix and fold aliases so RENAME/MERGE keys match."""
    for p in PREFIXES:
        if name.startswith(p):
            name = name[len(p):]
            break
    return ALIASES.get(name, name)


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
