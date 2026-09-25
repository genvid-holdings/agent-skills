"""Render the Luau step templates and ingest their RUNNER_RESULT JSON.

Orchestrator protocol per Studio step:

    runner studio emit <step> --manifest m            # writes <out>/studio/<step>.luau
    <execute it in Studio; Edit mode, except the Play steps below>
    <save the RUNNER_RESULT line the step returns into <out>/studio/<step>.result.json>
    runner studio ingest <step> --manifest m <file>

The Play steps are `settle` and `bench_clip` (both in the Server datamodel),
`probe_walk`, and `treadmill`/`treadmill_scaled`. Each clones the parked
template into a running world and measures it over time: a Humanoid standing,
a MoveTo walk, or a published clip's track playing. Every other step, including
`probe_feet`, runs in Edit.

Every step both prints and returns that line, since `execute_luau` hands back a
script's return value and not its console output. The result file may hold
either the bare JSON object or the line verbatim (`RUNNER_RESULT {...}`);
`ingest` accepts both.

RUN ORDER. Which template a step reads sets the order the steps run in.
`scale`, `dump_rest`, `groundfit`, `wire` and `capture_ids` read the imported
template in `workspace`, through MODEL_PATH (default
`workspace:FindFirstChild("<template>", true)`, set in emit()). `park` MOVES it
into the park folder, and every later step (`settle`, `sethip`, `probe_feet`,
`probe_walk`, `treadmill`, `bench_clip`, `build_kfs`, `publish_clip`) reads it
from PARK_FOLDER, as does `inspect_template`, which reads a template already
parked there. So `wire` and `park` run right after `groundfit`, before the
settle loop and before any clip is built:

    scale -> dump_rest -> groundfit -> wire -> capture_ids -> park
      -> settle -> sethip -> settle -> probe_feet (close, far) -> probe_walk -> clip route

`capture_ids` runs before `park` with the default MODEL_PATH, or after it with
`--param MODEL_PATH=<park folder expression>["<template>"]`.

The two eval probes are steps here too, and land in `<out>/eval.json` where
eval_cmd's E13/E14/E24 rows read them -- never in the manifest, since they measure
the parked template rather than produce a stage artifact. `probe_feet` measures one
LOD per run: LOD is a render parameter (default close), so the far run is emitted
with `--param LOD=far`, and its ingest requires the LOD to be named rather than
assumed:

    runner studio emit probe_feet --manifest m --param LOD=far
    runner studio ingest probe_feet --manifest m --lod far <file>

`probe_feet` runs in EDIT, not Play: it needs EditableMesh, which in Play fails
with "EditableMesh is not accessible. Go to the Security Tab in Experience
Settings to enable this API" until the experience's Mesh & Image API setting is
turned on (witnessed 2026-09-04). That setting is the operator's, not this runner's.

GROUND-FIT SETTLE LOOP. A Humanoid standing still hovers: its
HumanoidRootPart bottom sits at HipHeight + e, with e constant per rig
(0.45 / 0.89 / 1.03 studs on the three bake-off legs). So groundfit's own
`hipHeight` is the sole offset, not the hip, and the correction is
hip = soleOffset - e. It takes FIVE steps, not four, because the last one is
the loop's exit test and an exit test has to be a measurement. `groundfit`
reads the template in workspace and the rest read it from the park folder, so
`wire` and `park` run between them (RUN ORDER, above):

    runner studio emit groundfit ... ; ingest groundfit ...   # EDIT: soleOffset
    runner studio emit wire ...      ; ingest wire ...        # EDIT: wires the rig
    runner studio emit park ...      ; ingest park ...        # EDIT: moves it into the park folder
    runner studio emit settle ...    ; ingest settle ...      # PLAY: measures e
    runner studio emit sethip ...    ; ingest sethip ...      # EDIT: writes the fix
    runner studio emit settle ...    ; ingest settle ...      # PLAY: verifies it
    runner studio emit probe_feet ...; ingest probe_feet --lod close ...    # EDIT: close LOD
    runner studio emit probe_feet --param LOD=far ...; ingest probe_feet --lod far ...   # EDIT: far LOD

`sethip`'s HIP comes from `stages.groundfit.corrected_hip`, which the `settle`
ingest computes. `probe_feet`'s SETTLED_BOTTOM comes from the SECOND settle --
the one that ran with the corrected hip already on the template -- and from
nowhere else. Computing it as `corrected_hip + e` instead is the sole offset
back again ((S - e) + e = S), which poses the rig at exactly the height where
its rest-pose lowest vertex touches the plane: E13's gap would then be 0 by
construction and could never report a bad ground fit. The residuals the bake-off
converged on (+0.006 / -0.0003 / +0.003 studs) are that second measurement.

Until it exists, `settled_bottom()` is None, the probe falls back to the hip and
says so, and E13 reports PEND rather than scoring a fallback (measuring at the
hip reads -e, which passes the +-0.5 gate on a rig nothing verified).
"""
import json
import re
from pathlib import Path
import eval_cmd
import groundfit
import manifest
import metrics

