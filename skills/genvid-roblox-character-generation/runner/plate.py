"""Stage 1: approved plate -> four-view sheet -> Genvid bind under the assetImage assignment."""
import os, re, subprocess
from pathlib import Path
import manifest, genvid_bind
from vendors import fal, pricing

MODEL = "fal-ai/nano-banana-2/edit"
VIEW_WORDS = {"back": "seen directly from behind", "left": "seen from its left side in strict profile",
              "right": "seen from its right side in strict profile"}

class BudgetError(RuntimeError):
    """Raised when a spending stage is refused, or not yet cleared, by the pre-spend
    budget gate (manifest.py has no ManifestError; this is the real exception type)."""
    pass

def SHEET_PROMPT(view):
    return ("Redraw this exact character %s, same design, colors, materials and proportions, same symmetric "
            "A-pose with arms angled away from the torso and a clear gap on both sides, legs apart, feet "
            "shoulder-width, full body head to feet, centered, plain flat neutral gray background, even studio "
            "lighting, no floor shadow, no text." % VIEW_WORDS[view])

def budget_gate(m, stage, estimated_cost_usd):
    """Pre-spend budget gate (pack 0.9.0 Step 0b, mandatory for every spending stage per
    genvid-agent-generation/SKILL.md). `check_generation_budget` is a
    governed MCP read this runner cannot call itself (an orchestrator step); this writes
    the payload for the orchestrator to run and reads back whatever verdict it recorded at
    m["budget"][stage]["fits"]. No vendor call happens until that verdict is `True`.
    """
    budget = m.setdefault("budget", {})
    entry = budget.get(stage)
    if entry is None or "fits" not in entry:
        payload_path = genvid_bind.mcp_payload("check_generation_budget", m["out_dir"],
            project_id=m["project_id"], estimated_cost_usd=estimated_cost_usd, asset_id=m.get("asset_id"))
        budget[stage] = {"estimated_cost_usd": estimated_cost_usd, "payload": str(payload_path)}
        manifest.save(m)
        raise BudgetError(
            "budget check for stage %r not yet recorded: wrote %s for the orchestrator to run; "
            "record its `fits` verdict at budget[%r] before this stage may spend"
            % (stage, payload_path, stage))
    if entry.get("fits") is not True:
        raise BudgetError("budget: %s" % entry.get("refusal", "stage %r has no fits: true verdict" % stage))

def sheet(m, plate_path, t, poll_secs=3):
    out = Path(m["out_dir"]); out.mkdir(parents=True, exist_ok=True)
    # Resume, never re-spend: a view whose URL is already recorded AND whose file is on
    # disk was paid for on an earlier run (each view persists the moment it is charged,
    # below). Re-running `plate sheet` after a mid-loop vendor failure generates only the
    # views still missing, so the manifest's cost_usd stays equal to what fal charged.
    st = m["stages"].get("plate", {})
    urls = dict(st.get("view_urls") or {})
    paths = dict(st.get("view_paths") or {}); paths["front"] = str(plate_path)
    costs = dict(st.get("cost_usd") or {})
    todo = [v for v in ("back", "left", "right")
            if not (urls.get(v) and paths.get(v) and Path(paths[v]).exists())]
    for v in list(urls):
        if v in todo:
            urls.pop(v, None); costs.pop(v, None); paths.pop(v, None)
    if not todo:
        manifest.note(m, "plate sheet: all three views already generated; nothing spent")
        manifest.save(m)
        return
    # One fal-ai/nano-banana-2/edit call per missing view at pricing.PRICES's flat unit price.
    estimated_cost_usd = pricing.estimate_of(MODEL, len(todo))
    budget_gate(m, "plate", estimated_cost_usd)
    plate_url = st.get("plate_url")
    manifest.set_stage(m, "plate", artifact=str(plate_path))
    manifest.save(m)
    for view in todo:
        payload = {"prompt": SHEET_PROMPT(view), "image_urls": [plate_url] if plate_url else [],
                   "resolution": "2K", "aspect_ratio": "3:4", "thinking_level": "high"}
        rid = fal.submit(MODEL, payload, t)
        res = fal.wait(MODEL, rid, t, poll_secs=poll_secs)
        url = res["images"][0]["url"]
        dest = out / ("sheet_%s.png" % view)
        t.download(url, dest)
        urls[view] = url; paths[view] = str(dest); costs[view] = pricing.cost_of(MODEL, res)
        # Each view already spent a fal credit by this point: persist immediately so a
        # timeout or download failure on a later view leaves the already-charged cost and
        # URL for this one recoverable in the manifest, instead of losing it until all
        # three succeed (the same "billable action with nothing persisted to recover it"
        # shape bind() was fixed for -- save after each write).
        manifest.set_stage(m, "plate", view_urls=dict(urls), view_paths=dict(paths), cost_usd=dict(costs))
        manifest.save(m)

