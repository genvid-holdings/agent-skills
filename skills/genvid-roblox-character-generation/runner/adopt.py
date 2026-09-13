"""Adopt a rig that is ALREADY parked under the park folder into a
runner manifest, so the clip chain (`clips transfer` -> `clips build-kfs` ->
`clips publish-clip` -> `clips bench` -> `clips bind`) runs on it unchanged.

Why: the chain is manifest-driven, and a rig that predates the runner (the
old-pipeline characters) or arrives as a bare template has
no manifest. On 2026-09-10 two death clips were hand-driven end to end for
exactly that reason.

What an adopted manifest is NOT: a claim that plate/mesh/rig ever ran here.
Those stages are simply not on its chain -- `stage_order` starts at `rest`
(`manifest.stages_for` honours it), and `manifest.is_done` is never lied to
with a fake media_id. `wire` is filled by the `adopt_inspect` Studio step
(`studio.ingest`) from the parked template itself: its Model:GetScale (what
`clips build` divides root motion by), hip, sole, bone list and whether it
carries a HumanoidRootNode (which decides whether `build_kfs` inserts the node
pose). `rest` is the ordinary `dump_rest` step, pointed at the parked template.

Name vs template: `name` is the brand-free stem every published title is built
from (e.g. SmallDeath_v1); `template` is the Studio template's own name
and becomes `contract_name`, so `studio.emit` renders TEMPLATE/MODEL_PATH from
it -- the same split the bake-off used (`manifest.new` docstring).
"""
from pathlib import Path

import manifest
import studio

VENDOR = "adopted"
STAGE_ORDER = ("rest", "wire", "clips", "record")
INSPECT_STEP = "adopt_inspect"


def _model_path(template, folder):
    """The parked template's Luau path: the park folder plus the template name.

    Which folder is not this module's to know. It comes from the manifest's own
    `studio.park_folder` when it has one, else from studio.RENDER_DEFAULTS --
    which a downstream skill may have set through studio.register_steps."""
    return "(%s)[%r]" % (folder, template)


def adopt_manifest(name, project_id, height_studs, out_dir, *, template, asset_id, assignee,
                   production_title, park_folder=None):
    """`production_title` is required and keyword-only, like `asset_id` and
    `assignee`: an adopted rig's chain ends in `clips bind`, which creates governed
    media under an asset whose description carries the title, and
    `manifest.production_title()` refuses rather than guessing one. Demanding it here
    turns that into an error at adoption -- before any Studio step has run -- instead
    of one at the first bind, on a manifest that already carries real work."""
    if not asset_id:
        raise ValueError("adopt: asset_id is required -- clips.bind() reads it straight off the manifest")
    if not assignee:
        raise ValueError("adopt: assignee is required -- every claim this chain writes is claimed FOR that reviewer")
    if not production_title:
        raise ValueError("adopt: production_title is required -- this chain's binds write it into "
                         "governed asset descriptions and there is no default (manifest.production_title)")
    m = manifest.new(name, project_id, height_studs, VENDOR, out_dir, contract_name=template,
                     assignee=assignee, production_title=production_title)
    m["asset_id"] = asset_id
    m["kind"] = "adopted"
    m["stage_order"] = list(STAGE_ORDER)
    m["adopted"] = {"template": template,
                    "note": "pre-existing parked template; plate/mesh/rig are not on this chain and were never run by the runner"}
    if park_folder:
        studio.set_park_folder(m, park_folder)
    manifest.note(m, "adopted parked template %s as %s: chain starts at rest (adopt_inspect fills wire)" % (template, name))
    manifest.save(m)
    return m


def emit(m, step, park_folder=None, **params):
    """studio.emit() with MODEL_PATH pinned to the PARKED template: the default
    looks in workspace, where an adopted rig is not."""
    if m.get("kind") != "adopted":
        raise ValueError("adopt.emit is for adopted manifests only (kind=%r)" % m.get("kind"))
    folder = park_folder or studio.park_folder(m) or studio.RENDER_DEFAULTS["PARK_FOLDER"]
    params.setdefault("MODEL_PATH", _model_path(manifest.template_name(m), folder))
    return studio.emit(m, step, **params)


def _adopt_cli(x):
    adopt_manifest(x.name, x.project_id, x.height, x.out_dir, template=x.template,
                   asset_id=x.asset_id, assignee=x.assignee,
                   production_title=x.production_title, park_folder=x.park_folder)
    print(Path(x.out_dir) / "manifest.json")
    return 0


def _adopt_emit_cli(x):
    params = {"MODEL_PATH": x.model_path} if x.model_path else {}
    emit(manifest.load(x.manifest), x.step, **params)
    return 0


def register(sub):
    """Called from rig.register(): the adopt verbs live under `runner rig`."""
    a = sub.add_parser("adopt", help="give an already-parked template a manifest whose chain starts at rest")
    a.add_argument("--name", required=True, help="brand-free stem for published titles, e.g. Small")
    a.add_argument("--template", required=True, help="the parked template's own name in Studio")
    a.add_argument("--height", type=float, required=True, help="rig height in studs (the game's own height figure for this character type)")
    a.add_argument("--project-id", type=int, required=True)
    a.add_argument("--asset-id", required=True, help="the Genvid cast-member asset the clips bind under")
    a.add_argument("--assignee", required=True, help="reviewer email every claim is made for")
    a.add_argument("--production-title", required=True, help="the production's own title; written "
                   "verbatim into the description of every asset this chain's binds create")
    a.add_argument("--out-dir", required=True)
    a.add_argument("--park-folder", help="Luau expression for the folder the template is parked under; "
                   "defaults to studio.RENDER_DEFAULTS['PARK_FOLDER']")
    a.set_defaults(func=_adopt_cli)
    e = sub.add_parser("adopt-emit", help="emit adopt_inspect or dump_rest against the PARKED template")
    e.add_argument("--manifest", required=True)
    e.add_argument("--model-path", help="override the parked-template Luau expression outright")
    e.add_argument("step", choices=(INSPECT_STEP, "dump_rest"))
    e.set_defaults(func=_adopt_emit_cli)
