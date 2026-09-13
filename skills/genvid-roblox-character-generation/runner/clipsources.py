"""Per-clip candidate catalog (spec §2.3 fallback order) and local-file lookup
for the archive clip sources `clips.py` transfers.

Three kinds of source appear in `CATALOG`:

- `meshy-library`: arrives WITH the rig itself (R6 `rig gen --clips`) as
  `<out_dir>/clips/<ref>.glb`, on the shipped rig's own Meshy-convention
  skeleton -- there is no donor rig, so `--donor` mode is simply `--rename` on
  that file. `locate()` does not resolve this source; `clips.py` reads it
  straight from the rig stage's output directory (or from `stages.clips.fetched`
  after an orchestrator-run `clips.fetch()` for an id not in the original rig
  call). Meshy animation calls themselves are an orchestrator step everywhere
  in this module and in `clips.py` -- this module never talks to a vendor.
- `mixamo-archive` / `quaternius`: resolved locally by `locate()` below.
- `meshy-text-to-motion` (Slam only): the plan's own fallback order lists a
  middle rung, "meshy text-to-motion (orchestrator only, <=3 tries)", between
  the Meshy library clip and the archive fallback. It does not fit this
  module's typed candidate shape (`ref` is "an action id or filename" for
  every other candidate; here it would have to be a text prompt, and no
  `vendors/meshy.py` endpoint or fal model id exists for it). It is kept in
  `CATALOG` so the fallback chain still documents it, with `mode: None` --
  `locate()` and `clips.transfer()` both refuse it with an error explaining
  that the orchestrator must resolve it by hand (submit the Meshy text-to-
  motion job, download the result, then call `clips.transfer()` again with a
  `mixamo-archive`-shaped candidate pointing at the downloaded file) rather
  than silently skipping it or mis-typing it as a resolvable local source.

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

# spec §2.3 fallback order per logical clip, Meshy-first where a Meshy library
# animation id exists. Every clip carries at least one mixamo-archive or
# quaternius candidate (the free, always-available fallback); see the Slam
# entry's note above for the one candidate this module cannot drive itself.
CATALOG = {
    "Walk": [
        {"source": "meshy-library", "ref": 112, "mode": "--donor", "loop": True, "priority": "Movement"},
        {"source": "mixamo-archive", "ref": "mutant walking.fbx", "mode": "--mixamo", "loop": True, "priority": "Movement"},
    ],
    "Idle": [
        {"source": "quaternius", "ref": "Idle_Loop", "mode": "--ual", "loop": True, "priority": "Idle"},
        {"source": "mixamo-archive", "ref": "mutant breathing idle.fbx", "mode": "--mixamo", "loop": True, "priority": "Idle"},
    ],
    "Stun": [
        {"source": "quaternius", "ref": "Hit_Chest", "mode": "--ual", "loop": False, "priority": "Action"},
        {"source": "meshy-library", "ref": 171, "mode": "--donor", "loop": False, "priority": "Action"},
    ],
    "Attack": [
        {"source": "meshy-library", "ref": 26, "mode": "--donor", "loop": False, "priority": "Action"},
        {"source": "mixamo-archive", "ref": "Stomping.fbx", "mode": "--mixamo", "loop": False, "priority": "Action"},
    ],
    "Death": [
        # The library entry needs the rig's own vendor rig task (the clip arrives
        # retargeted onto that skeleton). A rig with no task id on record --
        # an old-pipeline rig, or anything handed over as a bare GLB -- takes
        # the archive fall below at zero vendor cost; that is what shipped for
        # two adopted rigs on 2026-09-10 (<Name>Death_v1 apiece).
        {"source": "meshy-library", "ref": 181, "mode": "--donor", "loop": False, "priority": "Action"},
        {"source": "mixamo-archive", "ref": "mutant dying.fbx", "mode": "--mixamo", "loop": False, "priority": "Action"},
        {"source": "quaternius", "ref": "Death01", "mode": "--ual", "loop": False, "priority": "Action"},
    ],
    "Slam": [
        {"source": "meshy-library", "ref": 127, "mode": "--donor", "loop": False, "priority": "Action"},
        # Orchestrator-only leg; see module docstring. Not locate()-able / transfer()-able.
        {"source": "meshy-text-to-motion",
         "ref": "giant character winds up then slams both fists into the ground",
         "mode": None, "loop": False, "priority": "Action"},
        {"source": "mixamo-archive", "ref": "mutant jump attack.fbx", "mode": "--mixamo", "loop": False, "priority": "Action"},
    ],
}


def locate(candidate, archive_root=None, downloads=DEFAULT_DOWNLOADS):
    """Resolve a `mixamo-archive` or `quaternius` candidate to a file on disk,
    or None when it is not there.

    `meshy-library` is not a local source (`clips.py` reads it from the rig
    stage's own output directory) and `meshy-text-to-motion` is the
    orchestrator-only leg documented on `CATALOG["Slam"]` -- both raise here
    rather than returning None, so a caller that mis-routes one gets a loud
    error instead of a silent "not found".
    """
    source = candidate["source"]
    archive_root = _resolve_archive_root(archive_root)
    if source == "quaternius":
        p = archive_root / QUATERNIUS_FILE
        return p if p.is_file() else None
    if source != "mixamo-archive":
        raise ValueError(
            "locate() only resolves mixamo-archive/quaternius candidates locally, got %r "
            "(meshy-library arrives with the rig; meshy-text-to-motion is orchestrator-only)" % (source,))
    ref = candidate["ref"]
    for sub in ARCHIVE_SUBDIRS:
        p = archive_root / sub / ref
        if p.is_file():
            return p
    p = Path(downloads) / ref
    return p if p.is_file() else None