def views(m):
    return dict(m["stages"]["plate"]["view_paths"])

# The stated rule eval row E1 reads. check_plate_gaps.py measures the longest
# background run between the legs at seven heights (0.62-0.86 of the image) and
# prints it per row; nothing turned those numbers into a verdict, so E1 was
# structurally PEND on every run (witnessed 2026-09-04 on both bake-off legs).
# 8 px is the stated threshold. Measured against the July
# 50-stud character's plate on 2026-09-04 (its own plate.png in the game repo,
# check_plate_gaps.py rc=0): rows 0.62-0.86 read 5, 25, 2, 1, 2, 0, 6 px, so that
# APPROVED plate does not clear this rule at six of its seven rows. E1 is a
# non-gate row precisely because of that spread -- the number reports, the zoo
# verdict decides -- and the measurement is recorded here rather than left as an
# assumption about what a passing plate looks like.
GAP_MIN_PX = 8
GAPS_RULE = ("every row of the FRONT plate reports a leg gap >= %d px; a row that reports n/a "
             "fails it too (no measurable gap in the band is not a plate with legs apart); side "
             "and back views are exempt, since a strict profile has no leg gap to measure" % GAP_MIN_PX)

# `<path>  (1024x1536)` starts a per-image block; `  0.62    30px` / `  0.66  n/a`
# are its rows. Anything else -- the column header, the `compare` block's
# disagreement lines -- matches neither and is ignored.
_HEADER_RE = re.compile(r"^(?P<path>\S.*?)\s+\(\d+x\d+\)\s*$")
_ROW_RE = re.compile(r"^\s+(?P<frac>\d+\.\d+)\s+(?:(?P<px>\d+)px|n/a)\s*$")


def parse_gaps(stdout):
    """check_plate_gaps.py's report -> {path: [(row_fraction, gap_px or None), ...]}."""
    blocks, cur = {}, None
    for line in (stdout or "").splitlines():
        header = _HEADER_RE.match(line)
        if header:
            cur = header.group("path")
            blocks.setdefault(cur, [])
            continue
        row = _ROW_RE.match(line)
        if row is not None and cur is not None:
            px = row.group("px")
            blocks[cur].append((float(row.group("frac")), int(px) if px is not None else None))
    return blocks


def gaps_verdict(stdout, front_path):
    """(ok, rows, failures) for the front plate under GAPS_RULE.

    `ok` is None when the front plate produced no rows at all -- an honest "not
    measured", which E1 renders PEND. It is never True by default: a plate this
    function could not find in the report has not passed anything.
    """
    blocks = parse_gaps(stdout)
    rows = blocks.get(front_path)
    if rows is None and front_path:
        # The report echoes each path as it was passed on the command line; fall
        # back to the file name so a symlinked or relative invocation still lands.
        name = Path(front_path).name
        for path, r in blocks.items():
            if Path(path).name == name:
                rows = r
                break
    if not rows:
        return None, [], []
    failures = [[frac, px] for frac, px in rows if px is None or px < GAP_MIN_PX]
    return not failures, [[frac, px] for frac, px in rows], failures


def gaps(m):
    script = os.environ.get("PLATE_GAPS_PY")
    if not script:
        manifest.note(m, "plate gaps: PLATE_GAPS_PY unset; not measured"); manifest.save(m); return None
    py = str(Path(script).parent / ".venv" / "bin" / "python")
    r = subprocess.run([py, script] + list(views(m).values()), capture_output=True, text=True)
    # Record returncode and a stderr tail alongside stdout: check_plate_gaps.py prints its
    # report per-path as it goes, so a crash partway through leaves stdout looking like a
    # complete, healthy measurement unless the exit status is captured too. An empty stdout
    # from a wholesale failure must not read as "measured, nothing to flag" either -- both
    # are recorded, and a nonzero exit raises after the partial record is persisted.
    manifest.set_stage(m, "plate", gaps_stdout=r.stdout[-2000:], gaps_returncode=r.returncode,
                        gaps_stderr=r.stderr[-2000:])
    # A partial report from a crashed run cannot carry a verdict: the rule is over
    # EVERY row of the front plate, and a run that died mid-report may simply not
    # have printed the row that would have failed it. gaps_ok stays None there.
    if r.returncode == 0:
        ok, rows, failures = gaps_verdict(r.stdout, views(m).get("front"))
        manifest.set_stage(m, "plate", gaps_ok=ok, gaps_rows=rows, gaps_failures=failures,
                           gaps_rule=GAPS_RULE, gaps_min_px=GAP_MIN_PX)
        if ok is None:
            manifest.note(m, "plate gaps: no rows parsed for the front plate; gaps_ok not measured")
    else:
        manifest.set_stage(m, "plate", gaps_ok=None, gaps_rule=GAPS_RULE, gaps_min_px=GAP_MIN_PX)
    manifest.save(m)
    if r.returncode != 0:
        raise RuntimeError("check_plate_gaps.py exited %d: %s" % (r.returncode, r.stderr[-2000:] or "(no stderr)"))
    return r.stdout

