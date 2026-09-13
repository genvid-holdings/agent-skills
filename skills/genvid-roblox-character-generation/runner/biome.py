"""Biome location plates: three candidate establishing shots -> Genvid `location`
asset -> the reviewer's approval. Also the HUD viz-dev asset: same plate machinery, a shorter
`kind="hud"` manifest, and a `set_dressing`/`set_dressing_image` bind instead of
`location`/`location_image` -- `plate_gen`/`bind` branch on `m["kind"]` rather than
forking a second module.

Reuses plate.py's budget_gate/BudgetError and genvid_bind's create_asset/import_media/
mcp_payload exactly as plate.py does -- nothing here duplicates that machinery. Only
the biome-specific pieces are genuinely new: the establishing-shot prompt (built
from this title's own design document -- runner/design.py; the palettes, HUD
tokens, prop kit and style words all belong to the title and none of them lives
in this pack), a `kind="location"` manifest with its own (shorter)
stage_order (manifest.stages_for() reads `m["stage_order"]` when present), and plate
generation from a text prompt alone (fal-ai/nano-banana-2/edit with no reference
image) rather than plate.py's edit-from-reference four-view sheet.

Generation, binds and the reviewer's plate approval are orchestrator steps: this
module writes and tests the
reproducible path -- it never itself spends a vendor credit or writes to Genvid outside
a test's FakeTransport/fake run. `approved()` is the one exception worth calling out: it
is a pure local manifest write (no Genvid/vendor call) that records which bound
candidate the orchestrator reports the reviewer approved.
"""
import json, shutil, struct, subprocess
from pathlib import Path
import design, manifest, genvid_bind, plate, studio
from vendors import fal, pricing

MODEL = "fal-ai/nano-banana-2"  # text-to-image. Witnessed 2026-09-04: the /edit slug rejects
                                 # image_urls: [] with 422 "At least one image URL is required";
                                 # the kit sheet (an edit of the approved plate) still uses plate.MODEL.
SEEDS = (11, 23, 37)
STAGE_ORDER = ("plate", "sky", "kit", "materials", "record")

# The Sky stage -- fal-ai/hunyuan_world panorama from the approved
# plate, split into six cubemap faces by runner/blender/equirect_to_cube.py, all
# bound as `location_image` under the same location asset the plate stage created.
SKY_MODEL = "fal-ai/hunyuan_world"
SKY_PROMPT = ("seamless 360 panorama of this exact scene, same palette and painting style, "
              "sky above, ground below, no characters, no text")
SKY_FACES = ("ft", "bk", "lf", "rt", "up", "dn")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# The biome palettes are NOT here: which biomes a title has, and the hexes by role
# that condition each one's establishing shot, are that title's own world design.
# They arrive on the manifest as `m["design"]["palettes"]` and are read through
# design.palette() / design.biome_names(), which raise when the document is absent.

# The HUD viz-dev asset. Same `biome` plate machinery as a location
# (plate_gen/bind branch on m["kind"] == "hud"), but a two-stage manifest -- no sky/kit/
# materials, just plate -> record -- and a "set_dressing" asset instead of "location".
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

# The prop kit -- one sheet image (fal-ai/nano-banana-2/edit, approved plate as
# the style reference), split by Blender into per-prop tiles, one
# set_dressing/greenery asset per prop. WHICH props is the title's design decision:
# the list arrives as `m["design"]["kit_props"]` (design.kit_props()) and `--props`
# overrides it per run. Only the sheet GRID has defaults here, because a 3x4 sheet is
# a property of the image, not of anyone's world -- and rows/cols are arguments
# rather than prompt text, so KIT_PROMPT derives the grid size and the prop count
# from whatever `props`/`rows`/`cols` it is actually called with. A title whose kit is
# three props passes its own grid.
KIT_ROWS_DEFAULT = 4
KIT_COLS_DEFAULT = 3
# Interfaces: "one set_dressing (or greenery for plants: names containing
# tree/bush/flower/mushroom/patch/pond) asset per prop".
GREENERY_WORDS = ("tree", "bush", "flower", "mushroom", "patch", "pond")