LUAU = Path(__file__).parent / "luau"
# Directories searched for `<step>.luau`, in order. `register_steps` prepends a
# caller's own directory, so a downstream skill can add steps -- or override one --
# without editing this package; the pack's own templates stay last.
TEMPLATE_DIRS = [LUAU]
# The steps the CLI accepts (its `choices`), not the order they run in: see RUN
# ORDER in the module docstring.
STEPS = ["inspect_template", "scale", "dump_rest", "groundfit", "settle", "sethip", "wire", "park",
         "capture_ids", "treadmill", "treadmill_scaled", "zoo_capture", "probe_feet", "probe_walk",
         "build_kfs", "publish_clip", "applymesh", "adopt_inspect", "bench_clip"]
STAGE_OF = {"inspect_template": "rest", "scale": "rest", "dump_rest": "rest", "groundfit": "groundfit",
            # settle and sethip are the two halves of the ground-fit hover
            # correction, so they land on the groundfit stage beside it.
            "settle": "groundfit", "sethip": "groundfit", "wire": "wire", "park": "wire",
            "capture_ids": "wire", "treadmill": "clips", "treadmill_scaled": "clips", "zoo_capture": "wire",
            "probe_feet": "groundfit", "probe_walk": "wire",
            # build_kfs / publish_clip are the in-Studio half of the clips stage:
            # the KeyframeSequence `clips build` wrote and Rojo synced is verified
            # read-only, then published with AssetService:CreateAssetAsync.
            "build_kfs": "clips", "publish_clip": "clips",
            # applymesh is the R15 surface pass: it swaps the MeshPart on an
            # ALREADY-parked, already-recorded template, so it lands on "rig" (where the
            # surface pass's other artifacts -- rig.py's surface_* keys -- already live)
            # rather than opening a new stage.
            "applymesh": "rig",
            # adopt_inspect fills the wire stage of an ADOPTED manifest (adopt.py)
            # from the parked template itself; no scale/wire steps ever ran on that chain.
            "adopt_inspect": "wire",
            # bench_clip plays a PUBLISHED clip on a Play clone and reports hip drop / slide / head-over-sole; the
            # verdict numbers land on the clip item, the timeline in <out_dir>/clips/<Clip>.bench.json
            "bench_clip": "clips"}
RESULT_PREFIX = "RUNNER_RESULT "
LODS = ("close", "far")


# Steps that share another step's Luau template.
TEMPLATE_OF = {"treadmill_scaled": "treadmill"}


# Template params with a safe default when a caller renders without emit().
# SETTLED_BOTTOM empty means "no settle has run": probe_feet's own tonumber()
# reads that as nil and falls back to the hip, saying so in its result.
#
# PARK_FOLDER is the Luau expression for the folder a wired template is parked
# under and every later step reads it back from. The default is NEUTRAL: a game
# that parks its characters somewhere else sets `m["studio"]["park_folder"]` on
# its manifest (emit reads it) or registers its own default through
# `register_steps`. HIP_ATTR is the attribute name `groundfit`/`sethip` write the
# ground-fit hip to and `wire`/`settle`/`probe_*`/`bench_clip` read back.
RENDER_DEFAULTS = {"SPEED": 1, "SETTLED_BOTTOM": "", "MAX_WAIT": 25, "BENCH_X": 0, "BENCH_Y": 300, "BENCH_Z": 0,
                    "ANIM_ID": "",
                    "PARK_FOLDER": 'game:GetService("ServerStorage").Assets.Characters',
                    "HIP_ATTR": "HipHeightStuds", "SOLE_ATTR": "SoleOffsetStuds",
                    # publish_clip's CreateAssetAsync table (empty publishes as the Studio
                    # user, the unchanged default) and the matching RUNNER_RESULT echo of
                    # what it actually ran with; emit() fills all three in for a group
                    # creator. The echo is what ingest() records the creator from -- never
                    # the manifest's current creator_group_id, which a later publish on a
                    # different clip can have already overwritten by ingest time.
                    "CREATOR_FIELDS": "", "CREATOR_ID_EXPR": "nil", "CREATOR_TYPE_EXPR": '"User"'}

# Ingest handlers contributed by `register_steps`, consulted before any of
# ingest()'s own step branches.
INGEST_HANDLERS = {}

_SERVICE_RE = re.compile(r'^game:GetService\(\s*["\']([A-Za-z][A-Za-z0-9_]*)["\']\s*\)')
_SEGMENT_RE = re.compile(r'\.([A-Za-z_][A-Za-z0-9_]*)|\[\s*["\']([^"\']+)["\']\s*\]')


