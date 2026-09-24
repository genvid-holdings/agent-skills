"""Biome location plates: three candidate establishing shots -> Genvid `location`
asset -> the reviewer's approval, then the sky and the prop kit. Also the HUD
viz-dev asset: same plate machinery, a shorter `kind="hud"` manifest, and a
`set_dressing`/`set_dressing_image` bind instead of `location`/`location_image`.

Every generating step is emit/ingest (request.py). The runner calls no provider
and names no model; the caller generates with a model of its own choosing:

    biome emit plates [--item 1|2|3]      -> text-to-image requests, one per location candidate
    biome emit hud-plates [--item V]      -> text-to-image requests, one per HUD variant
    biome ingest plates|hud-plates --item K [--create-asset | --asset-id A] <file-or-url>
                                          -> records and binds one candidate
    biome approved --media-id ID          -> records the candidate the reviewer approved
    biome emit sky                        -> image-to-panorama request from the approved plate
    biome ingest sky <file-or-url>        -> records the equirect, splits the six faces, binds all seven
    biome emit kit-sheet [--props ...]    -> image-to-image request for the prop sheet, plate as style
    biome ingest kit-sheet <file-or-url>  -> records the sheet, splits the tiles, binds them and
                                             creates one asset per prop
    biome emit kit-model --prop K ...     -> image-to-3D requests, one per prop tile
    biome ingest kit-model --prop K (<file-or-url> | --roblox-asset-id N)
                                          -> binds the prop's model (a file), or writes the
                                             platform registration payloads (an id only)
    biome kit-model-registered --prop K --media-id ID
                                          -> records the finalized registration's media id

`bind`, `sky-faces`, `sky-bind`, `kit-split`, `kit-bind` and `kit-model-bind`
re-run the processing and binds on what is recorded (after a ClaimPending, or a
--record-only ingest). Every bind attests the provider, model, params and cost
the caller reported at ingest; the pack's own splits (faces, tiles) attest the
runner's Blender step at no vendor cost.

The palettes, HUD tokens, prop kit and style words all belong to the title and
arrive on the manifest as its design document (runner/design.py); none of them
lives in this pack.
"""
import json, shutil, subprocess
from pathlib import Path
import design, manifest, genvid_bind, studio, request, budget, cost, mesh

STAGE_ORDER = ("plate", "sky", "kit", "materials", "record")

# The location candidates, and a seed per candidate the request suggests (a
# caller whose model takes no seed ignores it).
PLATE_KEYS = ("1", "2", "3")
SEEDS = (11, 23, 37)

SKY_PROMPT = ("seamless 360 panorama of this exact scene, same palette and painting style, "
              "sky above, ground below, no characters, no text")
SKY_FACES = ("ft", "bk", "lf", "rt", "up", "dn")

# The biome palettes are NOT here: which biomes a title has, and the hexes by role
# that condition each one's establishing shot, are that title's own world design.
# They arrive on the manifest as `m["design"]["palettes"]` and are read through
# design.palette() / design.biome_names(), which raise when the document is absent.

# The HUD viz-dev asset. Same `biome` plate machinery as a location, but a
# two-stage manifest -- no sky/kit/materials, just plate -> record -- and a
# "set_dressing" asset instead of "location".
HUD_STAGE_ORDER = ("plate", "record")
HUD_VARIANTS = ("pill", "chunky", "minimal")
HUD_SEEDS = {"pill": 5, "chunky": 6, "minimal": 7}
HUD_VARIANT_DESC = {
    "pill": "approved ramp as-is",
    "chunky": "thicker strokes, bigger numbers",
    "minimal": "thinner panels, smaller ramp",
}
# The HUD's token hexes by role are the title's, not this pack's: they arrive as
# `m["design"]["hud_tokens"]` (design.hud_tokens()). The HUD plate is conditioned on
# them so the approved variant's layout can be read straight back into the title's
# own design-token module -- design.luau_module(m, "design_tokens") names it.

# The prop kit -- one sheet image (the approved plate as the style reference),
# split by Blender into per-prop tiles, one set_dressing/greenery asset per prop.
# WHICH props is the title's design decision: the list arrives as
# `m["design"]["kit_props"]` (design.kit_props()) and `--props` overrides it per
# run. Only the sheet GRID has defaults here, because a 3x4 sheet is a property of
# the image, not of anyone's world -- and rows/cols are arguments rather than
# prompt text, so KIT_PROMPT derives the grid size and the prop count from whatever
# `props`/`rows`/`cols` it is actually called with.
KIT_ROWS_DEFAULT = 4
KIT_COLS_DEFAULT = 3
# Interfaces: "one set_dressing (or greenery for plants: names containing
# tree/bush/flower/mushroom/patch/pond) asset per prop".
GREENERY_WORDS = ("tree", "bush", "flower", "mushroom", "patch", "pond")

GROUP = "biome"
PLATES_STEP, HUD_STEP, SKY_STEP, KIT_SHEET_STEP, KIT_MODEL_STEP = (
    "plates", "hud-plates", "sky", "kit-sheet", "kit-model")
# Budget keys: the candidates, the sky, the sheet and the prop models are
# separate spends; a verdict covers its item set (budget.gate).
PLATES_BUDGET, SKY_BUDGET, KIT_BUDGET, KIT_MODEL_BUDGET = "biome.plates", "sky", "kit", "kit-model"

IMAGE_EXT = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}
MODEL_EXT = {"glb": ".glb", "fbx": ".fbx", "obj": ".obj"}
MODEL_KINDS = tuple(MODEL_EXT)
IMAGE_CHECKED = "image type by content: PNG, JPEG or WebP"
REQUESTED_CHECKED = "a request was emitted for this item (the budget check ran), unless --unrequested"

# The budget read asks for the manifest's own asset (the location), not the
# prop's asset: a known gap, stated on every kit-model request.
KIT_MODEL_BUDGET_NOTE = ("The budget check reads the headroom of the location asset this manifest binds to, not "
                         "of the prop's own asset; the prop asset's own budget is not checked. A known gap.")
FINALIZE_COST_NOTE = ("finalize_media_registration has no attested-cost field, so the cost is carried here for "
                      "information only; the ingest record at stages.kit.props.<prop>.generated.model holds it")

NO_BLENDER = ("biome ingest %s needs Blender on PATH: it splits the result in Blender before binding. Install "
              "Blender, or pass --record-only to record the result now and run `biome %s` then `biome %s` "
              "where Blender is installed.")


def _old_shape(step, what):
    return ("%s came from the old generator, whose attestation this bind no longer sends. Record the result "
            "first with `biome ingest %s --unrequested \"<reason>\" --provider <p> --model <m> --cost "
            "<c>|--cost-unobserved <file>`, adding --supersede when it is already bound." % (what, step))


def KIT_PROMPT(props, rows=KIT_ROWS_DEFAULT, cols=KIT_COLS_DEFAULT):
    return ("a %d×%d grid sheet of %d separate game props in the exact painting "
            "style and palette of the reference, each prop alone on a flat neutral "
            "gray tile, three-quarter front view, readable silhouette, no text; "
            "props: %s" % (cols, rows, len(props), ", ".join(props)))


def KIT_MODEL_PROMPT(name):
    return "%s, stylized game prop, single object" % name


def _kit_vocab(m, name):
    """(asset_type, model_link_type) for one kit prop, per the master contract's
    prefix-equals-asset-type rule. `set_dressing_model`, `greenery_model` and
    `set_dressing_image` all exist in the backend link-type enum (witnessed
    2026-09-03), so no `prop_model` fallback is needed. That is the default
    here; `m["vocab"]["kit_model_ok"] = False`
    (the fallback path) reproduces the
    fallback -- every kit item typed `prop`, bound `prop_model` -- for a project
    where the vocabulary check came back the other way."""
    ok = (m.get("vocab") or {}).get("kit_model_ok", True)
    if not ok:
        return "prop", "prop_model"
    low = name.lower()
    asset_type = "greenery" if any(w in low for w in GREENERY_WORDS) else "set_dressing"
    return asset_type, asset_type + "_model"


def _check_biome(m, biome):
    """Validate a biome name against the manifest's own design document. There is no
    constant to check against: the names belong to the title (design.palette raises
    with the title's list when the name is not one of them)."""
    design.palette(m, biome)


def _check_hud_variant(variant):
    if variant not in HUD_VARIANTS:
        raise ValueError("unknown HUD variant %r: choose from %s" % (variant, ", ".join(HUD_VARIANTS)))


def PLATE_PROMPT(m, biome=None):
    """The establishing-shot prompt for one of this title's biomes. Everything
    title-bound -- which biome names exist, their hexes by role, and the words that
    name the art direction -- comes from the manifest's design document; the frame
    (wide establishing shot, palette-by-role, the no-characters/no-text guard,
    16:9) is the pack's."""
    biome = m["biome"] if biome is None else biome
    hexes = ", ".join(design.palette(m, biome))
    return ("A wide establishing shot of a %s biome for a %s Roblox "
            "game, using this palette by role: %s. No characters, no text, 16:9, painterly, "
            "readable silhouettes, clear ground plane." % (biome, design.style(m), hexes))


def HUD_PROMPT(m, variant):
    """The HUD viz-dev prompt. The pack supplies the frame -- a full-screen 16:9
    mockup, the palette-by-role line, the variant instruction, the font direction
    and the no-real-logos guard -- and the title supplies what its HUD actually
    shows (`design["hud_style"]`), the token hexes and the style words. Which
    panels a HUD has is a game-design decision, so the layout sentence is a
    fragment from the design document, not prose in this pack."""
    _check_hud_variant(variant)
    tokens = ", ".join("%s %s" % (k, v) for k, v in design.hud_tokens(m).items())
    return (
        "A full-screen mockup of the in-game HUD for a %s Roblox "
        "game at 16:9: %s. Fonts: chunky rounded display font for numbers, "
        "clean sans for labels. Palette hexes by role: %s. Variant '%s': %s. No real "
        "logos, no text other than placeholder numbers, gameplay scene blurred behind."
        % (design.style(m), design.hud_style(m), tokens, variant, HUD_VARIANT_DESC[variant])
    )


