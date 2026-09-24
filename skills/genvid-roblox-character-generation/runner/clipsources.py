"""Per-clip candidate catalog (spec §2.3 fallback order) and local-file lookup
for the archive clip sources `clips.py` transfers.

Three kinds of source:

- `rig-bundled`: a library clip that arrives WITH the rig itself (`rig ingest
  model --clip <label>=<file>`), on the rig's own skeleton, so it transfers with
  `--rename`. Its `ref` is the clip's label, and `clips.py` resolves it only
  through `stages.rig.clip_files[<label>]`; `locate()` does not resolve it. The
  rig's own record holds its spend.
- `mixamo-archive` / `quaternius`: resolved locally by `locate()` below.
- a generated motion: not a `CATALOG` candidate. The caller generates it with a
  text-to-motion model of its own choosing (`clips emit motion` /
  `clips ingest motion`), and `clips transfer --source generated` reads its file
  and skeleton convention from the ingest record. `DESCRIPTIONS` holds the
  motion each clip asks for.

This module never talks to a provider.

Archive layout under `archive_root` -- the animation archive is the title's own
tree, named by `ANIM_LIBRARY_ROOT` (required, no default: see `archive_root()`) or a
CLI `--archive-root`:

    creature-packs/creature-pack/<clip>.fbx   (mutant pack, X Bot retarget)
    creature-packs/npc-pack/<clip>.fbx        (a second, mostly-overlapping copy)
    Animation Library[Standard]/Godot/AnimationLibrary_Godot_Standard.glb

`quaternius` candidates name an ACTION baked inside that one Godot file (e.g.
"Idle_Loop"), not a filename -- `clips.py` passes it to `blender/poses.py` as
`--action=<ref>`. The file choice is witnessed, not assumed: parsing the
glb's JSON chunk directly (12-byte header, then the "JSON" chunk) shows its 55
`nodes[].name` entries include `DEF-hips` / `DEF-foot.L` (the Rigify `DEF-`
skeleton `poses.py --ual` expects, per `rigtables.UAL_MAP`) and its 46
`animations[].name` entries include `Idle_Loop`, `Hit_Chest` and `Death01`
verbatim -- exactly the strings `bpy.data.actions[action_name]` needs. The
pack's `Unity/AnimationLibrary_Unity_Standard.fbx` also carries `DEF-` bones
(`Animation Library[Standard]/Unreal Engine/AL_Standard.fbx` does not -- it is
retargeted to the UE4 Mannequin's `spine_01`-style naming, no `DEF-` anywhere),
but its action names are FBX takes spelled `Rig|Idle_Loop`; Blender's FBX
importer does not strip that prefix, so `--action=Idle_Loop` would raise a
`KeyError` in `bpy.data.actions[...]`. The glTF file's names need no such
stripping, so it is the one this module points at.

`Stomping.fbx` (the Attack fallback, an X Bot download, "X Bot rule already
honored in July" per the plan) never joined the archive proper and lives
directly under `downloads` (default `~/Downloads`, override with
`ANIM_LIBRARY_DOWNLOADS` or a CLI `--downloads`) -- `locate()` checks there too
when the mutant-pack lookup misses.
"""
import os
from pathlib import Path

ARCHIVE_SUBDIRS = ("creature-packs/creature-pack", "creature-packs/npc-pack")
QUATERNIUS_FILE = "Animation Library[Standard]/Godot/AnimationLibrary_Godot_Standard.glb"

ARCHIVE_ROOT_ENV = "ANIM_LIBRARY_ROOT"
# ~/Downloads stays a default: it is the operating system's own download location,
# not one title's checkout, and `locate()` only ever READS from it.
DEFAULT_DOWNLOADS = Path(os.environ.get("ANIM_LIBRARY_DOWNLOADS", str(Path.home() / "Downloads")))


def archive_root():
    """The animation archive tree, named by $ANIM_LIBRARY_ROOT.

    REQUIRED, with no default. The default this replaced pointed at one checkout
    under the author's home directory: on any other machine every lookup under it
    missed, and a miss here reads exactly like a clip with no archive fallback, which
    would push a caller onto a paid vendor leg it did not need. A per-title skill
    exports the variable; a direct caller passes `--archive-root`."""
    root = os.environ.get(ARCHIVE_ROOT_ENV)
    if not root:
        raise RuntimeError(
            "%s is not set and has no default: it must name the animation archive tree "
            "(the creature packs and the animation library this module resolves candidates "
            "in), because a wrong root turns every lookup into a silent miss that reads "
            "exactly like a clip with no archive fallback. Export it (a per-title skill "
            "does this for you) or pass --archive-root." % ARCHIVE_ROOT_ENV)
    return Path(root).expanduser()