def park_path_segments(expr):
    """PARK_FOLDER's expression as the list of names leading to it, service first.

    `park` is the one step that has to CREATE the folder when it is missing, and
    an expression cannot be walked -- indexing a Roblox Instance with an absent
    child name raises rather than returning nil, so a pcall would say "missing"
    without saying what to build. This reads the path back out of the expression
    instead, and RAISES on anything it cannot read rather than guessing: emitting
    a `park` step that silently parks somewhere other than where every later step
    looks is the one failure this whole parameter exists to prevent.
    """
    s = str(expr).strip()
    m = _SERVICE_RE.match(s)
    if m:
        segments, rest = [m.group(1)], s[m.end():]
    elif s.startswith("game."):
        segments, rest = [], s[len("game"):]
    else:
        raise ValueError("park_path_segments: PARK_FOLDER must start with game:GetService(\"...\") "
                         "or game.<Service> to be walkable by the park step (got %r)" % (expr,))
    pos = 0
    while pos < len(rest):
        seg = _SEGMENT_RE.match(rest, pos)
        if not seg:
            raise ValueError("park_path_segments: cannot read a folder name out of %r at %r"
                             % (expr, rest[pos:]))
        segments.append(seg.group(1) or seg.group(2))
        pos = seg.end()
    if len(segments) < 2:
        raise ValueError("park_path_segments: %r names a service with no folder under it" % (expr,))
    return segments


def _luau_list(names):
    return "{" + ", ".join('"%s"' % n for n in names) + "}"


def register_steps(template_dir, stage_of=None, render_defaults=None, ingest_handlers=None):
    """Let a downstream skill add Studio steps without editing this package.

    `template_dir` is searched for `<step>.luau` BEFORE the pack's own directory.
    `stage_of` maps each new step to the manifest stage its ingest lands on and is
    what puts the step into STEPS (the CLI's `choices`). `render_defaults` merge
    into RENDER_DEFAULTS -- a manifest's own `studio.park_folder` still wins over
    them, since that is the per-character override. `ingest_handlers` maps a step
    to `handler(m, result, out_dir)`, called by `ingest` INSTEAD of its own
    branches; register one for every step whose result the pack does not know how
    to record, or the generic branch will write it to `stages[stage].result`.
    """
    d = Path(template_dir)
    if not d.is_dir():
        raise ValueError("register_steps: %s is not a directory" % d)
    if d not in TEMPLATE_DIRS:
        TEMPLATE_DIRS.insert(0, d)
    for step, stage in (stage_of or {}).items():
        STAGE_OF[step] = stage
        if step not in STEPS:
            STEPS.append(step)
    RENDER_DEFAULTS.update(render_defaults or {})
    for step, handler in (ingest_handlers or {}).items():
        INGEST_HANDLERS[step] = handler
        if step not in STEPS:
            STEPS.append(step)
    return tuple(STEPS)


def template_path(step):
    name = TEMPLATE_OF.get(step, step) + ".luau"
    for d in TEMPLATE_DIRS:
        p = Path(d) / name
        if p.is_file():
            return p
    raise FileNotFoundError("no Luau template %s in %s" % (name, [str(d) for d in TEMPLATE_DIRS]))


def render(step, **params):
    src = template_path(step).read_text()
    for k, v in RENDER_DEFAULTS.items():
        params.setdefault(k, v)
    if "{{PARK_PATH}}" in src and "PARK_PATH" not in params:
        params["PARK_PATH"] = _luau_list(park_path_segments(params["PARK_FOLDER"]))
    for k, v in params.items():
        src = src.replace("{{%s}}" % k, str(v))
    return src


# How close a settle's input hip must be to the hip `sethip` wrote for that
# settle to count as a verification of it. The hover constant it would otherwise
# be confused with is 0.45 studs at its smallest across the bake-off legs, and
# the residuals at convergence are ~0.006, so 0.01 separates the two cleanly.
HIP_MATCH_TOL = 0.01


def settled_bottom(m):
    """The MEASURED HRP-bottom height this rig settles to with its corrected hip
    on it, or None until a settle has measured it AT that hip.

    Never computed. `corrected_hip + hover_excess` is the sole offset again --
    (S - e) + e = S -- so posing probe_feet there stands the rig at exactly the
    height where its rest-pose lowest vertex meets the plane, and E13's gap is 0
    whatever the ground fit did. The exit test is the second standing settle in
    Play; this reads that number back and nothing else.

    A settle measured against a hip that has since been rewritten is stale, so
    the verification is kept with the hip it was measured at and discarded when
    `sethip` moves it.
    """
    st = m["stages"].get("groundfit") or {}
    verified = st.get("verified")
    applied = (st.get("hip_applied") or {}).get("hip")
    if not isinstance(verified, dict) or applied is None:
        return None
    if abs(float(verified["hip"]) - float(applied)) > HIP_MATCH_TOL:
        return None
    # Rounded: this number is pasted into a Luau template, and a float32-noise
    # tail there is unreadable, not more accurate.
    return round(float(verified["bottom"]), 6)