def init(biome=None, out_dir=None, project_id=None, kind="location", name=None, assignee=None,
         production_title=None, design_doc=None):
    """`kind="location"` (default): the biome-plate manifest, keyed on `biome`.
    `kind="hud"`: the HUD viz-dev manifest -- no `biome`, a two-stage
    stage_order (plate, record), named `name` (falls back to "HUD").

    `design_doc` is this title's design document (runner/design.py: palettes, HUD
    tokens, prop kit, style fragments, Luau module names). It is OPTIONAL HERE and
    only here: a per-title skill that drives this pack through its own CLI stamps
    `m["design"]` after `init` returns, the same way it stamps the park folder, so
    requiring it at construction would break that seam. When it IS given, the biome
    name is validated against its palettes immediately. When it is not, nothing is
    guessed and nothing is defaulted -- the first step that needs a design value
    (`biome emit plates`, `biome emit hud-plates`, `biome emit kit-sheet`,
    `biome lighting`) raises through design.load() naming the missing key.

    `assignee` (see manifest.new's docstring): the reviewer email every bind
    claims the assetImage task for. No default beyond None -- the binds refuse via
    genvid_bind.require_assignee rather than claim for 'me'.

    `project_id` and `production_title` both belong to the production, not to
    this pack, so neither carries a default: a wrong project id writes governed
    rows into someone else's project, and see manifest.production_title for why
    the title never falls back."""
    if project_id is None:
        raise ValueError("project_id is required: pass --project (this pack has no default project)")
    if kind == "hud":
        if not out_dir:
            raise ValueError("out_dir required")
        m = {
            "name": name or "HUD", "kind": "hud", "project_id": int(project_id),
            "out_dir": str(out_dir), "asset_id": None, "assignee": assignee,
            "production_title": production_title, "stages": {}, "notes": [],
            "stage_order": list(HUD_STAGE_ORDER),
        }
        if design_doc:
            design.attach(m, design_doc)
        return m
    if kind != "location":
        raise ValueError("unknown kind %r: choose from location, hud" % kind)
    if biome is None:
        raise ValueError("--biome required for kind=location")
    m = {
        "name": name or biome.capitalize(), "biome": biome, "kind": "location",
        "project_id": int(project_id),
        "out_dir": str(out_dir), "asset_id": None, "assignee": assignee,
        "production_title": production_title, "stages": {}, "notes": [],
        "stage_order": list(STAGE_ORDER),
    }
    if design_doc:
        design.attach(m, design_doc)
        _check_biome(m, biome)
    return m


# ---------------------------------------------------------------- shared

def _st(m, stage):
    return m["stages"].get(stage) or {}


def _blender(step, split, rebind, blender=None):
    path = blender or shutil.which("blender")
    if not path:
        raise RuntimeError(NO_BLENDER % (step, split, rebind))
    return path


def _check_image(path):
    return request.check_kind(path, request.IMAGE_KINDS)


def _record_kwargs(m, att, req, req_path, *, prompt, render_type, input_media_ids, default_prompt,
                   default_render_type, default_inputs):
    """request.make_record's keyword arguments other than the artifact: attested
    from the caller, defaulted from the emitted request."""
    ids = [str(i) for i in input_media_ids] or [i["media_id"] for i in req.get("inputs") or []] \
        or [str(i) for i in default_inputs]
    return dict(attestation=att, prompt=prompt if prompt is not None else (req.get("prompt") or default_prompt),
                render_type=render_type or req.get("render_type") or default_render_type,
                input_media_ids=ids, request_path=req_path, vendor_hint=m.get("vendor"))


def _make(m, att, req, req_path, **kw):
    """The `make` callable request.record_result takes."""
    fields = _record_kwargs(m, att, req, req_path, **kw)
    return lambda path, url, _kind: request.make_record(artifact=path, source_url=url, **fields)


def _read_request(m, stage, step, item, unrequested, emit_args=None):
    path = request.require_request(m, stage, step, item, unrequested, group=GROUP, emit_args=emit_args)
    return path, (json.loads(Path(path).read_text()) if path else {})


# ---------------------------------------------------------------- plates

def _plate_step(m):
    return HUD_STEP if m.get("kind") == "hud" else PLATES_STEP


def _check_plate_step(m, step):
    """The candidate step this manifest's kind takes; another step is refused by name."""
    want = _plate_step(m)
    if step is not None and step != want:
        raise request.IngestError("`biome %s` is for a %s manifest; this manifest is %s: use `biome %s`"
                                  % (step, "HUD" if step == HUD_STEP else "location",
                                     "a HUD" if want == HUD_STEP else "a location", want))
    return want


def _plate_keys(m):
    return HUD_VARIANTS if m.get("kind") == "hud" else PLATE_KEYS


def _check_plate_key(m, key):
    keys = _plate_keys(m)
    if str(key) not in keys:
        raise request.IngestError("candidate %r is not one of %s (--item)" % (key, ", ".join(keys)))
    return str(key)


def _plate_prompt(m, key):
    return HUD_PROMPT(m, key) if m.get("kind") == "hud" else PLATE_PROMPT(m)


def _plate_seed(m, key):
    return HUD_SEEDS[key] if m.get("kind") == "hud" else SEEDS[PLATE_KEYS.index(key)]


def _plate_stem(m, key):
    return ("hud_%s" if m.get("kind") == "hud" else "plate_%s") % key


def _plate_must_satisfy(m, key):
    if m.get("kind") == "hud":
        return ["a full-screen 16:9 mockup of the in-game HUD the prompt describes, in the token hexes it lists",
                "variant '%s': %s" % (key, HUD_VARIANT_DESC[key]),
                "no real logos, no text other than placeholder numbers"]
    return ["a wide 16:9 establishing shot of the biome, in the palette the prompt lists by role",
            "no characters, no text", "a clear ground plane and readable silhouettes"]


def _plate_runner(m, key, rec):
    """What the pack itself contributed to a candidate, for the bind's params.runner:
    the design values its prompt was built from."""
    if m.get("kind") == "hud":
        return {"stage": "hud-vizdev", "variant": key, "tokens": design.hud_tokens(m), "size_px": rec.get("size_px")}
    return {"stage": "biome-plate", "candidate": key, "palette": design.palette(m, m["biome"]),
            "size_px": rec.get("size_px")}


def emit_plates(m, estimate, item=None, step=None, model=None, no_urls=False):
    """Write one text-to-image request per candidate not yet generated (or for
    `item` alone) behind one budget check, and return their paths. A location
    manifest takes the `plates` step (candidates 1, 2, 3), a HUD manifest the
    `hud-plates` step (one per variant)."""
    step = _check_plate_step(m, step)
    manifest.require_stage(m, "plate")
    generated = _st(m, "plate").get("generated") or {}
    todo = [_check_plate_key(m, item)] if item is not None else [k for k in _plate_keys(m) if k not in generated]
    if not todo:
        manifest.note(m, "biome emit %s: every candidate is already generated; nothing requested" % step)
        manifest.save(m)
        return []
    entry = budget.gate(m, PLATES_BUDGET, estimate, model=model, items=todo)
    return [request.write_request(
        m, "plate", step, key, model_type="text-to-image", render_type="T2I", prompt=_plate_prompt(m, key),
        inputs=[], target={"format": ["png"], "aspect": "16:9", "long_edge_px": 2048},
        must_satisfy=_plate_must_satisfy(m, key), checked_at_ingest=[IMAGE_CHECKED, REQUESTED_CHECKED],
        budget_entry=entry, ingest=request.ingest_command(m, GROUP, step, key),
        extra={"suggested_seed": _plate_seed(m, key),
               "candidates": "every candidate is bound; `biome approved` then records the one approved"})
        for key in todo]


def _plate_bind_preconditions(m, asset_id, create):
    """Everything a candidate bind needs, checked before any governed write."""
    if create and m.get("asset_id"):
        raise ValueError("--create-asset: this manifest already has asset %s; bind further candidates onto it "
                         "without --create-asset" % m["asset_id"])
    if asset_id and m.get("asset_id") and str(asset_id) != str(m["asset_id"]):
        raise ValueError("--asset-id %s differs from the manifest's asset %s" % (asset_id, m["asset_id"]))
    if not (create or asset_id or m.get("asset_id")):
        raise ValueError("no asset_id: pass --asset-id or --create-asset")
    # A create_asset with nothing claimed after it leaves a real asset assigned to
    # nobody and never in_progress.
    genvid_bind.require_assignee(m)
    if create:
        # The created asset's description carries the production's own title.
        manifest.production_title(m)


def _create_plate_asset(m, run):
    is_hud = m.get("kind") == "hud"
    title = manifest.production_title(m)
    description = ("%s HUD concept: %s" % (title, m["name"])) if is_hud else ("%s biome: %s" % (title, m["name"]))
    asset_id = genvid_bind.create_asset(m["project_id"], m["name"], "set_dressing" if is_hud else "location",
                                        description, run=run)
    m["asset_id"] = asset_id
    manifest.save(m)
    return asset_id


def _plate_stale(m, key):
    """True when candidate `key` has a bound row that is not its recorded bytes: a
    superseding result whose bind has not run yet (it hit ClaimPending, or was
    recorded with --record-only)."""
    st = _st(m, "plate")
    rec = (st.get("generated") or {}).get(key) or {}
    return bool((st.get("media_ids") or {}).get(key)) and (st.get("bound_sha256") or {}).get(key) != rec.get("sha256")


def _plate_needs_bind(m, key):
    return not (_st(m, "plate").get("media_ids") or {}).get(key) or _plate_stale(m, key)


def _bind_plate(m, key, run):
    st = _st(m, "plate")
    rec = st["generated"][key]
    link_type = "set_dressing_image" if m.get("kind") == "hud" else "location_image"
    ids = dict(st.get("media_ids") or {})
    prior = ids.get(key)
    kw = request.bind_kwargs(rec, runner=_plate_runner(m, key, rec))
    if prior and "supersedes_media_id" not in kw["params"]:
        kw["params"]["supersedes_media_id"] = str(prior)
    ids[key] = genvid_bind.import_media(m["project_id"], link_type=link_type, asset_id=m["asset_id"], run=run, **kw)
    shas = dict(st.get("bound_sha256") or {}); shas[key] = rec["sha256"]
    entry = manifest.set_stage(m, "plate", media_ids=ids, bound_sha256=shas)
    if prior:
        entry["superseded_media_ids"] = list(entry.get("superseded_media_ids") or []) + [str(prior)]
        manifest.note(m, "biome bind: candidate %s media %s supersedes %s" % (key, ids[key], prior))
    manifest.save(m)
    return ids[key]


def _claim_plate_asset(m, asset_id, create, run):
    """Create and claim the asset, or gate on the existing one's claim."""
    if create:
        asset_id = _create_plate_asset(m, run)
        # No image task can exist on an asset created in this call, so the claim is
        # fire-and-forget for the binds in this call.
        genvid_bind.claim_assignment(m, asset_id)
        return
    if asset_id:
        m["asset_id"] = asset_id
        manifest.save(m)
    # A pre-existing asset (--asset-id, or one created by an earlier call) may have
    # been approved since, which refuses this bind until its task is reopened.
    genvid_bind.ensure_claim(m, m["asset_id"], "biome.plate")