def bind(m, asset_id=None, create=False, only="all", plate_path=None, run=subprocess.run,
         fresh_asset=False):
    # `fresh_asset=True` says the CALLER created `asset_id` moments ago in this same
    # call chain (a per-title static-prop plate bind does, under its own asset description), so no
    # assetImage task can exist on it yet, let alone an approved one: the front bind
    # takes the same fire-and-forget create_assignment claim `create=True` takes,
    # instead of the ensure_claim gate every bind against a PRE-EXISTING asset takes.
    # Never pass it for an asset that already existed before this call.
    # `only` implements a fixed two-call order: the edit
    # model needs a hosted plate URL, which only exists once the front plate is bound and
    # the orchestrator reads its signed URL back out of Genvid. So `--only front` binds
    # just the approved plate (and creates the asset/assignment); the orchestrator then
    # runs `plate sheet --plate-url <that url>`; `--only views` binds the three generated
    # views against the front media id already recorded in the manifest. `--only all`
    # (the default) does both in one call, for when a hosted plate URL is already known.
    if only not in ("front", "views", "all"):
        raise ValueError("only must be 'front', 'views', or 'all'")

    # Validate every precondition the requested `only` needs BEFORE any governed Genvid
    # write (create_asset, the assetImage assignment, import_media) runs: a failed
    # validation must never leave a real asset or media row created with nothing
    # persisted to the manifest to recover it. Read from a copy -- nothing is mutated
    # here yet.
    existing = dict(m["stages"].get("plate", {}))
    artifact = str(plate_path) if plate_path else existing.get("artifact")
    if only in ("front", "all") and not artifact:
        raise ValueError("no plate artifact on the manifest: pass --plate on the first bind")
    if only in ("views", "all"):
        view_urls = existing.get("view_urls") or {}
        if not view_urls:
            raise ValueError("no view_urls on the manifest: run `plate sheet` before `plate bind --only views`")
        cost_usd = existing.get("cost_usd") or {}
        missing = sorted(v for v in view_urls if v not in cost_usd)
        if missing:
            raise ValueError("no cost_usd recorded for view(s) %s: run `plate sheet` before binding"
                              % ", ".join(missing))
    if only == "views" and not (existing.get("media_ids") or {}).get("front"):
        raise RuntimeError("plate bind --only views needs the front media id bound first (run --only front)")
    if not asset_id and not create and not m.get("asset_id"):
        raise ValueError("no asset_id: pass --asset-id or --create-asset")
    if create:
        # The created asset's description carries the production's own title;
        # checked here with the other preconditions so a manifest without the
        # field never reaches create_asset.
        manifest.production_title(m)
    if create and only == "views":
        # --only views never reaches the "front"/"all" branch below, so it would
        # create a real governed asset with no require_assignee gate and no
        # create_assignment claim. Reject the
        # combination outright rather than widen the gate below to cover it.
        raise ValueError("plate bind --create-asset --only views would create an asset with no "
                          "assignee claim: use --create-asset with --only front or --only all")
    # Every governed write below (create_asset, import_media) must be checked against
    # BEFORE it runs, same as every other precondition here -- "--create-asset" is now
    # rejected when only == "views" (above), so create_asset can only run when only is
    # "front" or "all", and those are exactly the branches gated here and below.
    if only in ("front", "all"):
        genvid_bind.require_assignee(m)

    # Preconditions clear; governed writes start here, with a save after each so a
    # mid-sequence failure leaves a governed partial record (manifest.py's docstring
    # promise: "a failure leaves a governed partial record").
    if create:
        asset_id = genvid_bind.create_asset(m["project_id"], m["name"], "cast_member",
                                            "%s character: %s" % (manifest.production_title(m), m["name"]),
                                            run=run)
        m["asset_id"] = asset_id
        manifest.save(m)
    if asset_id:
        m["asset_id"] = asset_id
    asset_id = m.get("asset_id")

    # stages.plate.artifact is normally written by sheet(), but sheet() runs AFTER the
    # front-only bind in the fixed order above (it needs the front media's signed URL).
    # So the first bind on a fresh manifest must be told the plate path directly.
    st = manifest.set_stage(m, "plate")
    if plate_path:
        st["artifact"] = str(plate_path)
    ids = dict(st.get("media_ids") or {})
    if only in ("front", "all"):
        if create or fresh_asset:
            # Asset created a few lines above in THIS call (or by the caller just
            # before it -- fresh_asset): no assetImage task can exist on it yet, let
            # alone an approved one, so the fire-and-forget create_assignment claim
            # is safe (the same trust `claim_assignment` relies on).
            genvid_bind.claim_assignment(m, asset_id)
        else:
            # Pre-existing asset (--asset-id, or asset_id already on the manifest
            # from an earlier --create-asset run): the reviewer may have approved
            # its plate since, which 409s this front bind until the task is reopened.
            # create_assignment only attaches to the existing task and never
            # reopens it, so gate on ensure_claim and block until the reopen ran.
            genvid_bind.ensure_claim(m, asset_id, "plate.front")
        # T2I: the front plate is the character concept image the reviewer approved
        # before this stage runs -- generated from a text prompt alone, no reference
        # image (input_media_ids=[], below; nothing upstream of this bind conditions
        # it on another media row) -- render_type "image" is not in the boundary's
        # RenderType vocabulary (T2I/I2I/I23D are).
        ids["front"] = genvid_bind.import_media(m["project_id"], path=st["artifact"], link_type="cast_member_image",
            asset_id=asset_id, model_provider="fal", model_name="nano-banana-2", render_type="T2I",
            prompt="approved plate", params={"stage": "plate", "view": "front"}, input_media_ids=[], attested_cost_usd=pricing.NO_VENDOR_CALL, run=run)
        manifest.set_stage(m, "plate", media_id=ids.get("front"), media_ids=dict(ids))
        manifest.save(m)
    if only in ("views", "all"):
        front_id = ids.get("front")
        if front_id is None:
            raise RuntimeError("plate bind --only views needs the front media id bound first (run --only front)")
        if only == "views":
            # `--only all` gated this asset in THIS call, immediately above
            # (fresh claim on a created asset, ensure_claim on an existing one). A
            # standalone `--only views` call ran `--only front` earlier, possibly a
            # whole session ago, and its own gate is keyed to its own site -- the
            # asset may be hand-created and never claimed, or the reviewer may have
            # approved the front plate in between, which 409s this bind until reopened.
            genvid_bind.ensure_claim(m, asset_id, "plate.views")
        for view, url in st["view_urls"].items():
            # I2I: fal-ai/nano-banana-2/edit (MODEL, above) redraws the approved front
            # plate into this view -- sheet()'s own image_urls: [plate_url] payload
            # conditions the edit on the front plate's hosted URL, and input_media_ids
            # cites that same front bind (front_id) as the true derivation source --
            # render_type "image" is not in the boundary's RenderType vocabulary
            # (T2I/I2I/I23D are).
            ids[view] = genvid_bind.import_media(m["project_id"], source_url=url, link_type="cast_member_image",
                asset_id=asset_id, model_provider="fal", model_name="nano-banana-2", render_type="I2I",
                prompt=SHEET_PROMPT(view), params={"stage": "plate", "view": view, "resolution": "2K"}, attested_cost_usd=st["cost_usd"][view],
                input_media_ids=[front_id], run=run)
            manifest.set_stage(m, "plate", media_id=ids.get("front"), media_ids=dict(ids))
            manifest.save(m)
    return ids

def register(sub):
    p = sub.add_parser("plate"); s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("sheet"); a.add_argument("--manifest", required=True); a.add_argument("--plate", required=True)
    a.add_argument("--plate-url", help="hosted URL of the plate for the edit model")
    a.set_defaults(func=lambda x: _sheet(x))
    g = s.add_parser("gaps"); g.add_argument("--manifest", required=True); g.set_defaults(func=lambda x: gaps(manifest.load(x.manifest)))
    b = s.add_parser("bind"); b.add_argument("--manifest", required=True); b.add_argument("--asset-id")
    b.add_argument("--create-asset", action="store_true")
    b.add_argument("--only", choices=("front", "views", "all"), default="all")
    b.add_argument("--plate", help="path to the approved plate image (required on the first bind of a fresh manifest)")
    b.set_defaults(func=lambda x: bind(manifest.load(x.manifest), x.asset_id, x.create_asset, x.only, x.plate))

def _sheet(x):
    m = manifest.load(x.manifest)
    if x.plate_url:
        manifest.set_stage(m, "plate", plate_url=x.plate_url)
    sheet(m, x.plate, fal.transport())