def park_folder(m):
    """This manifest's park folder, or None to take RENDER_DEFAULTS'."""
    return (m.get("studio") or {}).get("park_folder")


def set_park_folder(m, folder):
    """Pin this manifest's park folder. Validated here rather than at the first
    `park`: an unwalkable expression that only fails at emit time has already
    been recorded on a saved manifest by then."""
    park_path_segments(folder)
    m.setdefault("studio", {})["park_folder"] = folder
    return m


UNVERIFIED_OK_RETIRED = ("publish_clip no longer takes UNVERIFIED_OK: every clip is published only once `studio "
                         "ingest build_kfs` has verified it. A title's own clip key is declared (`clips declare`), "
                         "transferred and built as a manifest item like any other clip")


def require_verified(m, clip, clip_name):
    """Refuse to emit `publish_clip` until `studio ingest build_kfs` has
    verified the title being published. Checked in emit() so every route is
    gated: `clips publish-clip`, `studio emit publish_clip --param CLIP=...
    --param CLIP_NAME=...`, and a caller's own studio.emit.

    A CLIP that is not on stages.clips.items has no build record to verify, so
    it is refused, with no bypass: a title's own clips (`clips declare`) are
    manifest items, which is what makes them verifiable."""
    item = (((m.get("stages") or {}).get("clips") or {}).get("items") or {}).get(clip)
    if item is None:
        raise ValueError(
            "publish_clip %s: CLIP %r is not on stages.clips.items, so no `clips build` record exists to verify "
            "it against. Transfer and build it as a manifest item (`clips declare` for a title's own key, "
            "`clips transfer`/`clips build`, then build-kfs + ingest + `clips publish-clip`)" % (clip_name, clip))
    built = item.get("kfs_name")
    verified = (item.get("kfs_verified") or {}).get("name")
    if not built:
        raise ValueError("publish_clip %s: clip %s has no `clips build` record; run `clips build --clip %s`, the Rojo "
                         "sync, `clips build-kfs` and `studio ingest build_kfs`, then `clips publish-clip`"
                         % (clip_name, clip, clip))
    if clip_name != built:
        raise ValueError("publish_clip %s: `clips build` last wrote %s for clip %s; publish that title with "
                         "`clips publish-clip --clip %s`" % (clip_name, built, clip, clip))
    if verified != built:
        raise ValueError("publish_clip %s: not verified in Studio%s; run `clips build-kfs --clip %s`, execute the "
                         "step, then `studio ingest build_kfs --clip %s <result>`, then `clips publish-clip`"
                         % (built, " (the last verify read %s)" % verified if verified else "", clip, clip))


def validate_group_id(group_id):
    """A Roblox group id `publish_clip` may upload under: digits only, positive.
    Refuses anything else before it is recorded on the manifest or rendered into
    Luau -- a malformed id would otherwise fail only when CreateAssetAsync runs
    in Studio, as an opaque group-permission error days later."""
    s = str(group_id).strip()
    if not s.isdigit() or int(s) == 0:
        raise ValueError("publish_clip: group id must be a positive integer (got %r)" % (group_id,))
    return int(s)


def creator_render(group_id):
    """The three `publish_clip.luau` placeholders that describe who this asset
    uploads under: CREATOR_FIELDS, the fragment spliced into the
    CreateAssetAsync table (empty for the Studio user -- the unchanged default,
    the table renders exactly as it did before this existed -- else
    CreatorId/CreatorType = Enum.AssetCreatorType.Group for a validated group
    id; witnessed 2026-09-25: that pair publishes a group-owned asset a
    group-owned experience can load, where a user-owned copy of the same clip
    is refused), and CREATOR_ID_EXPR/CREATOR_TYPE_EXPR, the matching Luau
    expressions the RUNNER_RESULT echoes back.

    That echo is deliberate, not decorative: `stages.clips.creator_group_id`
    is a single manifest-wide setting a later `publish_clip` on a DIFFERENT
    clip can already have overwritten by the time this one is ingested, so
    `ingest()` records the creator from what this step's own result reports
    it actually ran with, never from re-reading that manifest field."""
    if group_id is None:
        return {"CREATOR_FIELDS": "", "CREATOR_ID_EXPR": "nil", "CREATOR_TYPE_EXPR": '"User"'}
    # Re-validated here even though clips._resolve_creator_group already validated
    # a --group before recording it: `studio.emit(..., GROUP_ID=...)` is itself a
    # direct entry point (`studio emit publish_clip --param GROUP_ID=...`), so this
    # is the only validation a caller that skips clips.py ever gets.
    gid = validate_group_id(group_id)
    return {
        "CREATOR_FIELDS": "\n\tCreatorId = %d,\n\tCreatorType = Enum.AssetCreatorType.Group," % gid,
        "CREATOR_ID_EXPR": str(gid),
        "CREATOR_TYPE_EXPR": '"Group"',
    }