def ingest_plate(m, key, result, att, *, step=None, asset_id=None, create=False, prompt=None, render_type=None,
                 input_media_ids=(), record_only=False, supersede=False, unrequested=None, opener=None,
                 run=subprocess.run):
    """Record one candidate and bind it; returns its media id (None with
    `record_only`). The first candidate on a new manifest passes `create`."""
    step = _check_plate_step(m, step)
    key = _check_plate_key(m, key)
    if not record_only:
        _plate_bind_preconditions(m, asset_id, create)
    req_path, req = _read_request(m, "plate", step, key, unrequested)
    make = _make(m, att, req, req_path, prompt=prompt, render_type=render_type, input_media_ids=input_media_ids,
                 default_prompt=_plate_prompt(m, key), default_render_type="T2I", default_inputs=())
    bound = (_st(m, "plate").get("media_ids") or {}).get(key)
    outcome = request.record_result(m, "plate", key, result, make, stem=_plate_stem(m, key), ext=IMAGE_EXT,
                                    check=_check_image, bound_media_id=bound, supersede=supersede, opener=opener)
    paths = dict(_st(m, "plate").get("paths") or {})
    paths[key] = _st(m, "plate")["generated"][key]["artifact"]
    manifest.set_stage(m, "plate", paths=paths)
    manifest.save(m)
    if record_only:
        return None
    if outcome == "unchanged" and not _plate_needs_bind(m, key):
        return bound
    _claim_plate_asset(m, asset_id, create, run)
    return _bind_plate(m, key, run)


def bind(m, asset_id=None, create=False, run=subprocess.run):
    """Bind every recorded candidate whose recorded bytes are not bound yet: the
    re-run after a ClaimPending or a --record-only ingest. Returns the media ids.
    A candidate already bound with its recorded bytes is never bound again; a
    superseding result binds a new row naming the one it supersedes."""
    st = _st(m, "plate")
    generated = st.get("generated") or {}
    ids = dict(st.get("media_ids") or {})
    if not generated:
        if st.get("urls") and not all(ids.get(k) for k in st["urls"]):
            raise ValueError(_old_shape(_plate_step(m) + " --item <key>", "stages.plate has no generated record: "
                                        "these candidates"))
        if ids:
            manifest.note(m, "biome bind: every candidate is already bound")
            manifest.save(m)
            return ids
        raise ValueError("no candidate recorded: run `biome ingest %s` first" % _plate_step(m))
    todo = [k for k in _plate_keys(m) if k in generated and _plate_needs_bind(m, k)]
    if not todo:
        manifest.note(m, "biome bind: every recorded candidate is already bound")
        manifest.save(m)
        return ids
    _plate_bind_preconditions(m, asset_id, create)
    _claim_plate_asset(m, asset_id, create, run)
    for key in todo:
        _bind_plate(m, key, run)
    return dict(_st(m, "plate").get("media_ids") or {})


def approved(m, media_id):
    """Record which bound plate candidate the reviewer approved. The orchestrator reads which
    one was approved with `genvid list-asset-media <project-id> <asset_id>` and passes its
    media_id here -- this makes no Genvid or vendor call itself, just a local manifest
    write. `require_stage(m, "sky")` (STAGE_ORDER) passes only once this has run."""
    media_ids = (m["stages"].get("plate") or {}).get("media_ids") or {}
    if media_id not in media_ids.values():
        raise ValueError("media_id %r is not one of this manifest's bound plate candidates: %s"
                          % (media_id, sorted(media_ids.values())))
    manifest.set_stage(m, "plate", media_id=media_id)
    manifest.save(m)
    return m


# ---------------------------------------------------------------- sky

def _approved_plate(m):
    plate_media_id = _st(m, "plate").get("media_id")
    if not plate_media_id:
        raise ValueError("no approved plate media_id on the manifest: run `biome approved` first")
    return str(plate_media_id)


def emit_sky(m, estimate, model=None, no_urls=False, run=subprocess.run):
    """Write the image-to-panorama request from the approved plate and return its path."""
    manifest.require_stage(m, "sky")
    plate_id = _approved_plate(m)
    entry = budget.gate(m, SKY_BUDGET, estimate, model=model, items=["equirect"])
    ins = request.inputs(m, [("source", plate_id)], no_urls=no_urls, run=run)
    return request.write_request(
        m, "sky", SKY_STEP, None, model_type="image-to-panorama", render_type="I2I", prompt=SKY_PROMPT,
        inputs=ins, target={"format": ["png"], "projection": "equirectangular", "aspect": "2:1"},
        must_satisfy=["a seamless 360-degree equirectangular panorama of the scene in the source plate",
                      "the same palette and painting style as the source plate",
                      "sky above, ground below, no characters, no text",
                      "2:1 (a result that is not 2:1 is recorded and flagged, not refused)"],
        checked_at_ingest=[IMAGE_CHECKED, REQUESTED_CHECKED, "the 2:1 aspect is measured and recorded"],
        budget_entry=entry, ingest=request.ingest_command(m, GROUP, SKY_STEP))


def _sky_bind_preconditions(m):
    if not m.get("asset_id"):
        raise ValueError("no asset_id on the manifest: run `biome bind` (plate stage) first")
    _approved_plate(m)
    genvid_bind.require_assignee(m)


def ingest_sky(m, result, att, *, prompt=None, render_type=None, input_media_ids=(), record_only=False,
               supersede=False, unrequested=None, opener=None, blender=None, run=subprocess.run):
    """Record the caller's equirect, split it into six faces and bind all seven;
    returns the equirect's media id (None with `record_only`). Everything that can
    refuse runs before the record."""
    manifest.require_stage(m, "sky")
    plate_id = _approved_plate(m)
    if not record_only:
        _sky_bind_preconditions(m)
        blender = _blender(SKY_STEP, "sky-faces", "sky-bind", blender)
    req_path, req = _read_request(m, "sky", SKY_STEP, None, unrequested)
    make = _make(m, att, req, req_path, prompt=prompt, render_type=render_type, input_media_ids=input_media_ids,
                 default_prompt=SKY_PROMPT, default_render_type="I2I", default_inputs=(plate_id,))
    bound = (_st(m, "sky").get("media_ids") or {}).get("equirect")
    outcome = request.record_result(m, "sky", "equirect", result, make, stem="sky_equirect", ext=IMAGE_EXT,
                                    check=_check_image, bound_media_id=bound, supersede=supersede, opener=opener)
    rec = _st(m, "sky")["generated"]["equirect"]
    size = rec.get("size_px")
    aspect_2to1 = (abs(size[0] - 2 * size[1]) <= 1) if size else None
    manifest.set_stage(m, "sky", equirect_path=rec["artifact"], equirect_size=size, equirect_aspect_2to1=aspect_2to1)
    if aspect_2to1 is False and outcome != "unchanged":
        manifest.note(m, "biome ingest sky: equirect is not 2:1 (%dx%d); recorded and flagged, not refused"
                         % tuple(size))
    manifest.save(m)
    if record_only:
        return None
    if outcome == "unchanged" and _st(m, "sky").get("media_id") and not _sky_stale(m):
        return bound
    sky_faces(m, blender=blender)
    return sky_bind(m, run=run)["equirect"]


def _sky_stale(m):
    """True when the bound equirect is not the recorded one."""
    st = _st(m, "sky")
    rec = (st.get("generated") or {}).get("equirect") or {}
    return st.get("bound_sha256") != rec.get("sha256")


def sky_faces(m, blender=None, size=1024):
    """`blender --background --python equirect_to_cube.py -- <equirect> <out>/faces <size>`
    -- six inverse-mapped cubemap face PNGs from the recorded equirect. Local Blender
    computation, not a vendor/Genvid call, so this always runs for real (same as
    mesh.py's facing()/prep()); the pack rule keeping numpy/bpy out of this
    stdlib-only module is why the actual math lives in blender/equirect_to_cube.py."""
    st = _st(m, "sky")
    equirect_path = st.get("equirect_path")
    if not equirect_path or not Path(equirect_path).exists():
        raise ValueError("no stages.sky.equirect_path on the manifest: run `biome ingest sky` before "
                         "`biome sky-faces`")
    out_faces = Path(m["out_dir"]) / "faces"; out_faces.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).parent / "blender" / "equirect_to_cube.py"
    r = subprocess.run([_blender(SKY_STEP, "sky-faces", "sky-bind", blender), "--background", "--python",
                        str(script), "--", equirect_path, str(out_faces), str(size)],
                       capture_output=True, text=True, check=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith("RUNNER_RESULT ")]
    if not lines:
        raise RuntimeError("equirect_to_cube.py printed no result: %s" % (r.stdout[-2000:] or r.stderr[-2000:]))
    rep = json.loads(lines[-1][len("RUNNER_RESULT "):])
    # The faces say which equirect they were split from, so a bind never pairs a
    # new equirect with faces split from an older one.
    manifest.set_stage(m, "sky", faces=dict(rep["faces"]), face_size=size,
                       faces_sha256=request.sha256_of(equirect_path))
    manifest.save(m)
    return rep