def KIT_PROMPT(props, rows=KIT_ROWS_DEFAULT, cols=KIT_COLS_DEFAULT):
    return ("a %d×%d grid sheet of %d separate game props in the exact painting "
            "style and palette of the reference, each prop alone on a flat neutral "
            "gray tile, three-quarter front view, readable silhouette, no text; "
            "props: %s" % (cols, rows, len(props), ", ".join(props)))


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
    guessed and nothing is defaulted -- the first stage that needs a design value
    (`biome plate`, `biome hud-plates`, `biome bind`, `biome kit-sheet`,
    `biome lighting`) raises through design.load() naming the missing key.

    `assignee` (see manifest.new's docstring): the reviewer email `bind()`/
    `kit_bind()`/`kit_model_bind()` claim the assetImage task for. No default
    beyond None -- those stages refuse via genvid_bind.require_assignee rather
    than claim for 'me'.

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


def plate_gen(m, t, poll_secs=3):
    """Candidate generation for either manifest kind: a location's three establishing-shot
    seeds against PLATE_PROMPT (11/23/37, keys "1"/"2"/"3", files plate_<i>.png), or
    a HUD's three variant plates against HUD_PROMPT (seeds 5/6/7, keys pill/chunky/minimal,
    files hud_<variant>.png) -- same fal-ai/nano-banana-2/edit text-to-image call (16:9, 2K,
    no reference image), one budget_gate check before any submit, persisted after every
    paid call -- same resume-never-respend shape as plate.sheet(). `biome hud-plates` and
    `biome plate` are both this one function; only the key/seed/prompt/filename source
    differs, picked from `m["kind"]`."""
    is_hud = m.get("kind") == "hud"
    if is_hud:
        keys = list(HUD_VARIANTS)
        seed_of = dict(HUD_SEEDS)
        prompt_of = lambda k: HUD_PROMPT(m, k)
        filename_of = lambda k: "hud_%s.png" % k
        done_note = "biome hud-plates: all three variants already generated; nothing spent"
    else:
        keys = [str(i) for i in range(1, len(SEEDS) + 1)]
        seed_of = {str(i): SEEDS[i - 1] for i in range(1, len(SEEDS) + 1)}
        prompt_of = lambda k: PLATE_PROMPT(m)
        filename_of = lambda k: "plate_%s.png" % k
        done_note = "biome plate: all three candidates already generated; nothing spent"

    out = Path(m["out_dir"]); out.mkdir(parents=True, exist_ok=True)
    st = m["stages"].get("plate", {})
    urls = dict(st.get("urls") or {})
    paths = dict(st.get("paths") or {})
    costs = dict(st.get("cost_usd") or {})
    seeds = dict(st.get("seeds") or {})
    todo = [k for k in keys if not (urls.get(k) and paths.get(k) and Path(paths[k]).exists())]
    if not todo:
        manifest.note(m, done_note)
        manifest.save(m)
        return
    estimated_cost_usd = pricing.estimate_of(MODEL, len(todo))
    plate.budget_gate(m, "plate", estimated_cost_usd)
    # Two passes, not one loop that submits-then-waits per candidate: fal.submit()
    # already persists every request id to the on-disk ledger before returning
    # (vendors/fal.py's _ledger_write_submit), and fal.pending_request_id() already
    # resumes a submitted-but-unfinished job by tag -- so submitting every candidate
    # first and only then waiting on each is just as crash-safe as the old
    # interleaved shape, and N candidates cost one round of generation latency
    # instead of N. Record the ledger path before the first submit.
    manifest.set_stage(m, "plate", ledger_path=manifest.ledger_path(m)); manifest.save(m)
    # Pass 1: submit (or resume) every candidate before waiting on any of them.
    pending = []
    for k in todo:
        seed = seed_of[k]
        tag = "%s:plate:%s" % (m["name"], k)
        rid = fal.pending_request_id(MODEL, tag, t)
        if rid is None:
            prompt = prompt_of(k)
            payload = {"prompt": prompt, "aspect_ratio": "16:9",
                       "resolution": "2K", "seed": seed}
            rid = fal.submit(MODEL, payload, t, tag=tag)
        else:
            manifest.note(m, "biome plate-gen: resuming fal request %s (candidate %s) from the "
                             "ledger; no new submit" % (rid, k))
        pending.append((k, rid, seed))
    manifest.save(m)  # persist any resume notes recorded above
    # Pass 2: wait on each submitted/resumed candidate, in the same order, recording
    # exactly what the old single loop recorded per candidate.
    for k, rid, seed in pending:
        res = fal.wait(MODEL, rid, t, poll_secs=poll_secs)
        url = res["images"][0]["url"]
        dest = out / filename_of(k)
        t.download(url, dest)
        urls[k] = url; paths[k] = str(dest); costs[k] = pricing.cost_of(MODEL, res)
        seeds[k] = seed
        # Persist immediately: each candidate is already charged by this point (same
        # reasoning as plate.sheet()'s per-view save -- a later failure must not lose an
        # already-spent URL).
        manifest.set_stage(m, "plate", urls=dict(urls), paths=dict(paths),
                            cost_usd=dict(costs), seeds=dict(seeds))
        manifest.save(m)


def bind(m, asset_id=None, create=False, run=subprocess.run):
    """`genvid create-assets` if requested, the `production_write` assignment payload
    (assetImage) for the orchestrator to run, then one `import-generated-media` per
    generated candidate with its attested cost. Every precondition is checked before any
    governed write, matching plate.bind()'s validate-then-write order.

    A location manifest (default) creates asset_type="location" and imports with
    link_type="location_image". A HUD manifest (`m["kind"] == "hud"`) creates
    asset_type="set_dressing" and imports with link_type="set_dressing_image",
    params={"stage": "hud-vizdev", "variant": <pill|chunky|minimal>, "tokens": the
    design document's hud_tokens}
    -- the pack rule (prefix = asset type, suffix = media kind) applies identically."""
    is_hud = m.get("kind") == "hud"
    existing = dict(m["stages"].get("plate", {}))
    urls = existing.get("urls") or {}
    if not urls:
        raise ValueError("no plate urls on the manifest: run `biome plate` before `biome bind`")
    cost_usd = existing.get("cost_usd") or {}
    missing = sorted(i for i in urls if i not in cost_usd)
    if missing:
        raise ValueError("no cost_usd recorded for candidate(s) %s: run `biome plate` before binding"
                          % ", ".join(missing))
    if not asset_id and not create and not m.get("asset_id"):
        raise ValueError("no asset_id: pass --asset-id or --create-asset")
    if create:
        # The created asset's description carries the production's own title;
        # checked with the other preconditions, before any governed write.
        manifest.production_title(m)
    # Checked before any governed write below (create_asset, the assetImage
    # assignment, import_media), same as plate.bind()'s own precondition order --
    # a create_asset with nothing claimed after it leaves a real asset
    # assigned to nobody and never in_progress.
    genvid_bind.require_assignee(m)

    asset_type = "set_dressing" if is_hud else "location"
    link_type = "set_dressing_image" if is_hud else "location_image"

    if create:
        title = manifest.production_title(m)
        description = ("%s HUD concept: %s" % (title, m["name"])) if is_hud else \
                      ("%s biome: %s" % (title, m["name"]))
        asset_id = genvid_bind.create_asset(m["project_id"], m["name"], asset_type, description, run=run)
        m["asset_id"] = asset_id
        manifest.save(m)
    if asset_id:
        m["asset_id"] = asset_id
    asset_id = m.get("asset_id")

    if create:
        # Asset created just above in THIS call: no assetImage task can exist on it
        # yet, so the fire-and-forget create_assignment claim is safe.
        genvid_bind.claim_assignment(m, asset_id)
    else:
        # Pre-existing asset (--asset-id, or asset_id already on the manifest from an
        # earlier --create-asset run -- e.g. a re-bind after `biome approved`): the
        # task may be approved, which 409s this bind until it is reopened, and a
        # create_assignment re-claim never reopens it. Gate on ensure_claim.
        genvid_bind.ensure_claim(m, asset_id, "biome.plate")

    seeds = existing.get("seeds") or {}
    ids = dict(existing.get("media_ids") or {})
    for i, url in urls.items():
        if is_hud:
            prompt = HUD_PROMPT(m, i)
            params = {"stage": "hud-vizdev", "variant": i, "tokens": design.hud_tokens(m)}
        else:
            prompt = PLATE_PROMPT(m)
            # The palette recorded on the governed row is the one the prompt above was
            # actually built from -- read from the design document, not from a second
            # copy cached on the manifest, so the two can never disagree.
            params = {"stage": "biome-plate", "seed": seeds.get(i),
                      "palette": design.palette(m, m["biome"])}
        # T2I: nano-banana-2 generates the plate from a text prompt alone, no reference
        # image (biome plate_gen()'s own /edit-slug-rejects-empty-image_urls comment on
        # MODEL, above) -- render_type "image" is not in the boundary's RenderType
        # vocabulary (witnessed 2026-09-04 against the live boundary: T2I/I2I/I23D are).
        ids[i] = genvid_bind.import_media(m["project_id"], source_url=url, link_type=link_type,
            asset_id=asset_id, model_provider="fal", model_name="nano-banana-2", render_type="T2I",
            prompt=prompt, params=params,
            input_media_ids=[], attested_cost_usd=cost_usd[i], run=run)
        manifest.set_stage(m, "plate", media_ids=dict(ids))
        manifest.save(m)
    return ids


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


def _png_size(path):
    """(width, height) read straight from a PNG's IHDR chunk, or None when `path`
    isn't a recognizable PNG -- e.g. http.FakeTransport.download's 4-byte
    placeholder in tests, or a real vendor failure that wrote something else.
    Stdlib-only (struct on the first 24 bytes): PIL/numpy stay Blender-only per
    the runner's own rule."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if len(data) < 24 or data[:8] != _PNG_SIGNATURE or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def sky_pano(m, t, poll_secs=3):
    """fal-ai/hunyuan_world panorama from the approved plate's Genvid signed URL
    (`--image-url`, orchestrator-supplied -- same shape as plate.py's `_sheet`'s
    `--plate-url`: a governed read this stdlib-only module cannot perform itself).
    Gated on the reviewer's plate approval (require_stage), resume-never-respend and
    persist-after-spend (same shape as plate_gen()/plate.sheet()).

    Records the downloaded equirect's actual size and whether it reads 2:1.
    A mirror-pad-in-Blender fallback for a non-2:1 result is NOT built here; a
    failing check is recorded as a note instead of silently accepted, flagged
    for whoever runs the orchestrator step next.
    """
    manifest.require_stage(m, "sky")
    out = Path(m["out_dir"]); out.mkdir(parents=True, exist_ok=True)
    st = m["stages"].get("sky", {})
    dest = out / "sky_equirect.png"
    if st.get("equirect_url") and st.get("equirect_path") and Path(st["equirect_path"]).exists():
        manifest.note(m, "biome sky-pano: equirect already generated; nothing spent")
        manifest.save(m)
        return
    image_url = st.get("image_url")
    if not image_url:
        raise ValueError("no stages.sky.image_url on the manifest: pass --image-url "
                          "(the approved plate's Genvid signed URL)")
    estimated_cost_usd = pricing.estimate_of(SKY_MODEL)
    plate.budget_gate(m, "sky", estimated_cost_usd)
    # Record the ledger path and resume an already-submitted request by
    # tag instead of resubmitting on a re-run after a crash between submit
    # and wait.
    manifest.set_stage(m, "sky", ledger_path=manifest.ledger_path(m)); manifest.save(m)
    payload = {"image_url": image_url, "prompt": SKY_PROMPT}
    tag = "%s:sky_pano" % m["name"]
    rid = fal.pending_request_id(SKY_MODEL, tag, t)
    if rid is None:
        rid = fal.submit(SKY_MODEL, payload, t, tag=tag)
    else:
        manifest.note(m, "biome sky-pano: resuming fal request %s from the ledger; no new submit" % rid)
    res = fal.wait(SKY_MODEL, rid, t, poll_secs=poll_secs)
    # Response key is unverified (assumption): hunyuan_world's queue response
    # shape was not witnessed against the fal MCP. nano-banana-2's
    # plural `images[0]` shape is the one witnessed pattern already in this pack
    # (plate_gen above), so that is read first, falling back to a singular
    # `image` field.
    if "images" in res:
        url = res["images"][0]["url"]
    else:
        url = res["image"]["url"]
    t.download(url, dest)
    cost = pricing.cost_of(SKY_MODEL, res)
    size = _png_size(dest)
    aspect_2to1 = (abs(size[0] - 2 * size[1]) <= 1) if size else None
    manifest.set_stage(m, "sky", equirect_url=url, equirect_path=str(dest), equirect_cost_usd=cost,
                        equirect_size=list(size) if size else None, equirect_aspect_2to1=aspect_2to1)
    if aspect_2to1 is False:
        manifest.note(m, "biome sky-pano: equirect is not 2:1 (%dx%d); mirror-pad in Blender not "
                          "built -- flagged, not silently accepted" % tuple(size))
    manifest.save(m)


def sky_faces(m, blender=None, size=1024):
    """`blender --background --python equirect_to_cube.py -- <equirect> <out>/faces <size>`
    -- six inverse-mapped cubemap face PNGs from the bound equirect. Local Blender
    computation, not a vendor/Genvid call, so this always runs for real (same as
    mesh.py's facing()/prep()); the pack rule keeping numpy/bpy out of this
    stdlib-only module is why the actual math lives in blender/equirect_to_cube.py."""
    st = m["stages"].get("sky", {})
    equirect_path = st.get("equirect_path")
    if not equirect_path or not Path(equirect_path).exists():
        raise ValueError("no stages.sky.equirect_path on the manifest: run `biome sky-pano` before `biome sky-faces`")
    out_faces = Path(m["out_dir"]) / "faces"; out_faces.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).parent / "blender" / "equirect_to_cube.py"
    r = subprocess.run([blender or shutil.which("blender"), "--background", "--python", str(script), "--",
                        equirect_path, str(out_faces), str(size)], capture_output=True, text=True, check=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith("RUNNER_RESULT ")]
    if not lines:
        raise RuntimeError("equirect_to_cube.py printed no result: %s" % (r.stdout[-2000:] or r.stderr[-2000:]))
    rep = json.loads(lines[-1][len("RUNNER_RESULT "):])
    manifest.set_stage(m, "sky", faces=dict(rep["faces"]), face_size=size)
    manifest.save(m)
    return rep


def sky_bind(m, run=subprocess.run):
    """Bind the panorama AND the six cubemap faces as `location_image` media
    under the SAME location asset plate.bind() already created for this manifest;
    the equirect binds the same way as the faces. The
    equirect (render_type I2I) cites the approved plate candidate in
    `input_media_ids`; each face (render_type I2I, model_provider="blender") cites
    the equirect's own media id instead, since Blender split it from the
    panorama, not from the plate -- the provenance chain reads plate -> equirect
    -> face.

    Before any bind, this gates on genvid_bind.ensure_claim (site "biome.sky"):
    once the reviewer approves a plate the task moves to 'approved' and the
    boundary 409s workflow-invalid-state on further generation binds until it
    is reopened. A fire-and-forget reopen followed by the equirect import on
    the very next line loses that race, so this reads the task's status
    through the deferred-read shape
    (ClaimPending until the orchestrator records it), reopens approved/in_review
    and BLOCKS until that reopen has run and its result is recorded on the
    manifest, and is a no-op once the task is known
    in_progress. Same UNVERIFIED-per-method-schema caveat for
    set_assignment_status's parameter shape, now carried by ensure_claim.

    Every precondition is checked before any governed write, matching
    plate.bind()'s and biome.bind()'s validate-then-write order."""
    asset_id = m.get("asset_id")
    if not asset_id:
        raise ValueError("no asset_id on the manifest: run `biome bind` (plate stage) first")
    plate_media_id = (m["stages"].get("plate") or {}).get("media_id")
    if not plate_media_id:
        raise ValueError("no approved plate media_id on the manifest: run `biome approved` first")
    sky_st = dict(m["stages"].get("sky", {}))
    equirect_path = sky_st.get("equirect_path")
    equirect_cost = sky_st.get("equirect_cost_usd")
    if not equirect_path or not Path(equirect_path).exists():
        raise ValueError("no stages.sky.equirect_path on the manifest: run `biome sky-pano` before `biome sky-bind`")
    if not equirect_cost:
        raise ValueError("no stages.sky.equirect_cost_usd recorded: run `biome sky-pano` before binding")
    faces = sky_st.get("faces") or {}
    missing = [f for f in SKY_FACES if not (faces.get(f) and Path(faces[f]).exists())]
    if missing:
        raise ValueError("missing face PNG(s) on the manifest: %s -- run `biome sky-faces` before binding"
                          % ", ".join(missing))

    # Claim-or-reopen the asset's assetImage task BEFORE any bind, and block until
    # it is known in_progress (biome.bind()'s own create_assignment, above, does the
    # claim+start on a fresh asset; once the reviewer approves a plate the task
    # moves to 'approved' and the boundary answers 409 workflow-invalid-state to any
    # further generation bind on this asset until it is reopened). A fire-and-forget
    # reopen payload here would be followed immediately by the synchronous equirect
    # import below, which would still hit the asset while it was 'approved'.
    genvid_bind.ensure_claim(m, asset_id, "biome.sky")

    ids = dict(sky_st.get("media_ids") or {})
    # I2I: hunyuan_world conditions on the approved plate's signed URL (sky_pano()'s
    # own --image-url, above) -- render_type "image" is not in the boundary's
    # RenderType vocabulary (witnessed 2026-09-04; T2I/I2I/I23D are).
    ids["equirect"] = genvid_bind.import_media(m["project_id"], path=equirect_path, link_type="location_image",
        asset_id=asset_id, model_provider="fal", model_name="hunyuan_world", render_type="I2I",
        prompt=SKY_PROMPT, params={"stage": "sky-pano", "endpoint": SKY_MODEL}, input_media_ids=[plate_media_id],
        attested_cost_usd=equirect_cost, run=run)
    manifest.set_stage(m, "sky", media_ids=dict(ids))
    manifest.save(m)
    for face in SKY_FACES:
        # I2I derivation, not "image": each face is a Blender split of the bound
        # equirect, so its true source is the panorama's own media id (just bound
        # above), not the original plate -- the provenance chain reads
        # plate -> equirect -> face, matching how the split actually happened.
        ids[face] = genvid_bind.import_media(m["project_id"], path=faces[face], link_type="location_image",
            asset_id=asset_id, model_provider="blender", model_name="equirect_to_cube", render_type="I2I",
            prompt="cubemap face split of the approved-plate panorama", params={"stage": "sky-face", "face": face},
            input_media_ids=[ids["equirect"]], attested_cost_usd=pricing.NO_VENDOR_CALL, run=run)
        manifest.set_stage(m, "sky", media_ids=dict(ids))
        manifest.save(m)
    # media_id written last, only once every face is bound -- is_done("sky") must
    # not read true (and require_stage let a later stage past it) while faces are
    # still missing after a mid-loop failure.
    manifest.set_stage(m, "sky", media_id=ids["equirect"])
    manifest.save(m)
    return ids


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


def kit_sheet(m, t, props=None, rows=KIT_ROWS_DEFAULT, cols=KIT_COLS_DEFAULT, poll_secs=3):
    """One fal-ai/nano-banana-2/edit call -- the approved plate's Genvid signed
    URL (`--image-url`, orchestrator-supplied, same shape as sky_pano()'s) as the
    style reference, KIT_PROMPT(props, rows, cols) as the prompt -- writes
    kit_sheet.png. Gated on the sky stage being fully bound (STAGE_ORDER), one
    budget_gate check before any submit, resume-never-respend + persist-after-spend
    (same shape as plate_gen()/sky_pano())."""
    manifest.require_stage(m, "kit")
    if len(props) != rows * cols:
        raise ValueError("kit-sheet needs exactly rows*cols=%d props, got %d" % (rows * cols, len(props)))
    out = Path(m["out_dir"]); out.mkdir(parents=True, exist_ok=True)
    st = m["stages"].get("kit", {})
    dest = out / "kit_sheet.png"
    if st.get("sheet_url") and st.get("sheet_path") and Path(st["sheet_path"]).exists():
        manifest.note(m, "biome kit-sheet: sheet already generated; nothing spent")
        manifest.save(m)
        return
    image_url = st.get("image_url")
    if not image_url:
        raise ValueError("no stages.kit.image_url on the manifest: pass --image-url "
                          "(the approved plate's Genvid signed URL)")
    estimated_cost_usd = pricing.estimate_of(MODEL)
    plate.budget_gate(m, "kit", estimated_cost_usd)
    # Record the ledger path and resume an already-submitted request by
    # tag instead of resubmitting on a re-run after a crash between submit
    # and wait.
    manifest.set_stage(m, "kit", ledger_path=manifest.ledger_path(m)); manifest.save(m)
    prompt = KIT_PROMPT(props, rows, cols)
    payload = {"prompt": prompt, "image_urls": [image_url], "aspect_ratio": "3:4", "resolution": "2K"}
    tag = "%s:kit_sheet" % m["name"]
    rid = fal.pending_request_id(MODEL, tag, t)
    if rid is None:
        rid = fal.submit(MODEL, payload, t, tag=tag)
    else:
        manifest.note(m, "biome kit-sheet: resuming fal request %s from the ledger; no new submit" % rid)
    res = fal.wait(MODEL, rid, t, poll_secs=poll_secs)
    url = res["images"][0]["url"]
    t.download(url, dest)
    cost = pricing.cost_of(MODEL, res)
    manifest.set_stage(m, "kit", sheet_url=url, sheet_path=str(dest), cost_usd=cost,
                        props_list=list(props), rows=rows, cols=cols)
    manifest.save(m)


def kit_split(m, blender=None, rows=None, cols=None):
    """`kit-split --rows 4 --cols 3`: `blender --background --python
    split_sheet.py -- kit_sheet.png out/kit <rows> <cols>` -- writes
    prop_01.png..prop_NN.png (equal-tile crop, row-major). `rows`/`cols` default to
    whatever kit_sheet() recorded on the manifest (a three-landmark grid included),
    falling back to KIT_*_DEFAULT only when neither is known -- an
    explicit override always wins, matching the Interfaces line's own literal flags.
    Local Blender computation, not a vendor/Genvid call, so this always runs for real
    (same as sky_faces())."""
    st = m["stages"].get("kit", {})
    sheet_path = st.get("sheet_path")
    if not sheet_path or not Path(sheet_path).exists():
        raise ValueError("no stages.kit.sheet_path on the manifest: run `biome kit-sheet` before `biome kit-split`")
    rows = rows if rows is not None else st.get("rows", KIT_ROWS_DEFAULT)
    cols = cols if cols is not None else st.get("cols", KIT_COLS_DEFAULT)
    out_kit = Path(m["out_dir"]) / "kit"; out_kit.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).parent / "blender" / "split_sheet.py"
    r = subprocess.run([blender or shutil.which("blender"), "--background", "--python", str(script), "--",
                        sheet_path, str(out_kit), str(rows), str(cols)], capture_output=True, text=True, check=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith("RUNNER_RESULT ")]
    if not lines:
        raise RuntimeError("split_sheet.py printed no result: %s" % (r.stdout[-2000:] or r.stderr[-2000:]))
    rep = json.loads(lines[-1][len("RUNNER_RESULT "):])
    manifest.set_stage(m, "kit", tiles=dict(rep["tiles"]))
    manifest.save(m)
    return rep


def kit_bind(m, run=subprocess.run):
    """Sheet + tiles as `location_image` on the location asset (params.stage=
    "kit"). The sheet (render_type I2I) cites the approved plate in
    input_media_ids; each tile (render_type I2I, model_provider="blender") cites
    the SHEET's own media id instead, since Blender cropped it from the sheet,
    not from the plate -- the provenance chain reads plate -> sheet -> tile
    from it. The tile crops are a local Blender split, not a separate vendor
    spend, so they bind at cost "0" the same way sky_bind()'s six faces do.
    Then one `set_dressing` (or `greenery`, per _kit_vocab) asset PER PROP,
    created with a single batch `create-assets` call (genvid_bind.create_assets)
    rather than one call per prop, each immediately claimed with its own
    genvid_bind.claim_assignment call: a batch `create_assets` with no
    `create_assignment` after it leaves every new prop asset assigned to
    nobody. Records stages.kit.props[<n>] = {name,
    asset_type, asset_id, tile_media_id, model_link_type, model_media_id: null}
    -- model_media_id is filled in later, by kit_model_bind(), once the
    orchestrator's Cube/park/mesh_dump pass has produced something to bind.

    Before any bind, this gates on genvid_bind.ensure_claim (site "biome.kit")
    the same way sky_bind() does -- an approved plate 409s further generation
    binds until reopened, and the reopen must have RUN, and its result
    been recorded on the manifest, before the sheet import on the next line --
    not merely been written as a payload. The per-prop
    create_assignment claims below deliberately do NOT pre-seed the
    "biome.kit_model" claim cache for their props: the reviewer normally approves each
    tile image between kit_bind() and kit_model_bind(), so a seeded in_progress
    would be exactly the stale cache that 409s the model bind.

    Every precondition is checked before any governed write, matching
    plate.bind()'s/sky_bind()'s validate-then-write order; stages.kit.media_id is
    written LAST, only once sheet+tiles+assets are all bound, so a mid-loop failure
    leaves is_done(m, "kit") false (sky_bind()'s same discipline). That incompleteness
    makes a re-run of `biome kit-bind` the expected recovery path (note: a re-run
    reads the cached claims["<asset_id>:biome.kit"] status rather than re-listing,
    so if the plate was approved between the runs delete that key first to force a
    fresh read -- ensure_claim's own documented tradeoff) -- so create-assets
    only fires once: a re-run with stages.kit.props already recorded reuses that map
    as-is (asset ids and any model_media_id kit_model_bind() already filled in)
    instead of creating a second duplicate batch and clobbering it, the same
    create-is-a-governed-write-not-a-plain-import treatment bind()'s explicit
    --create-asset flag gives plate asset creation."""
    asset_id = m.get("asset_id")
    if not asset_id:
        raise ValueError("no asset_id on the manifest: run `biome bind` (plate stage) first")
    plate_media_id = (m["stages"].get("plate") or {}).get("media_id")
    if not plate_media_id:
        raise ValueError("no approved plate media_id on the manifest: run `biome approved` first")
    kit_st = dict(m["stages"].get("kit", {}))
    sheet_path = kit_st.get("sheet_path")
    sheet_cost = kit_st.get("cost_usd")
    if not sheet_path or not Path(sheet_path).exists():
        raise ValueError("no stages.kit.sheet_path on the manifest: run `biome kit-sheet` before `biome kit-bind`")
    if not sheet_cost:
        raise ValueError("no stages.kit.cost_usd recorded: run `biome kit-sheet` before binding")
    props = kit_st.get("props_list") or []
    if not props:
        raise ValueError("no stages.kit.props_list on the manifest: run `biome kit-sheet` before `biome kit-bind`")
    tiles = kit_st.get("tiles") or {}
    keys = sorted(tiles)  # "01".."NN", row-major -- same order as props_list
    if len(keys) != len(props):
        raise ValueError("stages.kit.tiles (%d) does not match stages.kit.props_list (%d): "
                          "run `biome kit-split` before `biome kit-bind`" % (len(keys), len(props)))
    missing = [k for k in keys if not Path(tiles[k]).exists()]
    if missing:
        raise ValueError("missing tile file(s) on disk: %s -- run `biome kit-split` before `biome kit-bind`"
                          % ", ".join(missing))
    # Checked before any governed write below (the reopen, the sheet/tile imports,
    # and -- the site that most easily goes unclaimed -- the per-prop
    # create_assignment claims after create_assets): a missing assignee must never
    # let create_assets run and leave the new prop assets unclaimed.
    genvid_bind.require_assignee(m)
    if not (kit_st.get("props") or {}):
        # A fresh batch below creates prop assets whose descriptions carry the
        # production's own title; checked here, before any governed write. A
        # re-run that reuses existing props creates nothing and needs nothing.
        manifest.production_title(m)

    # Claim-or-reopen the location asset's assetImage task BEFORE any bind and block
    # until it is known in_progress -- same reasoning as sky_bind()'s gate, above.
    genvid_bind.ensure_claim(m, asset_id, "biome.kit")

    rows = kit_st.get("rows", KIT_ROWS_DEFAULT)
    cols = kit_st.get("cols", KIT_COLS_DEFAULT)
    ids = dict(kit_st.get("media_ids") or {})
    # I2I: the sheet is an edit conditioned on the approved plate's signed URL
    # (kit_sheet()'s own --image-url, above) -- render_type "image" is not in the
    # boundary's RenderType vocabulary (witnessed 2026-09-04; T2I/I2I/I23D are).
    ids["sheet"] = genvid_bind.import_media(m["project_id"], path=sheet_path, link_type="location_image",
        asset_id=asset_id, model_provider="fal", model_name="nano-banana-2", render_type="I2I",
        prompt=KIT_PROMPT(props, rows, cols), params={"stage": "kit", "rows": rows, "cols": cols},
        input_media_ids=[plate_media_id], attested_cost_usd=sheet_cost, run=run)
    manifest.set_stage(m, "kit", media_ids=dict(ids))
    manifest.save(m)
    for k in keys:
        # I2I derivation, not "image": each tile is a Blender crop of the bound sheet,
        # so its true source is the sheet's own media id (just bound above), not the
        # original plate -- the provenance chain reads plate -> sheet -> tile,
        # matching how the split actually happened.
        ids[k] = genvid_bind.import_media(m["project_id"], path=tiles[k], link_type="location_image",
            asset_id=asset_id, model_provider="blender", model_name="split_sheet", render_type="I2I",
            prompt="kit sheet tile crop", params={"stage": "kit", "tile": k},
            input_media_ids=[ids["sheet"]], attested_cost_usd=pricing.NO_VENDOR_CALL, run=run)
        manifest.set_stage(m, "kit", media_ids=dict(ids))
        manifest.save(m)

    # Recovery-path guard (matches bind()'s treatment of asset creation as a governed
    # write distinct from media import, gated behind its own explicit --create-asset
    # flag): `biome kit-bind` writes stages.kit.media_id LAST, so a mid-loop failure
    # leaves the kit stage not-done and this function invites a re-run. Without this
    # guard a re-run would call genvid_bind.create_assets() again -- a second batch of
    # N duplicate set_dressing/greenery assets -- and then overwrite stages.kit.props
    # with fresh entries whose model_media_id is None, orphaning the first batch and
    # silently discarding any model bind kit_model_bind() already recorded. So: create
    # assets only the first time; on a re-run, reuse the already-recorded props map
    # (asset ids and any model_media_id) untouched.
    existing_props = kit_st.get("props") or {}
    if existing_props:
        props_out = dict(existing_props)
    else:
        vocab = [_kit_vocab(m, name) for name in props]
        title = manifest.production_title(m)
        items = [{"name": name, "asset_type": asset_type,
                  "description": "%s kit prop: %s (%s biome)" % (title, name, m.get("biome", m["name"]))}
                 for name, (asset_type, _) in zip(props, vocab)]
        asset_ids = genvid_bind.create_assets(m["project_id"], items, run=run)
        # Prop assets created by the batch here are easily left unclaimed --
        # assigned to nobody and never in_progress -- because the batch create
        # has no per-asset claim of its own. One claim
        # per newly created prop asset, immediately after the batch create, same
        # create-then-claim order bind()/plate.bind() use for the single-asset
        # case. Only on THIS branch (a fresh batch) -- a re-run that reuses
        # existing_props below claims nothing again for props already claimed here.
        for aid in asset_ids:
            genvid_bind.claim_assignment(m, aid)

        props_out = {}
        for k, name, (asset_type, model_link), aid in zip(keys, props, vocab, asset_ids):
            props_out[k] = {"name": name, "asset_type": asset_type, "asset_id": aid,
                             "tile_media_id": ids[k], "model_link_type": model_link, "model_media_id": None}
        manifest.set_stage(m, "kit", props=props_out)
        manifest.save(m)
    manifest.set_stage(m, "kit", media_id=ids["sheet"])
    manifest.save(m)
    return ids


def _pending_media_id(register_path):
    """Placeholder for `finalize_media_registration`'s required `media_id` field
    (the PENDING registry row id `register_media`'s own response returns) --
    unknowable here, since this runner never calls that MCP tool itself. Names
    the sibling register payload file so the orchestrator knows exactly which
    response to read the real id from before running finalize. Mirrors
    clips.py's `_pending_media_id` -- kept local rather than
    imported, since that name is module-private there too."""
    return "PENDING:%s" % register_path.name


def kit_model_bind(m, key, obj_path=None, roblox_asset_id=None, mesh_id=None, texture_id=None,
                   run=subprocess.run):
    """ORCHESTRATOR STEP for its governed writes (Cube's
    GenerateModelAsync, park_prop.luau, mesh_dump.luau all run in Studio under the
    orchestrator's hand; this only binds whatever that produced, and is never called
    here with a real transport/run). Two shapes:

    - Cube returns a Roblox asset id (`roblox_asset_id`): a platform-custodied
      capture -- the bytes live only as a Roblox asset id -- using the same
      `register_media`/`finalize_media_registration` shape clips.bind() writes
      for its own platform-tier clips:

      - `register_media`: `storage_class="platform"`, `kind="mesh"`
        (MediaKind's real enum -- "animation-clip" | "mesh", witnessed via
        context/api/api-media.yaml -- distinct from clips.py's
        "animation-clip"). No `proxy_filename`: register_media's own schema
        only accepts an image or `.glb`/`.fbx` proxy for a model original,
        and the synthetic `prop_<key>.obj` filename here is neither -- same
        reasoning clips.bind() documents for its `.rbxmx` (also not an
        accepted proxy type).
      - `finalize_media_registration`: `identifiers` is the schema's
        `IdentifierInput` shape (a list of `{identifier_scope,
        identifier_value}` objects), not a bare string list -- SKILL.md 5.1's
        `roblox.com`-scoped `asset_id:` identifier always, plus `mesh_id:`/
        `texture_id:` entries (the same prefixes `capture_ids.luau` captures
        for the character mesh's own "wire" stage) when the caller has them.
        `generation` is a JSON OBJECT (`provider`/`model`/`prompt`/`params`),
        matching the `import_media` call below's own
        `model_provider="roblox-cube"`/`model_name="generate-model-async"`,
        not the old bare `{"source": ..., "prompt": ...}` shape (not a field
        the schema defines at all). `media_id` carries the placeholder
        `_pending_media_id` writes, naming the sibling register payload file
        -- register_media's own response supplies the real id only once the
        orchestrator actually runs that call, same incompleteness clips.
        bind() documents for its own pair. `size_bytes` (schema-required) is
        left for the orchestrator to fill too -- unknowable without reading
        bytes this runner never holds for a platform-tier capture. `stage=
        "roblox/prop-mesh"` is UNVERIFIED against a published
        target_vocabulary (the schema says to check one, and no such check
        ran here), same caveat clips.bind() carries for its own
        `"roblox/keyframesequence"`. stages.kit.props[key].model_media_id is
        left null for that later step.
    - Otherwise (`obj_path`, no rbxassetid): a real, synchronous `import_media`
      upload of the OBJ geometry proxy mesh_dump.luau produced, at the item's own
      model link type (set_dressing_model/greenery_model, or prop_model under the
      manifest's vocab fallback) -- fills model_media_id immediately, the same
      plain-import shape rig.bind()/sky_bind() already use.

    Gates on genvid_bind.ensure_claim (site "biome.kit_model", keyed per prop
    asset) FIRST, ahead of either branch's register/import: kit_bind() already
    claims each prop the moment it creates it, but this is the runner path that
    touches those assets again -- by now the reviewer has usually approved the
    prop's tile image, which moves its assetImage task to 'approved', and the
    boundary answers 409 to the model bind until the task is reopened (witnessed
    2026-09-07). A plain create_assignment re-claim attaches
    to the existing task without reopening it, so it never prevents that 409;
    ensure_claim reads the status, reopens approved/in_review, and blocks until
    the reopen has run and its result is recorded on the manifest. A manifest built before the claim fix (or restored from
    a backup predating it) can still carry props with nothing claimed --
    ensure_claim claims those the same way.
    """
    props = m["stages"].get("kit", {}).get("props") or {}
    entry = props.get(key)
    if not entry:
        raise ValueError("no stages.kit.props[%r] on the manifest: run `biome kit-bind` first" % key)
    if not obj_path and not roblox_asset_id:
        raise ValueError("kit_model_bind needs obj_path or roblox_asset_id")
    if obj_path and not roblox_asset_id and not Path(obj_path).exists():
        # Checked before the claim gate below writes any payload (sky_bind()'s and
        # kit_bind()'s same validate-then-write order).
        raise ValueError("kit_model_bind: obj_path %s does not exist" % obj_path)
    asset_id = entry["asset_id"]
    tile_media_id = entry["tile_media_id"]
    link_type = entry["model_link_type"]
    name = entry["name"]
    prompt = "%s, stylized game prop, single object" % name
    genvid_bind.ensure_claim(m, asset_id, "biome.kit_model")

    if roblox_asset_id:
        filename = "prop_%s.obj" % key
        register_path = genvid_bind.mcp_payload("register_media", m["out_dir"], project_id=m["project_id"],
            link_type=link_type, asset_id=asset_id, filename=filename, mime_type="model/obj",
            storage_class="platform", kind="mesh")
        identifiers = [{"identifier_scope": "roblox.com", "identifier_value": "asset_id:%s" % roblox_asset_id}]
        if mesh_id:
            identifiers.append({"identifier_scope": "roblox.com", "identifier_value": "mesh_id:%s" % mesh_id})
        if texture_id:
            identifiers.append({"identifier_scope": "roblox.com", "identifier_value": "texture_id:%s" % texture_id})
        generation = {"provider": "roblox-cube", "model": "generate-model-async", "prompt": prompt,
                      "params": {"prop": key}}
        genvid_bind.mcp_payload("finalize_media_registration", m["out_dir"], project_id=m["project_id"],
            media_id=_pending_media_id(register_path),
            link_type=link_type, asset_id=asset_id, filename=filename, mime_type="model/obj",
            locator="rbxassetid://%s" % roblox_asset_id, locator_type="platform_asset",
            storage_class="platform", identifiers=identifiers, generation=generation,
            input_media_ids=[tile_media_id], target="roblox", stage="roblox/prop-mesh")
        manifest.note(m, "biome kit-model-bind: %s registered at platform tier (rbxassetid %s); "
                          "model_media_id awaits the orchestrator's finalize response" % (key, roblox_asset_id))
        manifest.save(m)
        return None

    mid = genvid_bind.import_media(m["project_id"], path=obj_path, link_type=link_type,
        asset_id=asset_id, model_provider="roblox-cube", model_name="generate-model-async",
        render_type="I23D", prompt=prompt, params={"stage": "kit-model", "prop": key},
        input_media_ids=[tile_media_id], attested_cost_usd=pricing.NO_VENDOR_CALL, run=run)
    updated = dict(entry); updated["model_media_id"] = mid
    props = dict(props); props[key] = updated
    manifest.set_stage(m, "kit", props=props)
    manifest.save(m)
    return mid


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


def _init_cli(x):
    doc = json.loads(Path(x.design).read_text()) if x.design else None
    m = init(x.biome, x.out, x.project, kind=x.kind, name=x.name, assignee=x.assignee,
             production_title=x.production_title, design_doc=doc)
    print("wrote", manifest.save(m))


def _plate_cli(x):
    m = manifest.load(x.manifest)
    plate_gen(m, fal.transport(ledger_path=manifest.ledger_path(m)))


def _hud_plate_cli(x):
    m = manifest.load(x.manifest)
    plate_gen(m, fal.transport(ledger_path=manifest.ledger_path(m)))


def _bind_cli(x):
    bind(manifest.load(x.manifest), x.asset_id, x.create_asset)


def _approved_cli(x):
    approved(manifest.load(x.manifest), x.media_id)


def _sky_pano_cli(x):
    m = manifest.load(x.manifest)
    if x.image_url:
        manifest.set_stage(m, "sky", image_url=x.image_url)
        manifest.save(m)
    sky_pano(m, fal.transport(ledger_path=manifest.ledger_path(m)))


def _sky_faces_cli(x):
    sky_faces(manifest.load(x.manifest), size=x.size)


def _sky_bind_cli(x):
    sky_bind(manifest.load(x.manifest))


def _kit_sheet_cli(x):
    m = manifest.load(x.manifest)
    if x.image_url:
        manifest.set_stage(m, "kit", image_url=x.image_url)
        manifest.save(m)
    # No --props: the title's own kit, from the manifest's design document. There is
    # no pack-side prop list to fall back to, so design.kit_props() raises instead.
    props = [p.strip() for p in x.props.split(",") if p.strip()] if x.props \
        else list(design.kit_props(m))
    kit_sheet(m, fal.transport(ledger_path=manifest.ledger_path(m)), props, rows=x.rows, cols=x.cols)


def _kit_split_cli(x):
    kit_split(manifest.load(x.manifest), rows=x.rows, cols=x.cols)


def _kit_bind_cli(x):
    kit_bind(manifest.load(x.manifest))


def _kit_model_bind_cli(x):
    kit_model_bind(manifest.load(x.manifest), x.prop, obj_path=x.obj, roblox_asset_id=x.roblox_asset_id,
                   mesh_id=x.mesh_id, texture_id=x.texture_id)


def _lighting_cli(x):
    lighting(manifest.load(x.manifest), plate_path=x.plate, brightness=x.seed_brightness,
             exposure=x.seed_exposure, clock_time=x.seed_clock)


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
                    "downstream bind stage (bind/kit-bind/kit-model-bind); required before "
                    "any of those run, never defaults to 'me' (that resolves to the agent's "
                    "own MCP session, not the human reviewer)")
    a.set_defaults(func=_init_cli)

    g = s.add_parser("plate", help="generate three establishing-shot plate candidates")
    g.add_argument("--manifest", required=True)
    g.set_defaults(func=_plate_cli)

    hp = s.add_parser("hud-plates", help="generate the three HUD variant plate candidates (pill/chunky/minimal)")
    hp.add_argument("--manifest", required=True)
    hp.set_defaults(func=_hud_plate_cli)

    b = s.add_parser("bind", help="create the location/HUD asset and bind the plate candidates")
    b.add_argument("--manifest", required=True)
    b.add_argument("--asset-id")
    b.add_argument("--create-asset", action="store_true")
    b.set_defaults(func=_bind_cli)

    ap = s.add_parser("approved", help="record which bound plate candidate the reviewer approved")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--media-id", required=True)
    ap.set_defaults(func=_approved_cli)

    sp = s.add_parser("sky-pano", help="fal-ai/hunyuan_world panorama from the approved plate")
    sp.add_argument("--manifest", required=True)
    sp.add_argument("--image-url", help="the approved plate's Genvid signed URL (orchestrator-supplied)")
    sp.set_defaults(func=_sky_pano_cli)

    sf = s.add_parser("sky-faces", help="Blender equirect_to_cube: six cubemap face PNGs from the panorama")
    sf.add_argument("--manifest", required=True)
    sf.add_argument("--size", type=int, default=1024)
    sf.set_defaults(func=_sky_faces_cli)

    sb = s.add_parser("sky-bind", help="bind the panorama and six faces as location_image media")
    sb.add_argument("--manifest", required=True)
    sb.set_defaults(func=_sky_bind_cli)

    ks = s.add_parser("kit-sheet", help="fal-ai/nano-banana-2/edit prop kit sheet from the approved plate")
    ks.add_argument("--manifest", required=True)
    ks.add_argument("--image-url", help="the approved plate's Genvid signed URL (orchestrator-supplied)")
    ks.add_argument("--props", default=None, help="comma-separated prop names; defaults to "
                    "this title's design document kit_props")
    ks.add_argument("--rows", type=int, default=KIT_ROWS_DEFAULT)
    ks.add_argument("--cols", type=int, default=KIT_COLS_DEFAULT)
    ks.set_defaults(func=_kit_sheet_cli)

    kp = s.add_parser("kit-split", help="Blender split_sheet: per-prop PNGs from the kit sheet")
    kp.add_argument("--manifest", required=True)
    kp.add_argument("--rows", type=int, default=None, help="defaults to stages.kit.rows (from kit-sheet)")
    kp.add_argument("--cols", type=int, default=None, help="defaults to stages.kit.cols (from kit-sheet)")
    kp.set_defaults(func=_kit_split_cli)

    kb = s.add_parser("kit-bind", help="bind the sheet+tiles and create one asset per kit prop")
    kb.add_argument("--manifest", required=True)
    kb.set_defaults(func=_kit_bind_cli)

    km = s.add_parser("kit-model-bind", help="bind a Cube-generated prop's model (OBJ proxy or published rbxassetid)")
    km.add_argument("--manifest", required=True)
    km.add_argument("--prop", required=True, help="stages.kit.props key, e.g. 01")
    km.add_argument("--obj", help="local OBJ proxy path (mesh_dump.luau output)")
    km.add_argument("--roblox-asset-id", help="published Roblox asset id, when Cube returned one")
    km.add_argument("--mesh-id", default=None, help="MeshPart.MeshId, when capture_ids-style data is known")
    km.add_argument("--texture-id", default=None, help="MeshPart.TextureID, when capture_ids-style data is known")
    km.set_defaults(func=_kit_model_bind_cli)

    lt = s.add_parser("lighting", help="derive this title's lighting-preset values from the "
                       "approved plate; prints a Luau snippet")
    lt.add_argument("--manifest", required=True)
    lt.add_argument("--plate", help="local plate PNG to sample (writes/updates lighting_sample.json); "
                                     "omit to reuse an existing lighting_sample.json")
    lt.add_argument("--seed-brightness", type=float, default=LIGHTING_SEED_BRIGHTNESS)
    lt.add_argument("--seed-exposure", type=float, default=LIGHTING_SEED_EXPOSURE)
    lt.add_argument("--seed-clock", type=float, default=LIGHTING_SEED_CLOCK)
    lt.set_defaults(func=_lighting_cli)
