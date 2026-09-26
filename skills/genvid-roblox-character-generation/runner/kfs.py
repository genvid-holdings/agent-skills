"""KeyframeSequence .rbxmx writer from poses JSON (world-space transfer output).
Rojo syncs the file into ServerStorage/Assets/Anims, where the `build_kfs` Studio
step verifies it and `publish_clip` publishes it."""
import re
from pathlib import Path
from xml.sax.saxutils import escape
import timing

PRIORITY = {"Idle": 0, "Movement": 1, "Action": 2}
ROOT_NODE = "HumanoidRootNode"  # the rig's root bone between HumanoidRootPart and LowerTorso
BRANDS = ("mixamo", "meshy", "quaternius", "tripo", "cascadeur")

def clip_name(character, clip, version=1):
    name = "%s%s_v%d" % (character, clip, version)
    low = name.lower()
    for b in BRANDS:
        if b in low:
            raise ValueError("brand name in asset title: %s" % name)
    if not re.match(r"^[A-Za-z][A-Za-z0-9]*_v\d+$", name):
        raise ValueError("bad clip name %s" % name)
    return name

def quat_to_rot(q):
    x, y, z, w = q
    return [[1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
            [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
            [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)]]

def _cframe_xml(rot, pos=(0.0, 0.0, 0.0)):
    cells = ["<X>%.5f</X><Y>%.5f</Y><Z>%.5f</Z>" % (pos[0], pos[1], pos[2])]
    for i in range(3):
        for j in range(3):
            cells.append("<R%d%d>%.6f</R%d%d>" % (i, j, rot[i][j], i, j))
    return "<CoordinateFrame name=\"CFrame\">%s</CoordinateFrame>" % "".join(cells)

def _pose_xml(name, rot, children, ref, pos=(0.0, 0.0, 0.0)):
    inner = "".join(children)
    return ("<Item class=\"Pose\" referent=\"%s\"><Properties><string name=\"Name\">%s</string>%s"
            "<float name=\"Weight\">1</float><token name=\"EasingDirection\">0</token>"
            "<token name=\"EasingStyle\">0</token></Properties>%s</Item>" % (ref, escape(name), _cframe_xml(rot, pos), inner))

def _omitted(poses):
    """The held bones (poses.py `held`: extra bones the clip does not drive) this
    sequence leaves out altogether.

    A present Pose claims its joint: the Animator evaluates tracks "in order from
    high to low priority, per joint", and "Higher priority animation will
    override lower priority ones per joint" (creator docs, enums/
    AnimationPriority; classes/AnimationTrack.Priority), so an identity Pose on a
    joint an Action clip does not animate would still pin it over an Idle that
    does. A held bone is therefore omitted unless it has to stay as a structural
    node: it carries root motion (`r`), or a descendant is driven (`p`) or
    translated (`r`). A poses doc without `held` omits nothing."""
    held = set(poses.get("held") or ())
    if not held:
        return set()
    carried = set()
    for fr in poses["frames"]:
        carried.update(fr.get("p") or {})
        carried.update(fr.get("r") or {})
    parent = poses["hier"]
    needed = set()
    for bone in carried:
        while bone and bone not in needed:
            needed.add(bone)
            bone = parent.get(bone)
    return held - needed


def write(poses, path, *, name, height_studs, loop, priority, root_scale=1.0, root_node=True, time_scale=None):
    hier = poses["hier"]
    omit = _omitted(poses)
    kids = {}
    for bone, parent in hier.items():
        if bone not in omit:
            kids.setdefault(parent if parent else "HumanoidRootPart", []).append(bone)
    n = [0]
    def ref():
        n[0] += 1; return "RBX%d" % n[0]
    def pose(bone, p, r):
        rot = quat_to_rot(p[bone]) if bone in p else [[1,0,0],[0,1,0],[0,0,1]]
        # poses.py "r": a per-bone translation in the bone's rest frame, carried
        # by the root bone(s) under HumanoidRootPart (root motion) and by any
        # bone the transfer was asked to translate (`--translate`), divided by
        # the Studio model scale: the Animator multiplies a pose
        # translation by Model:GetScale() (witnessed 2026-09-08), so studs
        # authored here land as studs in the game only after that division
        pos = tuple(v / root_scale for v in r[bone]) if bone in r else (0.0, 0.0, 0.0)
        return _pose_xml(bone, rot, [pose(c, p, r) for c in sorted(kids.get(bone, []))], ref(), pos)
    frames = []
    for fr in poses["frames"]:
        # time_scale None: the sqrt-cadence stretch for this height; a number
        # multiplies the authored times instead (1 keeps the authored cadence)
        t = timing.scale_time(fr["t"], height_studs) if time_scale is None else fr["t"] * float(time_scale)
        r = fr.get("r") or {}
        # The pose tree must mirror the rig's real bone chain for a TRANSLATION to
        # apply: on the R15-converted skinned rigs the root bone under
        # HumanoidRootPart is HumanoidRootNode (rig_r15 names it so; the R15
        # guideline expects it), and LowerTorso hangs off that. A tree that skips
        # the node still applies every rotation (matched by name) but the Animator
        # drops the root translation (witnessed 2026-09-08: four pose-tree
        # variants, only HumanoidRootPart > HumanoidRootNode > LowerTorso moved
        # the hips). The node pose is identity; root motion rides on LowerTorso.
        # A rig with no such bone (`root_node=False`) takes the translation on
        # HumanoidRootPart > LowerTorso instead (witnessed 2026-09-10).
        bones = [pose(c, fr["p"], r) for c in sorted(kids.get("HumanoidRootPart", []))]
        if root_node:
            bones = [_pose_xml(ROOT_NODE, [[1,0,0],[0,1,0],[0,0,1]], bones, ref())]
        root = _pose_xml("HumanoidRootPart", [[1,0,0],[0,1,0],[0,0,1]], bones, ref())
        frames.append("<Item class=\"Keyframe\" referent=\"%s\"><Properties><string name=\"Name\">Keyframe</string>"
                      "<float name=\"Time\">%.5f</float></Properties>%s</Item>" % (ref(), t, root))
    xml = ("<roblox version=\"4\"><Item class=\"KeyframeSequence\" referent=\"%s\"><Properties>"
           "<string name=\"Name\">%s</string><bool name=\"Loop\">%s</bool><token name=\"Priority\">%d</token>"
           "</Properties>%s</Item></roblox>" % (ref(), escape(name), "true" if loop else "false",
                                               PRIORITY[priority], "".join(frames)))
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(xml)
    return path