def sky_bind(m, run=subprocess.run):
    """Bind the recorded panorama AND the six cubemap faces as `location_image`
    media under the location asset the plate stage created. The equirect attests
    the caller's model from the ingest record and cites the approved plate; each
    face (model_provider "blender") cites the equirect's own media id instead,
    since Blender split it from the panorama, not from the plate -- the provenance
    chain reads plate -> equirect -> face.

    A re-run binds only what is not bound yet. A superseding equirect (ingested
    with --supersede) is bound as a new row naming the one it supersedes, and its
    six faces are bound again from it, each naming the face it supersedes.

    Before any bind, this gates on genvid_bind.ensure_claim (site "biome.sky"):
    once the reviewer approves a plate the task moves to 'approved' and the
    boundary 409s further generation binds until it is reopened; ensure_claim
    reads the task through the genvid CLI, reopens approved/in_review and blocks
    (ClaimPending) until a fresh read shows that reopen has run.

    Every precondition is checked before any governed write; stages.sky.media_id
    is written last, once every face is bound."""
    st = dict(_st(m, "sky"))
    rec = (st.get("generated") or {}).get("equirect")
    if not rec:
        # Checked before the bind preconditions: a manifest the old generator bound
        # may carry no assignee, and a no-op needs none.
        if st.get("media_id"):
            manifest.note(m, "biome sky-bind: the sky is already bound (media %s); nothing changed" % st["media_id"])
            manifest.save(m)
            return _old_sky_ids(st)
        raise ValueError(_old_shape(SKY_STEP, "stages.sky has no generated.equirect: this equirect"))
    _sky_bind_preconditions(m)
    plate_media_id = _approved_plate(m)
    faces = st.get("faces") or {}
    missing = [f for f in SKY_FACES if not (faces.get(f) and Path(faces[f]).exists())]
    if missing:
        raise ValueError("missing face PNG(s) on the manifest: %s -- run `biome sky-faces` before binding"
                         % ", ".join(missing))
    if st.get("faces_sha256") != rec["sha256"]:
        raise ValueError("the faces on the manifest were not split from the recorded equirect: run "
                         "`biome sky-faces` before `biome sky-bind`")
    ids = dict(st.get("media_ids") or {})
    rebind = bool(ids.get("equirect")) and _sky_stale(m)
    if ids.get("equirect") and not rebind and all(ids.get(f) for f in SKY_FACES) and st.get("media_id"):
        manifest.note(m, "biome sky-bind: the recorded equirect and its faces are already bound; nothing changed")
        manifest.save(m)
        return ids

    genvid_bind.ensure_claim(m, m["asset_id"], "biome.sky")

    # The rows a superseding equirect's faces supersede, kept on the stage until
    # every face is bound so a resume after a mid-loop failure still names them.
    superseded = dict(st.get("superseding") or {})
    if not ids.get("equirect") or rebind:
        superseded = {k: v for k, v in ids.items() if v}
        entry = manifest.set_stage(m, "sky", superseding=superseded)
        entry.pop("media_id", None)
        kw = request.bind_kwargs(rec, runner={"stage": "sky-pano", "model_type": "image-to-panorama",
                                              "size_px": rec.get("size_px"),
                                              "aspect_2to1": st.get("equirect_aspect_2to1")})
        if not rec.get("input_media_ids"):
            kw["input_media_ids"] = [plate_media_id]
        ids = {"equirect": genvid_bind.import_media(m["project_id"], link_type="location_image",
                                                    asset_id=m["asset_id"], run=run, **kw)}
        entry = manifest.set_stage(m, "sky", media_ids=dict(ids), bound_sha256=rec["sha256"])
        if superseded:
            entry["superseded_media_ids"] = list(entry.get("superseded_media_ids") or []) + sorted(
                set(superseded.values()))
            manifest.note(m, "biome sky-bind: equirect %s supersedes %s" % (ids["equirect"], superseded["equirect"]))
        manifest.save(m)
    for face in SKY_FACES:
        if ids.get(face):
            continue
        params = {"stage": "sky-face", "face": face}
        if superseded.get(face):
            params["supersedes_media_id"] = str(superseded[face])
        ids[face] = genvid_bind.import_media(m["project_id"], path=faces[face], link_type="location_image",
            asset_id=m["asset_id"], model_provider="blender", model_name="equirect_to_cube", render_type="I2I",
            prompt="cubemap face split of the approved-plate panorama", params=params,
            input_media_ids=[ids["equirect"]], cost=cost.no_vendor_call(), run=run)
        manifest.set_stage(m, "sky", media_ids=dict(ids))
        manifest.save(m)
    # media_id written last, only once every face is bound -- is_done("sky") must
    # not read true (and require_stage let a later stage past it) while faces are
    # still missing after a mid-loop failure.
    entry = manifest.set_stage(m, "sky", media_id=ids["equirect"])
    entry.pop("superseding", None)
    manifest.save(m)
    return ids


def _old_sky_ids(st):
    """What a sky bound by the old generator has bound: its media_ids, or its
    face_media_ids with the equirect's media_id."""
    ids = dict(st.get("face_media_ids") or {})
    ids.update(st.get("media_ids") or {})
    ids.setdefault("equirect", st["media_id"])
    return {k: str(v) for k, v in ids.items()}


def sky_luau(m, ids):
    """Render runner/luau/sky.luau with the six uploaded rbxassetid:// ids (Studio
    `upload_image` results, orchestrator step) and write it under <out>/studio/
    sky.luau -- the same location studio.emit() uses for the character chain's Luau
    steps. Reuses studio.render() (generic {{KEY}} substitution) directly rather
    than studio.emit(), whose defaults (NAME/HEIGHT/MODEL_PATH/...) are character-
    manifest-specific and don't apply to a biome location manifest."""
    missing = [f for f in SKY_FACES if f not in ids]
    if missing:
        raise ValueError("sky_luau needs all six face ids: missing %s" % ", ".join(missing))
    params = {name.upper(): ids[name] for name in SKY_FACES}
    src = studio.render("sky", **params)
    d = Path(m["out_dir"]) / "studio"; d.mkdir(parents=True, exist_ok=True)
    p = d / "sky.luau"; p.write_text(src)
    return p


# ---------------------------------------------------------------- kit sheet

def _kit_grid(props, rows, cols):
    props = [str(p).strip() for p in props or () if str(p).strip()]
    if len(props) != rows * cols:
        raise request.IngestError("the kit sheet needs exactly rows*cols=%d props, got %d"
                                  % (rows * cols, len(props)))
    return props


def emit_kit_sheet(m, estimate, props=None, rows=KIT_ROWS_DEFAULT, cols=KIT_COLS_DEFAULT, model=None,
                   no_urls=False, run=subprocess.run):
    """Write the prop-sheet request (image-to-image, the approved plate as the
    style reference) and return its path. `props` defaults to the design
    document's kit; the grid is recorded on the request, where ingest reads it."""
    manifest.require_stage(m, "kit")
    plate_id = _approved_plate(m)
    props = _kit_grid(props if props is not None else design.kit_props(m), rows, cols)
    entry = budget.gate(m, KIT_BUDGET, estimate, model=model, items=["sheet"])
    ins = request.inputs(m, [("style-reference", plate_id)], no_urls=no_urls, run=run)
    return request.write_request(
        m, "kit", KIT_SHEET_STEP, None, model_type="image-to-image", render_type="I2I",
        prompt=KIT_PROMPT(props, rows, cols), inputs=ins,
        target={"format": ["png"], "aspect": "%d:%d" % (cols, rows), "grid": {"rows": rows, "cols": cols}},
        must_satisfy=["a %d-column by %d-row grid of equal tiles, one prop per tile, in the order the prompt lists "
                      "them, row by row" % (cols, rows),
                      "each prop alone on a flat neutral gray tile, three-quarter front view, no text",
                      "the painting style and palette of the style reference"],
        checked_at_ingest=[IMAGE_CHECKED, REQUESTED_CHECKED],
        budget_entry=entry, ingest=request.ingest_command(m, GROUP, KIT_SHEET_STEP),
        extra={"props": props, "rows": rows, "cols": cols})


def _kit_bind_preconditions(m):
    if not m.get("asset_id"):
        raise ValueError("no asset_id on the manifest: run `biome bind` (plate stage) first")
    _approved_plate(m)
    # Checked before any governed write (the reopen, the sheet/tile imports, and --
    # the site that most easily goes unclaimed -- the per-prop create_assignment
    # claims after create_assets).
    genvid_bind.require_assignee(m)
    if not (_st(m, "kit").get("props") or {}):
        # A fresh batch creates prop assets whose descriptions carry the
        # production's own title. A re-run that reuses existing props creates nothing.
        manifest.production_title(m)


def ingest_kit_sheet(m, result, att, *, props=None, rows=None, cols=None, prompt=None, render_type=None,
                     input_media_ids=(), record_only=False, supersede=False, unrequested=None, opener=None,
                     blender=None, run=subprocess.run):
    """Record the caller's prop sheet, split it into tiles, bind the sheet and the
    tiles and create one asset per prop; returns the sheet's media id (None with
    `record_only`). The props and grid come from the emitted request; an
    --unrequested ingest names them itself."""
    manifest.require_stage(m, "kit")
    plate_id = _approved_plate(m)
    req_path, req = _read_request(m, "kit", KIT_SHEET_STEP, None, unrequested)
    rows = rows if rows is not None else req.get("rows")
    cols = cols if cols is not None else req.get("cols")
    props = props if props is not None else req.get("props")
    if rows is None or cols is None or props is None:
        raise request.IngestError("no kit grid: an unrequested kit sheet needs --props, --rows and --cols")
    props = _kit_grid(props, int(rows), int(cols))
    rows, cols = int(rows), int(cols)
    existing = _st(m, "kit").get("props") or {}
    if existing and [existing[k]["name"] for k in sorted(existing)] != props:
        raise request.IngestError("the kit's prop assets already exist for %s; a sheet for other props needs its "
                                  "own manifest" % ", ".join(existing[k]["name"] for k in sorted(existing)))
    if not record_only:
        _kit_bind_preconditions(m)
        blender = _blender(KIT_SHEET_STEP, "kit-split", "kit-bind", blender)
    make = _make(m, att, req, req_path, prompt=prompt, render_type=render_type, input_media_ids=input_media_ids,
                 default_prompt=KIT_PROMPT(props, rows, cols), default_render_type="I2I", default_inputs=(plate_id,))
    bound = (_st(m, "kit").get("media_ids") or {}).get("sheet")
    outcome = request.record_result(m, "kit", "sheet", result, make, stem="kit_sheet", ext=IMAGE_EXT,
                                    check=_check_image, bound_media_id=bound, supersede=supersede, opener=opener)
    rec = _st(m, "kit")["generated"]["sheet"]
    manifest.set_stage(m, "kit", sheet_path=rec["artifact"], props_list=props, rows=rows, cols=cols)
    manifest.save(m)
    if record_only:
        return None
    if outcome == "unchanged" and _st(m, "kit").get("media_id") and not _kit_stale(m):
        return bound
    kit_split(m, blender=blender)
    return kit_bind(m, run=run)["sheet"]


def _kit_stale(m):
    st = _st(m, "kit")
    rec = (st.get("generated") or {}).get("sheet") or {}
    return st.get("bound_sha256") != rec.get("sha256")