def emit(m, step, **params):
    if step == "publish_clip":
        if "UNVERIFIED_OK" in params:
            raise ValueError(UNVERIFIED_OK_RETIRED)
        require_verified(m, params.get("CLIP"), str(params.get("CLIP_NAME")))
        params.update(creator_render(params.pop("GROUP_ID", None)))
    template = manifest.template_name(m)
    # Manifest first, registered/pack default second: `studio.park_folder` is the
    # per-character override, so it has to beat a default register_steps merged in.
    folder = park_folder(m)
    if folder:
        params.setdefault("PARK_FOLDER", folder)
    params.setdefault("NAME", m["name"]); params.setdefault("TEMPLATE", template)
    params.setdefault("HEIGHT", m["height_studs"]); params.setdefault("SCALE", 1)
    params.setdefault("MODEL_PATH", "workspace:FindFirstChild(%r, true)" % template)
    params.setdefault("WALK_ID", ""); params.setdefault("CAMERA", "close"); params.setdefault("LOD", "close")
    if step == "treadmill_scaled":
        # The post-scale measurement plays the walk at animSpeedScale, which
        # clips.speed_scale() must have recorded first; refusing here keeps a
        # speed-1 run from being ingested as the scaled one and passing E19.
        scale = m["stages"].get("clips", {}).get("animSpeedScale")
        if not scale:
            raise RuntimeError("treadmill_scaled needs stages.clips.animSpeedScale; run clips speed-scale first")
        params["SPEED"] = float(scale)
    if step == "sethip":
        # Refusing beats defaulting: writing an uncorrected hip through the step
        # whose whole job is the correction would look exactly like a converged
        # ground fit on the manifest.
        hip = (m["stages"].get("groundfit") or {}).get("corrected_hip")
        if hip is None:
            raise RuntimeError("sethip needs stages.groundfit.corrected_hip; run the `settle` step "
                               "(Play) and ingest it first")
        params.setdefault("HIP", hip)
    if step == "probe_feet":
        params.setdefault("SETTLED_BOTTOM", settled_bottom(m) if settled_bottom(m) is not None else "")
    params.setdefault("SPEED", 1)
    d = Path(m["out_dir"]) / "studio"; d.mkdir(parents=True, exist_ok=True)
    p = d / (step + ".luau"); p.write_text(render(step, **params)); print(p); return p


def _read_result(result_path):
    """The orchestrator may paste the returned line verbatim; that line is not JSON."""
    raw = Path(result_path).read_text().strip()
    if raw.startswith(RESULT_PREFIX):
        raw = raw[len(RESULT_PREFIX):]
    data = json.loads(raw)
    if isinstance(data, str) and data.startswith(RESULT_PREFIX):
        data = json.loads(data[len(RESULT_PREFIX):])
    return data


def _write_eval(m, dotted, value):
    """Merge one key into <out>/eval.json without disturbing what eval_cmd wrote."""
    p = Path(m["out_dir"]) / "eval.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {}
    if p.is_file():
        try:
            doc = json.loads(p.read_text())
        except ValueError:
            doc = {}
    if not isinstance(doc, dict):
        doc = {}
    section, key = dotted.split(".", 1)
    doc.setdefault(section, {})[key] = value
    p.write_text(json.dumps(doc, indent=2, sort_keys=True, default=str))
    return p


# build_kfs read-back tolerances. Keyframe times are written to 5 decimals and
# read back as float32; a model scale is read back as a float.
KFS_TIME_TOL = 1e-3
KFS_SCALE_TOL = 1e-3


class KfsMismatch(ValueError):
    """The KeyframeSequence in Studio is not the one `clips build` recorded."""