def _resolve_archive_root(value):
    """An explicit root, else the required environment variable. Separate from
    `archive_root()` only because `locate`'s own parameter shadows that name."""
    return Path(value).expanduser() if value else archive_root()

# Fallback order per logical clip. Every clip carries at least one mixamo-archive
# or quaternius candidate (the free, always-available fallback).
CATALOG = {
    "Walk": [
        {"source": "rig-bundled", "ref": "Walk", "mode": "--rename", "loop": True, "priority": "Movement"},
        {"source": "mixamo-archive", "ref": "mutant walking.fbx", "mode": "--mixamo", "loop": True, "priority": "Movement"},
    ],
    "Idle": [
        {"source": "quaternius", "ref": "Idle_Loop", "mode": "--ual", "loop": True, "priority": "Idle"},
        {"source": "mixamo-archive", "ref": "mutant breathing idle.fbx", "mode": "--mixamo", "loop": True, "priority": "Idle"},
    ],
    "Stun": [
        {"source": "quaternius", "ref": "Hit_Chest", "mode": "--ual", "loop": False, "priority": "Action"},
        {"source": "rig-bundled", "ref": "Stun", "mode": "--rename", "loop": False, "priority": "Action"},
    ],
    "Attack": [
        {"source": "rig-bundled", "ref": "Attack", "mode": "--rename", "loop": False, "priority": "Action"},
        {"source": "mixamo-archive", "ref": "Stomping.fbx", "mode": "--mixamo", "loop": False, "priority": "Action"},
    ],
    "Death": [
        # The bundled entry needs a Death clip delivered with the rig; a rig
        # without one (an adopted rig, or a bare GLB) takes the archive fallback.
        {"source": "rig-bundled", "ref": "Death", "mode": "--rename", "loop": False, "priority": "Action"},
        {"source": "mixamo-archive", "ref": "mutant dying.fbx", "mode": "--mixamo", "loop": False, "priority": "Action"},
        {"source": "quaternius", "ref": "Death01", "mode": "--ual", "loop": False, "priority": "Action"},
    ],
    "Slam": [
        {"source": "rig-bundled", "ref": "Slam", "mode": "--rename", "loop": False, "priority": "Action"},
        {"source": "mixamo-archive", "ref": "mutant jump attack.fbx", "mode": "--mixamo", "loop": False, "priority": "Action"},
    ],
}

# The motion each clip asks a text-to-motion model for (`clips emit motion`'s
# prompt). Model-type language only: the caller picks the model.
DESCRIPTIONS = {
    "Walk": "a looping walk cycle in place: the root stays put while the feet plant and lift in rhythm",
    "Idle": "a looping idle standing in place: slow breathing and a slight shift of weight",
    "Stun": "a short hit reaction: the body recoils from a blow to the chest, then recovers its stance",
    "Attack": "a single heavy stomp: one foot lifts high and drives down into the ground",
    "Death": "a death: the body staggers, collapses to the ground and stays down",
    "Slam": "a giant character winds up, then slams both fists into the ground",
}


def locate(candidate, archive_root=None, downloads=DEFAULT_DOWNLOADS):
    """Resolve a `mixamo-archive` or `quaternius` candidate to a file on disk,
    or None when it is not there.

    `rig-bundled` is not a local source (`clips.py` reads it from the rig
    stage's own output directory), so it raises here rather than returning
    None: a caller that mis-routes one gets a loud error instead of a silent
    "not found".
    """
    source = candidate["source"]
    archive_root = _resolve_archive_root(archive_root)
    if source == "quaternius":
        p = archive_root / QUATERNIUS_FILE
        return p if p.is_file() else None
    if source != "mixamo-archive":
        raise ValueError(
            "locate() only resolves mixamo-archive/quaternius candidates locally, got %r "
            "(rig-bundled arrives with the rig)" % (source,))
    ref = candidate["ref"]
    for sub in ARCHIVE_SUBDIRS:
        p = archive_root / sub / ref
        if p.is_file():
            return p
    p = Path(downloads) / ref
    return p if p.is_file() else None