def kit_split(m, blender=None, rows=None, cols=None):
    """`kit-split --rows 4 --cols 3`: `blender --background --python
    split_sheet.py -- kit_sheet.png out/kit <rows> <cols>` -- writes
    prop_01.png..prop_NN.png (equal-tile crop, row-major). `rows`/`cols` default to
    the grid the ingest recorded on the manifest, falling back to KIT_*_DEFAULT only
    when neither is known -- an explicit override always wins.
    Local Blender computation, not a vendor/Genvid call, so this always runs for real
    (same as sky_faces())."""
    st = _st(m, "kit")
    sheet_path = st.get("sheet_path")
    if not sheet_path or not Path(sheet_path).exists():
        raise ValueError("no stages.kit.sheet_path on the manifest: run `biome ingest kit-sheet` before "
                         "`biome kit-split`")
    rows = rows if rows is not None else st.get("rows", KIT_ROWS_DEFAULT)
    cols = cols if cols is not None else st.get("cols", KIT_COLS_DEFAULT)
    out_kit = Path(m["out_dir"]) / "kit"; out_kit.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).parent / "blender" / "split_sheet.py"
    r = subprocess.run([_blender(KIT_SHEET_STEP, "kit-split", "kit-bind", blender), "--background", "--python",
                        str(script), "--", sheet_path, str(out_kit), str(rows), str(cols)],
                       capture_output=True, text=True, check=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith("RUNNER_RESULT ")]
    if not lines:
        raise RuntimeError("split_sheet.py printed no result: %s" % (r.stdout[-2000:] or r.stderr[-2000:]))
    rep = json.loads(lines[-1][len("RUNNER_RESULT "):])
    manifest.set_stage(m, "kit", tiles=dict(rep["tiles"]), tiles_sha256=request.sha256_of(sheet_path))
    manifest.save(m)
    return rep


def kit_bind(m, run=subprocess.run):
    """Sheet + tiles as `location_image` on the location asset (params.runner.stage=
    "kit"). The sheet attests the caller's model from the ingest record and cites
    the approved plate; each tile (model_provider "blender") cites the SHEET's own
    media id instead, since Blender cropped it from the sheet -- the provenance
    chain reads plate -> sheet -> tile. The tile crops are a local Blender split,
    not a separate vendor spend, so they bind at no vendor cost the same way
    sky_bind()'s six faces do.
    Then one `set_dressing` (or `greenery`, per _kit_vocab) asset PER PROP,
    created with a single batch `create-assets` call, each immediately claimed
    with its own genvid_bind.claim_assignment call: a batch `create_assets` with
    no `create_assignment` after it leaves every new prop asset assigned to
    nobody. Records stages.kit.props[<n>] = {name, asset_type, asset_id,
    tile_media_id, model_link_type, model_media_id: null}.

    Before any bind, this gates on genvid_bind.ensure_claim (site "biome.kit")
    the same way sky_bind() does. The per-prop create_assignment claims below
    deliberately do NOT pre-seed the "biome.kit_model" claim cache for their
    props: the reviewer normally approves each tile image between kit_bind() and
    the model bind, so a seeded in_progress would be exactly the stale cache that
    409s the model bind.

    A re-run binds only what is not bound yet, and create-assets fires only once:
    a re-run with stages.kit.props already recorded reuses that map (asset ids and
    any model_media_id already filled in). A superseding sheet (ingested with
    --supersede) binds a new sheet row and new tile rows, each naming the row it
    supersedes, and points the existing props at the new tiles.
    stages.kit.media_id is written LAST, so a mid-loop failure leaves the kit stage
    not done and a re-run of `biome kit-bind` is the recovery path."""
    st = dict(_st(m, "kit"))
    rec = (st.get("generated") or {}).get("sheet")
    if not rec:
        # Checked before the bind preconditions: a manifest the old generator bound
        # may carry no assignee, and a no-op needs none.
        if st.get("media_id"):
            manifest.note(m, "biome kit-bind: the kit is already bound (media %s); nothing changed" % st["media_id"])
            manifest.save(m)
            return _old_kit_ids(st)
        raise ValueError(_old_shape(KIT_SHEET_STEP, "stages.kit has no generated.sheet: this sheet"))
    _kit_bind_preconditions(m)
    plate_media_id = _approved_plate(m)
    props = st.get("props_list") or []
    tiles = st.get("tiles") or {}
    keys = sorted(tiles)  # "01".."NN", row-major -- same order as props_list
    if len(keys) != len(props):
        raise ValueError("stages.kit.tiles (%d) does not match stages.kit.props_list (%d): "
                         "run `biome kit-split` before `biome kit-bind`" % (len(keys), len(props)))
    missing = [k for k in keys if not Path(tiles[k]).exists()]
    if missing:
        raise ValueError("missing tile file(s) on disk: %s -- run `biome kit-split` before `biome kit-bind`"
                         % ", ".join(missing))
    if st.get("tiles_sha256") != rec["sha256"]:
        raise ValueError("the tiles on the manifest were not split from the recorded sheet: run `biome kit-split` "
                         "before `biome kit-bind`")
    ids = dict(st.get("media_ids") or {})
    rebind = bool(ids.get("sheet")) and _kit_stale(m)
    done = ids.get("sheet") and not rebind and all(ids.get(k) for k in keys)
    if done and st.get("props") and st.get("media_id"):
        manifest.note(m, "biome kit-bind: the recorded sheet, its tiles and the prop assets are already bound; "
                         "nothing changed")
        manifest.save(m)
        return ids

    genvid_bind.ensure_claim(m, m["asset_id"], "biome.kit")

    rows = st.get("rows", KIT_ROWS_DEFAULT)
    cols = st.get("cols", KIT_COLS_DEFAULT)
    # The rows a superseding sheet's tiles supersede, kept on the stage until every
    # tile is bound so a resume after a mid-loop failure still names them.
    superseded = dict(st.get("superseding") or {})
    if not ids.get("sheet") or rebind:
        superseded = {k: v for k, v in ids.items() if v}
        entry = manifest.set_stage(m, "kit", superseding=superseded)
        entry.pop("media_id", None)
        kw = request.bind_kwargs(rec, runner={"stage": "kit", "rows": rows, "cols": cols, "props": list(props),
                                              "size_px": rec.get("size_px")})
        if not rec.get("input_media_ids"):
            kw["input_media_ids"] = [plate_media_id]
        ids = {"sheet": genvid_bind.import_media(m["project_id"], link_type="location_image",
                                                 asset_id=m["asset_id"], run=run, **kw)}
        entry = manifest.set_stage(m, "kit", media_ids=dict(ids), bound_sha256=rec["sha256"])
        if superseded:
            entry["superseded_media_ids"] = list(entry.get("superseded_media_ids") or []) + sorted(
                set(superseded.values()))
            manifest.note(m, "biome kit-bind: sheet %s supersedes %s" % (ids["sheet"], superseded["sheet"]))
        manifest.save(m)
    for k in keys:
        if ids.get(k):
            continue
        params = {"stage": "kit", "tile": k}
        if superseded.get(k):
            params["supersedes_media_id"] = str(superseded[k])
        ids[k] = genvid_bind.import_media(m["project_id"], path=tiles[k], link_type="location_image",
            asset_id=m["asset_id"], model_provider="blender", model_name="split_sheet", render_type="I2I",
            prompt="kit sheet tile crop", params=params, input_media_ids=[ids["sheet"]],
            cost=cost.no_vendor_call(), run=run)
        manifest.set_stage(m, "kit", media_ids=dict(ids))
        manifest.save(m)

    existing_props = st.get("props") or {}
    if existing_props:
        # Reuse the recorded props untouched (asset ids, any model bind), pointing
        # each at the tile it now has.
        props_out = {k: dict(v, tile_media_id=ids.get(k, v.get("tile_media_id"))) for k, v in existing_props.items()}
        manifest.set_stage(m, "kit", props=props_out)
        manifest.save(m)
    else:
        vocab = [_kit_vocab(m, name) for name in props]
        title = manifest.production_title(m)
        items = [{"name": name, "asset_type": asset_type,
                  "description": "%s kit prop: %s (%s biome)" % (title, name, m.get("biome", m["name"]))}
                 for name, (asset_type, _) in zip(props, vocab)]
        asset_ids = genvid_bind.create_assets(m["project_id"], items, run=run)
        # One claim per newly created prop asset, immediately after the batch create:
        # the batch create has no per-asset claim of its own.
        for aid in asset_ids:
            genvid_bind.claim_assignment(m, aid)
        props_out = {}
        for k, name, (asset_type, model_link), aid in zip(keys, props, vocab, asset_ids):
            props_out[k] = {"name": name, "asset_type": asset_type, "asset_id": aid,
                            "tile_media_id": ids[k], "model_link_type": model_link, "model_media_id": None}
        manifest.set_stage(m, "kit", props=props_out)
        manifest.save(m)
    entry = manifest.set_stage(m, "kit", media_id=ids["sheet"])
    entry.pop("superseding", None)
    manifest.save(m)
    return ids


def _old_kit_ids(st):
    """What a kit bound by the old generator has bound: its media_ids, or the
    sheet's media_id with each prop's tile row."""
    ids = {k: (v.get("tile_media_id") or v.get("media_id")) for k, v in (st.get("props") or {}).items()
           if isinstance(v, dict) and (v.get("tile_media_id") or v.get("media_id"))}
    ids.update(st.get("media_ids") or {})
    ids.setdefault("sheet", st["media_id"])
    return {k: str(v) for k, v in ids.items()}


# ---------------------------------------------------------------- kit models

# What a prop entry needs before a model can be requested or bound for it. A prop
# recorded by the old generator (a tile `media_id`, no `tile_media_id` or
# `model_link_type`) lacks them and is refused by name; nothing migrates it.
PROP_FIELDS = ("name", "asset_id", "tile_media_id", "model_link_type")


def _prop(m, key, complete=False):
    props = _st(m, "kit").get("props") or {}
    entry = props.get(str(key))
    if not entry:
        raise ValueError("no stages.kit.props[%r] on the manifest: run `biome kit-bind` first" % (key,))
    missing = [f for f in PROP_FIELDS if not entry.get(f)] if complete else []
    if missing:
        raise ValueError("stages.kit.props[%r] has no %s: it was recorded by the old generator, and a model "
                         "cannot be requested or bound for it here" % (key, ", ".join(missing)))
    return entry


def _kit_model_ingest_command(m, key):
    return " ".join(["runner", GROUP, "ingest", KIT_MODEL_STEP, "--prop", key, "--manifest",
                     str(manifest.path_for(m)), "--provider <provider> --model <model>",
                     "--cost <amount> | --cost-unobserved", "<file-or-url> | --roblox-asset-id <id>"])