def check_kfs(clip, item, data):
    """Compare a `build_kfs` read-back with the `kfs_expected` record `clips
    build` left on the clip item; raise KfsMismatch naming every difference.
    Nothing is recorded for a sequence that fails: publishing it would publish
    something other than what the manifest says was built."""
    exp = item.get("kfs_expected")
    name = item.get("kfs_name")
    rebuild = ("`clips build --clip %s --anims-dir <the Rojo-mapped animations directory>`, then let Rojo sync "
               "it into ServerStorage.Assets.Anims and re-run build_kfs" % clip)
    if not exp or not name:
        raise KfsMismatch("build_kfs: clip %s has no `clips build` record (kfs_name, kfs_expected) to verify "
                          "against; run %s" % (clip, rebuild))
    if not data.get("found"):
        raise KfsMismatch("build_kfs: ServerStorage.Assets.Anims.%s is not in the place. Run %s. The step no "
                          "longer builds the sequence in Studio: execute_luau has no Network capability since "
                          "Studio 0.739" % (data.get("name") or name, rebuild))
    if not data.get("isKfs"):
        raise KfsMismatch("build_kfs: ServerStorage.Assets.Anims.%s is not a KeyframeSequence" % data.get("name"))
    problems = []
    if data.get("name") != name:
        problems.append("name %r, but `clips build` last wrote %r" % (data.get("name"), name))
    if data.get("keyframes") != exp["keyframes"]:
        problems.append("%s keyframes, expected %s" % (data.get("keyframes"), exp["keyframes"]))
    if abs(float(data.get("lastTime") or 0) - float(exp["last_time"])) > KFS_TIME_TOL:
        problems.append("last keyframe at %.5f s, expected %.5f s (time scale %s)" % (
            float(data.get("lastTime") or 0), float(exp["last_time"]), exp.get("time_scale")))
    if bool(data.get("loop")) != bool(exp["loop"]):
        problems.append("Loop %s, expected %s" % (data.get("loop"), exp["loop"]))
    if data.get("priority") != exp["priority"]:
        problems.append("Priority %r, expected %r" % (data.get("priority"), exp["priority"]))
    if exp["keyframes"] and data.get("rootPose") != "HumanoidRootPart":
        problems.append("root pose %r, expected 'HumanoidRootPart'" % data.get("rootPose"))
    if bool(data.get("rootNode")) != bool(exp["root_node"]):
        problems.append("HumanoidRootNode pose %s, expected %s" % (
            "present" if data.get("rootNode") else "absent", "present" if exp["root_node"] else "absent"))
    if problems:
        raise KfsMismatch("build_kfs: ServerStorage.Assets.Anims.%s is not the sequence `clips build` recorded "
                          "(%s). Run %s" % (data.get("name"), "; ".join(problems), rebuild))
    # Against the template it will play on (SKILL.md clip transfer laws 3-5).
    if not data.get("templateFound"):
        raise KfsMismatch("build_kfs: the template is not under the park folder, so the root-node and scale "
                          "checks cannot run; park it (or fix studio.park_folder) and re-run build_kfs")
    if bool(data.get("templateHasNode")) != bool(exp["root_node"]):
        raise KfsMismatch(
            "build_kfs: the template %s a HumanoidRootNode bone but the sequence was built %s the node pose, so "
            "the Animator would drop its root translation. Record the rig's shape (adopt_inspect for an adopted "
            "rig) and run %s" % ("has" if data.get("templateHasNode") else "has no",
                                 "without" if exp["root_node"] else "with", rebuild))
    scale, built = float(data.get("templateScale") or 0), float(exp["root_scale"])
    if exp.get("root_motion") and abs(scale - built) > KFS_SCALE_TOL * max(1.0, abs(built)):
        raise KfsMismatch(
            "build_kfs: the template's scale is %.4f but the root motion was divided by %.4f at `clips build` "
            "(stages.wire.result.scale); ingest the scale/wire step that set it and run %s" % (scale, built, rebuild))


def _dig_result(m, key):
    return ((m["stages"].get("groundfit") or {}).get("result") or {}).get(key)


def ingest(m, step, result_path, lod=None, clip=None):
    data = _read_result(result_path)
    # A registered handler owns its step outright, and is consulted BEFORE
    # STAGE_OF is read: a step contributed with only a handler has no stage here,
    # and the catch-all branch below would otherwise write a foreign result onto
    # some stage's `result` key.
    handler = INGEST_HANDLERS.get(step)
    if handler is not None:
        return handler(m, data, Path(m["out_dir"]))
    stage = STAGE_OF[step]
    if step == "probe_feet":
        if lod not in LODS:
            raise ValueError("probe_feet measures one LOD per run: pass --lod close|far (got %r)" % (lod,))
        assert "gap" in data, "probe_feet result lacks gap: %r" % (data,)
        _write_eval(m, "groundfit.gap_%s" % lod, data["gap"])
        # The whole result beside the bare number: E13 reads `settledMeasure`
        # (was this posed at a MEASURED settled height, or at the hip?) and E14
        # reads `inPlay` (was the far-LOD vertex read its own measurement?), and
        # neither question can be asked of a float.
        _write_eval(m, "groundfit.probe_%s" % lod, data)
        return data
    if step == "probe_walk":
        _write_eval(m, "wire.walk_probe", data)
        return data
    if step in ("build_kfs", "publish_clip", "bench_clip"):
        # Which logical clip this run verified, published or benched cannot be
        # inferred from the result (the Luau reports the PUBLISHED title, not
        # the catalog key), so it is named rather than assumed -- the same rule
        # probe_feet's --lod follows.
        items = dict((m["stages"].get("clips") or {}).get("items") or {})
        if clip not in items:
            raise ValueError("%s: pass --clip with a clip already on "
                             "stages.clips.items (got %r; have %s)"
                             % (step, clip, sorted(items) or "none"))
        item = dict(items[clip])
        if step == "build_kfs":
            check_kfs(clip, item, data)
            item["kfs_verified"] = data
        elif step == "bench_clip":
            timeline = data.pop("timeline", None)
            if timeline is not None:
                tl = Path(m["out_dir"]) / "clips" / ("%s.bench.json" % clip)
                tl.parent.mkdir(parents=True, exist_ok=True)
                tl.write_text(json.dumps(timeline))
                data["timeline_file"] = str(tl)
            item["bench"] = data
        else:
            asset_id = data.get("assetId")
            assert asset_id, "publish_clip result lacks assetId: %r" % (data,)
            item["roblox_id"] = str(asset_id)
            item["anim_attribute"] = data.get("attribute")
            # What the step ACTUALLY ran with, echoed back in the result --
            # never re-read from stages.clips.creator_group_id: that is a
            # single manifest-wide setting, and a later `publish_clip` on a
            # DIFFERENT clip can already have overwritten it by the time this
            # one is ingested (emit Walk --group 100, emit Idle --group 200,
            # then ingest Walk: reading the manifest here would record Walk
            # under 200, though it uploaded under 100).
            if data.get("creatorType") == "Group":
                creator_id = data.get("creatorId")
                assert creator_id, "publish_clip result claims a Group creator with no creatorId: %r" % (data,)
                item["creator"] = {"type": "Group", "id": int(creator_id)}
            else:
                item["creator"] = {"type": "User"}
            ids = dict((m["stages"].get("clips") or {}).get("roblox_ids") or {})
            ids[clip] = str(asset_id)
            manifest.set_stage(m, "clips", roblox_ids=ids)
        items[clip] = item
        manifest.set_stage(m, "clips", items=items)
        manifest.save(m)
        if step == "bench_clip":
            # Recorded whatever it reads: the gates are eval rows E30-E32, so a
            # breach is named here and judged by `runner eval`, never refused --
            # not even a bad bench_gates override, which `runner eval` names.
            try:
                verdict = eval_cmd.bench_verdict(m, clip)
            except ValueError as e:
                print("bench gate: %s recorded but not judged: %s" % (clip, e))
                return data
            for line in verdict["breaches"]:
                print("bench gate: %s (eval rows E30-E32)" % line)
            if verdict["unusable"]:
                print("bench gate: %s cannot be judged (%s); re-run the bench "
                      "(eval rows E30-E32 list it)" % (clip, verdict["unusable"]))
        return data
    if step == "dump_rest":
        assert "LowerTorso" in data, "rest dump lacks LowerTorso"
        (Path(m["out_dir"]) / "rest.json").write_text(json.dumps(data, indent=1))
        # E11 ("rest dump complete/orthonormal") is a GATE, and eval_cmd evaluates
        # stages.rest.result with _all_true -- true for any non-empty list. Storing
        # the bone NAMES as the result therefore made the gate structurally unable
        # to fail: a one-bone dump printed PASS for a completeness check nothing
        # computed. The result is now the two computed booleans; the names and the
        # diagnostics ride on their own stage keys, out of the gate's reach.
        # Malformed entries are recorded (as incomplete), never raised on: ingest
        # is the recording surface, `runner eval` is the reporting one.
        manifest.set_stage(m, "rest", result=metrics.rest_dump_checks(data),
                           bones=sorted(data.keys()), rest_detail=metrics.rest_dump_detail(data),
                           artifact=str(Path(m["out_dir"]) / "rest.json"))
    elif step == "groundfit":
        assert data.get("hipHeight", 0) > 0, "hipHeight must be positive: %r" % data
        manifest.set_stage(m, "groundfit", result=data)
    elif step == "adopt_inspect":
        # An adopted rig's wire stage IS this reading: scale (clips.build's
        # root_scale), hip/sole (the bench's sole plane), and whether the rig has
        # a HumanoidRootNode. Refusing a zero scale or a missing hip beats
        # recording a manifest that `clips build` would silently mis-scale.
        assert (data.get("scale") or 0) > 0, "adopt_inspect: scale must be positive: %r" % (data,)
        assert (data.get("hip") or 0) > 0, "adopt_inspect: hip (HipHeightStuds) must be positive: %r" % (data,)
        assert isinstance(data.get("bones"), list) and data["bones"], "adopt_inspect: bones list missing: %r" % (data,)
        result = {k: data.get(k) for k in ("scale", "hip", "sole", "hrpHeight", "hasRootNode", "boneCount", "rigTypeR15")}
        result["adopted"] = True
        manifest.set_stage(m, "wire", result=result, bones=sorted(data["bones"]))
    elif step == "settle":
        # groundfit's `hipHeight` is the SOLE OFFSET (HRP bottom to the lowest
        # vertex at rest); the settle measures how far above its HipHeight the
        # Humanoid actually holds that bottom. corrected_hip is recorded beside
        # them, never over `result`, so a second pass can recompute from the same
        # sole offset instead of from an already-corrected number.
        for key in ("settledBottom", "hip"):
            assert key in data, "settle result lacks %s: %r" % (key, data)
        sole = _dig_result(m, "hipHeight")
        if sole is None:
            raise RuntimeError("settle ingest needs stages.groundfit.result.hipHeight; "
                               "run the `groundfit` step first")
        hip = groundfit.corrected_hip(sole, data["settledBottom"], data["hip"])
        fields = dict(settle=data, sole_offset=sole,
                      hover_excess=float(data["settledBottom"]) - float(data["hip"]),
                      corrected_hip=hip)
        applied = ((m["stages"].get("groundfit") or {}).get("hip_applied") or {}).get("hip")
        if applied is not None and abs(float(data["hip"]) - float(applied)) <= HIP_MATCH_TOL:
            # A VERIFICATION settle: this one ran with the corrected hip already
            # written onto the template, so its settled bottom measures the
            # loop's OUTPUT rather than its input. Only this number may pose
            # probe_feet -- see settled_bottom(). Kept with the hip it was
            # measured at so a later sethip invalidates it instead of aging into
            # a wrong answer.
            fields["verified"] = {"hip": float(data["hip"]),
                                  "bottom": float(data["settledBottom"])}
        else:
            # This settle ran at a hip `sethip` did not write, so the template is
            # not in the state any earlier verification measured -- a re-run of
            # the loop from a fresh ground fit, typically. Clear the standing
            # verification rather than let probe_feet be posed from it.
            fields["verified"] = None
        manifest.set_stage(m, "groundfit", **fields)
    elif step == "sethip":
        assert "hip" in data, "sethip result lacks hip: %r" % (data,)
        manifest.set_stage(m, "groundfit", hip_applied=data)
    elif step == "capture_ids":
        manifest.set_stage(m, "wire", asset_ids=data)
    elif step == "park":
        # park, capture_ids and zoo_capture all share the "wire" stage, so each
        # gets its own key. Routing park through the catch-all below would put
        # {"parked": ...} on stages.wire.result after `wire` had written it,
        # wiping the four self-checks eval_cmd's E23 gate reads while
        # is_done(m, "wire") stays True and hides the loss. `park` always follows
        # `wire`; `capture_ids` comes before `park` with the default MODEL_PATH,
        # or after it only with `--param MODEL_PATH=<park folder>["<template>"]`
        # (RUN ORDER, in the module docstring).
        manifest.set_stage(m, "wire", parked=data)
    elif step == "treadmill":
        manifest.set_stage(m, "clips", treadmill=data)
    elif step == "treadmill_scaled":
        # Recorded beside the speed-1 run, never over it: E19 reads this key and
        # stays PEND until it exists (the speed-1 stride derives animSpeedScale,
        # so comparing it back against that scale could never fail).
        data = dict(data, animSpeedScale=m["stages"].get("clips", {}).get("animSpeedScale"))
        manifest.set_stage(m, "clips", treadmill_scaled=data)
    elif step == "zoo_capture":
        manifest.set_stage(m, "wire", capture=data)
    else:
        manifest.set_stage(m, stage, result=data)
    manifest.save(m); return data