def emit_kit_model(m, props, estimate, model=None, no_urls=False, triangles_max=None, run=subprocess.run):
    """Write one image-to-3D request per prop (its tile as the input) behind one
    budget check for the set; returns the request paths."""
    if not _st(m, "kit").get("media_id"):
        raise request.IngestError("the kit is not bound: run `biome ingest kit-sheet` (or `biome kit-bind`) first")
    keys = sorted(dict.fromkeys(str(k) for k in props or ()))
    if not keys:
        raise request.IngestError("name at least one --prop")
    entries = {k: _prop(m, k, complete=True) for k in keys}
    if triangles_max is not None and int(triangles_max) <= 0:
        raise request.IngestError("--triangles-max must be a positive number")
    entry = budget.gate(m, KIT_MODEL_BUDGET, estimate, model=model, items=keys)
    ins = request.inputs(m, [("tile", entries[k]["tile_media_id"]) for k in keys], no_urls=no_urls, run=run)
    target = {"format": list(MODEL_KINDS), "preferred": "glb", "or": "a published Roblox asset id "
              "(`biome ingest kit-model --roblox-asset-id`) when the model exists only on the platform"}
    if triangles_max is not None:
        target["triangles_max"] = int(triangles_max)
        target["triangles_note"] = "stated for the model; the ingest does not measure it"
    paths = []
    for k, tile in zip(keys, ins):
        ingest = _kit_model_ingest_command(m, k)
        paths.append(request.write_request(
            m, "kit", KIT_MODEL_STEP, k, model_type="image-to-3D", render_type="I23D",
            prompt=KIT_MODEL_PROMPT(entries[k]["name"]), inputs=[tile], target=target,
            must_satisfy=["a single textured model of the prop in the tile image, as one object",
                          "the tile's shape, colors and painting style",
                          "delivered as GLB (preferred), binary FBX with its textures embedded, or OBJ"],
            checked_at_ingest=["model type by content: GLB, binary FBX (7.1 or later) or OBJ", REQUESTED_CHECKED],
            budget_entry=entry, ingest=ingest,
            extra={"prop": k, "name": entries[k]["name"], "budget_note": KIT_MODEL_BUDGET_NOTE}))
    return paths


def _prop_generated(m, key):
    """The prop's own record container, stages.kit.props.<key>.generated."""
    return m["stages"]["kit"]["props"][str(key)].setdefault("generated", {})


def ingest_kit_model(m, key, result, att, *, roblox_asset_id=None, mesh_id=None, texture_id=None, prompt=None,
                     render_type=None, input_media_ids=(), record_only=False, supersede=False, unrequested=None,
                     opener=None, run=subprocess.run):
    """Record the caller's model for prop `key` at stages.kit.props.<key>.generated.model
    and bind it. A file (GLB, binary FBX or OBJ) is bound as delivered at the prop's
    own model link type; a Roblox asset id with no file is registered at the
    platform tier (payloads the orchestrator runs, then `biome
    kit-model-registered`). Returns the model's media id (None for the platform
    path, and with `record_only`)."""
    key = str(key)
    entry = _prop(m, key, complete=True)
    if (result is None) == (roblox_asset_id is None):
        raise request.IngestError("give exactly one of a result file or URL and --roblox-asset-id")
    if not record_only:
        genvid_bind.require_assignee(m)
    req_path, req = _read_request(m, "kit", KIT_MODEL_STEP, key, unrequested, emit_args="--prop %s" % key)
    fields = _record_kwargs(m, att, req, req_path, prompt=prompt, render_type=render_type,
                            input_media_ids=input_media_ids, default_prompt=KIT_MODEL_PROMPT(entry["name"]),
                            default_render_type="I23D", default_inputs=(entry["tile_media_id"],))
    bound = entry.get("model_media_id")
    if result is not None:
        outcome = request.record_result(
            m, "kit", "model", result, lambda path, url, _kind: request.make_record(artifact=path, source_url=url,
                                                                                     **fields),
            stem="prop_%s.model" % key, ext=MODEL_EXT, check=mesh._check_model_kind, bound_media_id=bound,
            supersede=supersede, opener=opener, container=_prop_generated(m, key))
    else:
        outcome = _record_platform_model(m, key, fields, roblox_asset_id, mesh_id, texture_id, supersede)
    if record_only:
        return None
    if outcome == "unchanged" and not _model_needs_bind(m, key):
        return _prop(m, key).get("model_media_id")
    return kit_model_bind(m, key, run=run)


def _record_platform_model(m, key, fields, roblox_asset_id, mesh_id, texture_id, supersede):
    """The record for a model that exists only as a Roblox asset id: the
    attestation with no artifact. The same id again changes nothing; another id
    over a bound or registered model needs `supersede`, and names what it supersedes."""
    roblox_asset_id = str(roblox_asset_id).strip()
    if not roblox_asset_id:
        raise request.IngestError("--roblox-asset-id must be a non-empty id")
    if fields["render_type"] not in request.RENDER_TYPES:
        raise request.IngestError("render type %r is not one of %s"
                                  % (fields["render_type"], ", ".join(request.RENDER_TYPES)))
    box = _prop_generated(m, key)
    prior = box.get("model")
    if prior and prior.get("roblox_asset_id") == roblox_asset_id:
        manifest.note(m, "ingest %s: Roblox asset %s is already recorded; nothing changed" % (key, roblox_asset_id))
        manifest.save(m)
        return "unchanged"
    entry = _prop(m, key)
    held = entry.get("model_media_id") or (entry.get("registration") or {}).get("media_id")
    if (held or entry.get("registration")) and not supersede:
        raise request.IngestError("prop %s already has a model (%s): pass --supersede to record the new one as a "
                                  "new row that supersedes it" % (key, held or "registration payloads written"))
    att = fields["attestation"]
    rec = {"artifact": None, "source_url": None, "sha256": None, "mime": None, "size_px": None,
           "roblox_asset_id": roblox_asset_id, "mesh_id": mesh_id, "texture_id": texture_id,
           "model_provider": att["model_provider"], "model_name": att["model_name"], "params": dict(att["params"]),
           "prompt": fields["prompt"], "render_type": fields["render_type"],
           "input_media_ids": [str(i) for i in fields["input_media_ids"]], "cost": dict(att["cost"]),
           "request": str(fields["request_path"]) if fields["request_path"] else None,
           "vendor_hint": fields["vendor_hint"]}
    if held:
        rec["supersedes_media_id"] = str(held)
    box["model"] = rec
    manifest.save(m)
    return "superseded" if held else ("replaced" if prior else "recorded")


def _model_needs_bind(m, key):
    """True when the recorded model is not what the prop's bound row (or its
    written registration) carries."""
    entry = _prop(m, key)
    rec = (entry.get("generated") or {}).get("model")
    if not rec:
        return False
    if rec.get("roblox_asset_id"):
        return (entry.get("registration") or {}).get("roblox_asset_id") != rec["roblox_asset_id"]
    return not entry.get("model_media_id") or entry.get("bound_sha256") != rec.get("sha256")


def _pending_media_id(register_path):
    """Placeholder for `finalize_media_registration`'s required `media_id` field
    (the PENDING registry row id `register_media`'s own response returns) --
    unknowable here, since this runner never calls that MCP tool itself. Names
    the sibling register payload file so the orchestrator knows exactly which
    response to read the real id from before running finalize."""
    return "PENDING:%s" % register_path.name


def _set_prop(m, key, **fields):
    props = dict(_st(m, "kit").get("props") or {})
    props[key] = dict(props[key], **fields)
    manifest.set_stage(m, "kit", props=props)
    manifest.save(m)
    return props[key]


def kit_model_bind(m, key, run=subprocess.run):
    """Bind prop `key`'s recorded model: the re-run after a ClaimPending or a
    --record-only ingest, and the second half of every ingest.

    - A file: a synchronous `import_media` of the delivered bytes at the prop's own
      model link type (set_dressing_model/greenery_model, or prop_model under the
      manifest's vocab fallback), attesting the record and citing the prop's tile;
      fills model_media_id. A superseding file binds a new row naming the old one.
    - A Roblox asset id with no file: platform-custodied, so the runner writes the
      `register_media` / `finalize_media_registration` payloads (the shape
      clips.bind() writes) with `generation` taken from the record, and the
      orchestrator runs them; `biome kit-model-registered` then records the
      finalized media id. No target/stage: the boundary's target vocabulary has
      no prop stage, and a pair it does not know is refused.

    Gates on genvid_bind.ensure_claim (site "biome.kit_model", keyed per prop
    asset) first: by now the reviewer has usually approved the prop's tile image,
    which moves its assetImage task to 'approved', and the boundary answers 409
    to the model bind until the task is reopened. A manifest whose props were
    never claimed is claimed the same way.

    Known limit: a prop whose platform registration payloads were written and
    that is then ingested as a file binds the file, but the written payloads stay
    on disk and `registration` stays on the prop; the orchestrator must not run
    them afterwards."""
    key = str(key)
    entry = _prop(m, key)
    rec = (entry.get("generated") or {}).get("model")
    if not rec:
        if entry.get("model_media_id"):
            manifest.note(m, "biome kit-model-bind: prop %s is already bound (media %s); nothing changed"
                             % (key, entry["model_media_id"]))
            manifest.save(m)
            return entry["model_media_id"]
        raise ValueError(_old_shape(KIT_MODEL_STEP + " --prop %s" % key, "prop %s has no generated.model: its "
                                    "model" % key))
    if not _model_needs_bind(m, key):
        manifest.note(m, "biome kit-model-bind: prop %s's recorded model is already bound; nothing changed" % key)
        manifest.save(m)
        return entry.get("model_media_id")
    entry = _prop(m, key, complete=True)
    genvid_bind.require_assignee(m)
    asset_id = entry["asset_id"]
    link_type = entry["model_link_type"]
    runner = {"stage": "kit-model", "prop": key, "name": entry["name"]}
    genvid_bind.ensure_claim(m, asset_id, "biome.kit_model")

    if rec.get("roblox_asset_id"):
        rid = rec["roblox_asset_id"]
        filename = "prop_%s.obj" % key
        register_path = genvid_bind.mcp_payload("register_media", m["out_dir"], project_id=m["project_id"],
            link_type=link_type, asset_id=asset_id, filename=filename, mime_type="model/obj",
            storage_class="platform", kind="mesh")
        identifiers = [{"identifier_scope": "roblox.com", "identifier_value": "asset_id:%s" % rid}]
        if rec.get("mesh_id"):
            identifiers.append({"identifier_scope": "roblox.com", "identifier_value": "mesh_id:%s" % rec["mesh_id"]})
        if rec.get("texture_id"):
            identifiers.append({"identifier_scope": "roblox.com",
                                "identifier_value": "texture_id:%s" % rec["texture_id"]})
        params = dict(rec.get("params") or {})
        params["runner"] = dict(runner, render_type=rec["render_type"], cost=dict(rec["cost"]),
                                cost_note=FINALIZE_COST_NOTE)
        if rec.get("supersedes_media_id"):
            params["supersedes_media_id"] = rec["supersedes_media_id"]
        generation = {"provider": rec["model_provider"], "model": rec["model_name"], "prompt": rec.get("prompt") or "",
                      "params": params}
        # No target/stage: the target vocabulary seeds no prop stage, and the
        # boundary refuses a target/stage pair it does not know.
        finalize_path = genvid_bind.mcp_payload("finalize_media_registration", m["out_dir"],
            project_id=m["project_id"], media_id=_pending_media_id(register_path), link_type=link_type,
            asset_id=asset_id, filename=filename, mime_type="model/obj", locator="rbxassetid://%s" % rid,
            locator_type="platform_asset", storage_class="platform", identifiers=identifiers,
            generation=generation, input_media_ids=list(rec.get("input_media_ids") or []))
        _set_prop(m, key, registration={"state": "payload_written", "roblox_asset_id": rid,
                                        "register_payload": str(register_path),
                                        "finalize_payload": str(finalize_path)})
        manifest.note(m, "biome kit-model-bind: %s registered at platform tier (rbxassetid %s); payloads written "
                         "(%s, %s), awaiting the orchestrator's register_media + finalize_media_registration calls "
                         "and `biome kit-model-registered --prop %s --media-id <id>`"
                         % (key, rid, register_path.name, finalize_path.name, key))
        manifest.save(m)
        return None

    kw = request.bind_kwargs(rec, runner=dict(runner, kind=request.sniff(rec["artifact"])))
    prior = entry.get("model_media_id")
    if prior and "supersedes_media_id" not in kw["params"]:
        kw["params"]["supersedes_media_id"] = str(prior)
    mid = genvid_bind.import_media(m["project_id"], link_type=link_type, asset_id=asset_id, run=run, **kw)
    fields = {"model_media_id": mid, "bound_sha256": rec["sha256"]}
    if prior:
        fields["superseded_media_ids"] = list(entry.get("superseded_media_ids") or []) + [str(prior)]
        manifest.note(m, "biome kit-model-bind: prop %s model %s supersedes %s" % (key, mid, prior))
    _set_prop(m, key, **fields)
    return mid


def kit_model_registered(m, key, media_id):
    """Record the finalized Genvid media id of prop `key`'s platform registration,
    once the orchestrator has run the register_media + finalize_media_registration
    payloads `kit_model_bind()` wrote. A local manifest write, no Genvid call."""
    key = str(key)
    entry = _prop(m, key)
    media_id = str(media_id or "").strip()
    if not media_id:
        raise ValueError("--media-id must be a non-empty media id")
    registration = dict(entry.get("registration") or {})
    if not registration:
        raise ValueError("prop %s has no registration payloads on record: run `biome ingest kit-model --prop %s "
                         "--roblox-asset-id <id>` first" % (key, key))
    prior = entry.get("model_media_id")
    registration.update(state="registered", media_id=media_id)
    fields = {"registration": registration, "model_media_id": media_id}
    if prior and prior != media_id:
        fields["superseded_media_ids"] = list(entry.get("superseded_media_ids") or []) + [str(prior)]
    _set_prop(m, key, **fields)
    manifest.note(m, "biome kit-model-registered: prop %s -> Genvid media %s" % (key, media_id))
    manifest.save(m)
    return m


# Derive a title's lighting-preset values from an approved biome plate. Which
# module those values land in is the title's own (design["luau_modules"]["lighting"]);
# the mapping below is the one a production committed by hand in that module's
# preset comment for its first, hand-derived biome:
# colorShiftTop = sky_top, outdoorAmbient = sky_horizon * 0.8 (rounded),
# ambient = shadow. brightness/exposure/clockTime are not derivable from a still
# plate and are seed values a human tunes in Studio; these are just the current
# seed defaults, not a measurement.
LIGHTING_SEED_BRIGHTNESS = 2.44
LIGHTING_SEED_EXPOSURE = 0.08
LIGHTING_SEED_CLOCK = 13.5
LIGHTING_SAMPLE_KEYS = ("sky_top", "sky_horizon", "ground_near", "ground_mid", "shadow")

try:
    from PIL import Image
except ImportError:
    Image = None


def _hex_to_rgb(hexstr):
    """"#RRGGBB" -> (r, g, b) ints. Pure string/int math -- no Pillow, no PNG
    decoding -- so this (and lighting_table(), below) is unit-testable in an
    environment where Pillow is absent."""
    h = hexstr.lstrip("#")
    if len(h) != 6:
        raise ValueError("not a 6-digit hex color: %r" % hexstr)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _scaled_rgb(rgb, factor):
    return tuple(round(c * factor) for c in rgb)


def lighting_table(name, sample, brightness=LIGHTING_SEED_BRIGHTNESS,
                    exposure=LIGHTING_SEED_EXPOSURE, clock_time=LIGHTING_SEED_CLOCK):
    """Render one lighting-preset table entry from a lighting_sample.json-
    shaped dict (sky_top/sky_horizon/shadow hex strings -- ground_near/ground_mid are
    recorded on the sample but play no part in this mapping, same as the committed
    hand-derived preset). Pure Python: no file I/O, no Pillow, so this is the half of
    `lighting()` a test can exercise without a real PNG or Pillow installed."""
    for key in ("sky_top", "sky_horizon", "shadow"):
        if key not in sample:
            raise ValueError("lighting sample is missing %r: %s" % (key, sorted(sample)))
    top = _hex_to_rgb(sample["sky_top"])
    horizon = _hex_to_rgb(sample["sky_horizon"])
    ambient = _hex_to_rgb(sample["shadow"])
    outdoor = _scaled_rgb(horizon, 0.8)
    title = name[:1].upper() + name[1:] if name else name
    lines = [
        "%s = {" % title,
        "\tambient = { %d, %d, %d }, -- plate shadow" % ambient,
        "\toutdoorAmbient = { %d, %d, %d }, -- plate sky_horizon * 0.8" % outdoor,
        "\tcolorShiftTop = { %d, %d, %d }, -- plate sky_top" % top,
        "\tbrightness = %s, -- seed value, not derivable from a still plate" % brightness,
        "\texposure = %s, -- seed value, not derivable from a still plate" % exposure,
        "\tclockTime = %s, -- seed value, not derivable from a still plate" % clock_time,
        "},",
    ]
    return "\n".join(lines)


def sample_plate(path):
    """Sample five representative points from an approved biome plate PNG into the
    lighting_sample.json shape (sky_top/sky_horizon/ground_near/ground_mid/shadow,
    each a "#RRGGBB" string): sky_top near the top-center (clear sky), sky_horizon
    where sky meets ground (~40% down), ground_mid at mid-distance (~70% down),
    ground_near in the foreground (~92% down), and shadow as the darkest pixel in a
    small patch around the ground_near point (a painted establishing shot rarely
    lands a true shadow tone on one exact sample line the way a raytraced render
    would).

    HEURISTIC, not a re-derivation of a prior process: the first sample a production
    committed to lighting_sample.json and its own lighting module was produced by
    hand, not by this function, so there is nothing to reproduce exactly -- this is a
    reasonable first cut a human still eyeballs in Studio (per that module's
    own comment that brightness/exposure/clockTime stay seed values regardless).

    Needs Pillow, which the runner otherwise keeps out of anything but its
    Blender-only modules -- guarded above so importing this module, and testing
    lighting_table(), never requires it."""
    if Image is None:
        raise RuntimeError("sample_plate needs Pillow ('pip install Pillow') to read pixel "
                            "data; lighting_table() itself has no such dependency")
    img = Image.open(path).convert("RGB")
    w, h = img.size

    def px(fx, fy):
        x = min(w - 1, max(0, int(w * fx)))
        y = min(h - 1, max(0, int(h * fy)))
        return img.getpixel((x, y))

    def hexof(rgb):
        return "#%02X%02X%02X" % tuple(rgb)

    patch = [px(0.5 + dx, 0.85 + dy) for dx in (-0.05, 0, 0.05) for dy in (-0.03, 0, 0.03)]
    shadow = min(patch, key=sum)
    return {
        "sky_top": hexof(px(0.5, 0.06)),
        "sky_horizon": hexof(px(0.5, 0.40)),
        "ground_mid": hexof(px(0.5, 0.70)),
        "ground_near": hexof(px(0.5, 0.92)),
        "shadow": hexof(shadow),
    }


def lighting(m, plate_path=None, brightness=LIGHTING_SEED_BRIGHTNESS,
             exposure=LIGHTING_SEED_EXPOSURE, clock_time=LIGHTING_SEED_CLOCK):
    """`biome lighting`. With `plate_path` given: samples that PNG
    (sample_plate(), Pillow-guarded) and writes <out_dir>/lighting_sample.json with
    the five hex keys, same file shape as the hand-derived first sample.
    Without it: reads an existing <out_dir>/lighting_sample.json (written by an
    earlier `biome lighting --plate` run, or by hand) and refuses if none exists.
    Either way, prints (and returns) a Luau preset-table snippet via
    lighting_table(), headed by the name of the module it belongs in
    (design["luau_modules"]["lighting"]) -- this never writes that module itself,
    since the title's repo is not this pack's to edit; a human pastes the snippet
    in."""
    out = Path(m["out_dir"])
    sample_path = out / "lighting_sample.json"
    if plate_path:
        sample = sample_plate(plate_path)
        out.mkdir(parents=True, exist_ok=True)
        sample_path.write_text(json.dumps(sample, indent=2))
    elif sample_path.exists():
        sample = json.loads(sample_path.read_text())
    else:
        raise ValueError("no %s and no --plate given: pass --plate <approved-plate.png> "
                          "to sample it, or run this again once that file exists" % sample_path)
    name = m.get("biome") or m.get("name") or "Biome"
    table = lighting_table(name, sample, brightness=brightness, exposure=exposure, clock_time=clock_time)
    # Say which module the snippet belongs in. The name is the title's, read from its
    # design document -- this pack neither knows it nor writes the file.
    print("-- paste into %s" % design.luau_module(m, "lighting"))
    print(table)
    return table



# ---------------------------------------------------------------- CLI

def _done(_result):
    """CLI commands return an exit code, never the value."""
    return None


def _init_cli(x):
    doc = json.loads(Path(x.design).read_text()) if x.design else None
    m = init(x.biome, x.out, x.project, kind=x.kind, name=x.name, assignee=x.assignee,
             production_title=x.production_title, design_doc=doc)
    print("wrote", manifest.save(m))


def _no_item(x):
    if x.item:
        raise SystemExit("biome %s %s takes no --item" % (x.cmd, x.step))


def _props_arg(x):
    return [p.strip() for p in x.props.split(",") if p.strip()] if x.props else None