def _emit_cli(x):
    emit(manifest.load(x.manifest), x.step, **dict(kv.split("=", 1) for kv in x.param))
    return 0


def _ingest_cli(x):
    ingest(manifest.load(x.manifest), x.step, x.result, lod=x.lod, clip=x.clip)
    return 0


def register(sub):
    p = sub.add_parser("studio"); s = p.add_subparsers(dest="cmd", required=True)
    e = s.add_parser("emit"); e.add_argument("step", choices=STEPS); e.add_argument("--manifest", required=True)
    e.add_argument("--param", action="append", default=[], help="KEY=VALUE")
    # The CLI wrappers return an exit CODE, never the emitted Path / ingested dict:
    # cli.py does `sys.exit(main() or 0)`, so returning the value itself makes a
    # successful `runner studio emit` print the object to stderr and exit 1.
    e.set_defaults(func=_emit_cli)
    i = s.add_parser("ingest"); i.add_argument("step", choices=STEPS); i.add_argument("--manifest", required=True)
    i.add_argument("--lod", choices=LODS, default=None, help="probe_feet only: which LOD this result measured")
    i.add_argument("--clip", default=None,
                   help="build_kfs / publish_clip / bench_clip only: which clip this result verified, published or benched")
    i.add_argument("result"); i.set_defaults(func=_ingest_cli)