def _emit_cli(x):
    m = manifest.load(x.manifest)
    if x.step in (PLATES_STEP, HUD_STEP):
        paths = emit_plates(m, x.estimate, item=x.item, step=x.step, model=x.model, no_urls=x.no_urls)
    elif x.step == SKY_STEP:
        _no_item(x)
        paths = [emit_sky(m, x.estimate, model=x.model, no_urls=x.no_urls)]
    elif x.step == KIT_SHEET_STEP:
        _no_item(x)
        paths = [emit_kit_sheet(m, x.estimate, props=_props_arg(x), rows=x.rows, cols=x.cols, model=x.model,
                                no_urls=x.no_urls)]
    else:
        _no_item(x)
        paths = emit_kit_model(m, x.prop, x.estimate, model=x.model, no_urls=x.no_urls,
                               triangles_max=x.triangles_max)
    for p in paths:
        print(p)


def _ingest_kwargs(x):
    return dict(prompt=x.prompt, render_type=x.render_type, input_media_ids=x.input_media_id,
                record_only=x.record_only, supersede=x.supersede, unrequested=x.unrequested)


def _ingest_cli(x):
    m = manifest.load(x.manifest)
    att = request.attestation_from_args(x)
    if x.step in (PLATES_STEP, HUD_STEP):
        if not x.item:
            raise SystemExit("biome ingest %s needs --item: the candidate this result is for" % x.step)
        ingest_plate(m, x.item, x.result, att, step=x.step, asset_id=x.asset_id, create=x.create_asset,
                     **_ingest_kwargs(x))
    elif x.step == SKY_STEP:
        _no_item(x)
        ingest_sky(m, x.result, att, **_ingest_kwargs(x))
    elif x.step == KIT_SHEET_STEP:
        _no_item(x)
        ingest_kit_sheet(m, x.result, att, props=_props_arg(x), rows=x.rows, cols=x.cols, **_ingest_kwargs(x))
    else:
        _no_item(x)
        ingest_kit_model(m, x.prop, x.result, att, roblox_asset_id=x.roblox_asset_id, mesh_id=x.mesh_id,
                         texture_id=x.texture_id, **_ingest_kwargs(x))


def _lighting_cli(x):
    lighting(manifest.load(x.manifest), plate_path=x.plate, brightness=x.seed_brightness,
             exposure=x.seed_exposure, clock_time=x.seed_clock)


def _emit_parsers(s):
    e = s.add_parser("emit", help="write a generation request for the caller's own model")
    es = e.add_subparsers(dest="step", required=True)
    for step, help_text, item_help in (
            (PLATES_STEP, "text-to-image requests for the location plate candidates",
             "1, 2 or 3; omit for every candidate not yet generated"),
            (HUD_STEP, "text-to-image requests for the HUD variants",
             "pill, chunky or minimal; omit for every variant not yet generated")):
        request.add_emit_args(es.add_parser(step, help=help_text), item_help=item_help)
    request.add_emit_args(es.add_parser(SKY_STEP, help="the image-to-panorama request, from the approved plate"),
                          item_help="not used: the sky is one item")
    ks = request.add_emit_args(es.add_parser(KIT_SHEET_STEP, help="the image-to-image prop sheet request, the "
                                             "approved plate as its style reference"),
                               item_help="not used: the sheet is one item")
    ks.add_argument("--props", default=None, help="comma-separated prop names; defaults to this title's design "
                    "document kit_props")
    ks.add_argument("--rows", type=int, default=KIT_ROWS_DEFAULT)
    ks.add_argument("--cols", type=int, default=KIT_COLS_DEFAULT)
    km = request.add_emit_args(es.add_parser(KIT_MODEL_STEP, help="image-to-3D requests, one per prop tile"),
                               item_help="not used: name props with --prop")
    km.add_argument("--prop", action="append", required=True, help="a stages.kit.props key, e.g. 01 (repeatable)")
    km.add_argument("--triangles-max", type=int, default=None,
                    help="optional triangle budget stated in the request; recorded, not measured at ingest")
    e.set_defaults(func=_emit_cli)


def _ingest_parsers(s):
    i = s.add_parser("ingest", help="record and bind a result the caller generated")
    ist = i.add_subparsers(dest="step", required=True)
    for step, what in ((PLATES_STEP, "1, 2 or 3"), (HUD_STEP, "pill, chunky or minimal")):
        p = request.add_ingest_args(ist.add_parser(step, help="one candidate"), item_help="the candidate: " + what)
        p.add_argument("--asset-id", help="the existing asset the candidates bind onto")
        p.add_argument("--create-asset", action="store_true", help="create the asset (first candidate)")
    request.add_ingest_args(ist.add_parser(SKY_STEP, help="the equirect; splits the faces and binds all seven"),
                            item_help="not used: the sky is one item")
    ks = request.add_ingest_args(ist.add_parser(KIT_SHEET_STEP, help="the prop sheet; splits the tiles, binds "
                                                "them and creates one asset per prop"),
                                 item_help="not used: the sheet is one item")
    ks.add_argument("--props", default=None, help="comma-separated prop names; defaults to the emitted request's "
                    "(required with --unrequested)")
    ks.add_argument("--rows", type=int, default=None, help="defaults to the emitted request's grid")
    ks.add_argument("--cols", type=int, default=None, help="defaults to the emitted request's grid")
    km = request.add_ingest_args(ist.add_parser(KIT_MODEL_STEP, help="one prop's model: a file or URL (GLB, "
                                                "binary FBX or OBJ), or --roblox-asset-id"),
                                 item_help="not used: name the prop with --prop", positional=False)
    km.add_argument("--prop", required=True, help="the stages.kit.props key, e.g. 01")
    km.add_argument("result", nargs="?", help="the model: a local file or an http(s) URL")
    km.add_argument("--roblox-asset-id", help="the published Roblox asset id, when the model exists only there")
    km.add_argument("--mesh-id", default=None, help="MeshPart.MeshId, when known (with --roblox-asset-id)")
    km.add_argument("--texture-id", default=None, help="MeshPart.TextureID, when known (with --roblox-asset-id)")
    i.set_defaults(func=_ingest_cli)


def register(sub):
    p = sub.add_parser("biome"); s = p.add_subparsers(dest="cmd", required=True)

    a = s.add_parser("init", help="create out/<biome>/manifest.json for a location, or --kind hud for the HUD viz-dev asset")
    # No `choices=`: the biome names belong to the title's design document, not to
    # this pack, and the document is not in hand when the parser is built. `init`
    # validates the name against `--design`'s palettes when one is passed, and
    # PLATE_PROMPT raises with the title's own list of names otherwise.
    a.add_argument("--biome", help="a biome name from this title's design document")
    a.add_argument("--design", help="path to this title's design document JSON (palettes, "
                    "hud_tokens, kit_props, style, hud_style, luau_modules -- see "
                    "runner/design.py). Optional here and only here: a per-title skill may "
                    "stamp m['design'] after init instead. Nothing is defaulted either way")
    a.add_argument("--kind", choices=("location", "hud"), default="location")
    a.add_argument("--name")
    a.add_argument("--project", type=int, required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--production-title", required=True, help="the production's own title; written "
                    "verbatim into the description of every asset this chain creates")
    a.add_argument("--assignee", help="email to claim the assetImage task for at every "
                    "bind; required before any bind runs, never defaults to 'me' (that resolves "
                    "to the agent's own MCP session, not the human reviewer)")
    a.set_defaults(func=_init_cli)

    _emit_parsers(s)
    _ingest_parsers(s)

    b = s.add_parser("bind", help="bind every recorded plate candidate not yet bound (the re-run)")
    b.add_argument("--manifest", required=True)
    b.add_argument("--asset-id")
    b.add_argument("--create-asset", action="store_true")
    b.set_defaults(func=lambda x: _done(bind(manifest.load(x.manifest), x.asset_id, x.create_asset)))

    ap = s.add_parser("approved", help="record which bound plate candidate the reviewer approved")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--media-id", required=True)
    ap.set_defaults(func=lambda x: _done(approved(manifest.load(x.manifest), x.media_id)))

    sf = s.add_parser("sky-faces", help="Blender equirect_to_cube: six cubemap face PNGs from the recorded panorama")
    sf.add_argument("--manifest", required=True)
    sf.add_argument("--size", type=int, default=1024)
    sf.set_defaults(func=lambda x: _done(sky_faces(manifest.load(x.manifest), size=x.size)))

    sb = s.add_parser("sky-bind", help="bind the recorded panorama and six faces not yet bound (the re-run)")
    sb.add_argument("--manifest", required=True)
    sb.set_defaults(func=lambda x: _done(sky_bind(manifest.load(x.manifest))))

    kp = s.add_parser("kit-split", help="Blender split_sheet: per-prop PNGs from the recorded kit sheet")
    kp.add_argument("--manifest", required=True)
    kp.add_argument("--rows", type=int, default=None, help="defaults to stages.kit.rows (from the ingest)")
    kp.add_argument("--cols", type=int, default=None, help="defaults to stages.kit.cols (from the ingest)")
    kp.set_defaults(func=lambda x: _done(kit_split(manifest.load(x.manifest), rows=x.rows, cols=x.cols)))

    kb = s.add_parser("kit-bind", help="bind the recorded sheet and tiles not yet bound and create one asset per "
                                       "kit prop (the re-run)")
    kb.add_argument("--manifest", required=True)
    kb.set_defaults(func=lambda x: _done(kit_bind(manifest.load(x.manifest))))

    km = s.add_parser("kit-model-bind", help="bind a prop's recorded model (the re-run)")
    km.add_argument("--manifest", required=True)
    km.add_argument("--prop", required=True, help="stages.kit.props key, e.g. 01")
    km.set_defaults(func=lambda x: _done(kit_model_bind(manifest.load(x.manifest), x.prop)))

    kr = s.add_parser("kit-model-registered", help="record the finalized media id of a prop's platform "
                                                   "registration")
    kr.add_argument("--manifest", required=True)
    kr.add_argument("--prop", required=True, help="stages.kit.props key, e.g. 01")
    kr.add_argument("--media-id", required=True)
    kr.set_defaults(func=lambda x: _done(kit_model_registered(manifest.load(x.manifest), x.prop, x.media_id)))

    lt = s.add_parser("lighting", help="derive this title's lighting-preset values from the "
                       "approved plate; prints a Luau snippet")
    lt.add_argument("--manifest", required=True)
    lt.add_argument("--plate", help="local plate PNG to sample (writes/updates lighting_sample.json); "
                                     "omit to reuse an existing lighting_sample.json")
    lt.add_argument("--seed-brightness", type=float, default=LIGHTING_SEED_BRIGHTNESS)
    lt.add_argument("--seed-exposure", type=float, default=LIGHTING_SEED_EXPOSURE)
    lt.add_argument("--seed-clock", type=float, default=LIGHTING_SEED_CLOCK)
    lt.set_defaults(func=_lighting_cli)
