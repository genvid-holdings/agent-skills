"""Per-character manifest: the artifact + Genvid media id of every stage, and
the stage-order gate. A stage counts as done only when it carries a media_id
(bound in Genvid), so a failure leaves a governed partial record.
"""
import json
from pathlib import Path

STAGES = ("plate", "mesh", "rig", "rest", "groundfit", "clips", "wire", "record")
# A static asset (a per-title skill's static-prop chain: plate + mesh only, parked directly --
# no rig, no rest dump, no ground-fit, no clips) has no use for the stages a
# skinned rig needs. Its manifest carries `"kind": "static"` (that skill's own init)
# and the park Studio step's ingest result lands on "wire" (studio.STAGE_OF), so
# the same four STAGES names cover it -- just a shorter, gated subsequence.
STATIC_STAGES = ("plate", "mesh", "wire", "record")
# Stages that produce no Genvid media of their own (Studio-side steps); they
# count as done when they carry a result.
LOCAL_STAGES = ("rest", "groundfit", "wire")

class StageMissing(RuntimeError):
    pass

def new(name, project_id, height_studs, vendor, out_dir, contract_name=None, assignee=None,
        production_title=None):
    """`name` is the BRAND-FREE name every published asset title is built from;
    `contract_name` is the Studio template's own name, the one the cross-track
    interface contract pins.

    They are usually the same string and `contract_name` defaults to `name`. They
    came apart on the bake-off (witnessed 2026-09-04): the contract pinned
    template names carrying vendor words, and kfs.clip_name refuses to build a
    published KeyframeSequence title from one -- published titles carry no source
    brand. Keeping both lets the template answer to the contract while the clips
    are named from something publishable, instead of one of the two rules being
    quietly broken.

    `assignee` is the reviewer's email every create_assignment claim this
    manifest's chain writes is claimed FOR (genvid_bind.require_assignee /
    claim_assignment / ensure_claim). It has no default here beyond None: a
    manifest with no assignee is valid to build and inspect, it just cannot
    pass any claim-emitting stage (plate.bind, biome.bind, biome.kit_bind,
    biome.kit_model_bind, a per-title static-prop plate bind, and the ensure_claim-gated sites
    plate.bind --only views, mesh.bind, rig.bind, rig.surface_prep, clips.bind,
    biome.sky_bind, biome.kit_bind, biome.kit_model_bind, and plate.bind /
    biome.bind on a pre-existing asset all refuse first)
    -- never silently 'me', which on a runner chain
    resolves to whichever agent holds the MCP session, not the reviewer, so
    the asset lands assigned to nobody and never enters in_progress.

    `vendor` is an optional hint (None when not given): the provider the caller
    expects to use. It is recorded and copied into every request; nothing selects
    behaviour from it.

    `production_title` is the production's own title, and it is written verbatim
    into the description of every governed asset this chain creates
    (plate.bind, biome.bind, biome.kit_bind). It belongs to the production, not
    to this pack, so it has no default and no fallback here: see
    production_title() below, which refuses rather than guessing."""
    return {
        "name": name, "contract_name": contract_name or name,
        "project_id": int(project_id), "height_studs": float(height_studs),
        "vendor": vendor, "out_dir": str(out_dir), "asset_id": None, "assignee": assignee,
        "production_title": production_title, "stages": {},
        "notes": [],
    }


def production_title(m):
    """The production title every created asset's description carries.

    Raises rather than defaulting. A description is governed content written
    into the graph once and read by humans afterwards; a placeholder or a
    borrowed title would be a false provenance claim that no later run can
    tell from a true one. A per-production skill stamps the field on the
    manifest; this pack never knows a value to fall back to."""
    title = m.get("production_title")
    if not title:
        raise ValueError("no production_title on the manifest (m['production_title']); set it at "
                          "`init` (--production-title) -- every asset this bind creates carries it "
                          "in its description and there is no default to fall back to")
    return title


def template_name(m):
    """The Studio template's name: `contract_name` when the manifest carries one,
    else `name` (which is what a manifest written without one has)."""
    return m.get("contract_name") or m["name"]

def path_for(m):
    return Path(m["out_dir"]) / "manifest.json"

def save(m, path=None):
    p = Path(path) if path else path_for(m)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m, indent=2, sort_keys=True))
    return p

def load(path):
    return json.loads(Path(path).read_text())

def set_stage(m, stage, **fields):
    if stage not in stages_for(m):
        raise ValueError("unknown stage %r" % stage)
    entry = m["stages"].setdefault(stage, {})
    entry.update(fields)
    return entry

def _clips_registration_states(m):
    """`{clip: registration.state or None}` for every item on `stages.clips.items`."""
    items = (m["stages"].get("clips") or {}).get("items") or {}
    return {clip: (it.get("registration") or {}).get("state") for clip, it in items.items()}

def _clips_done(m, allow_unregistered=False):
    """A clip is bound through `register_media` + `finalize_media_registration`
    MCP payloads (`clips.bind()`), not a real synchronous import -- the boundary
    rejects a direct `.rbxmx` upload (422, witnessed 2026-09-04). So "done" for the
    `clips` stage is a per-item registration state, not the single top-level
    `media_id` every other stage uses: every clip must be `"registered"` (the
    finalized Genvid media id recorded by `clips registered`, the second half of
    the capture), or, with `allow_unregistered=True`, `"payload_written"` is
    tolerated too (the payloads exist; the orchestrator has not run them for real
    yet) -- an item with no `registration` at all (`bind()` never run for it)
    satisfies neither. At least one clip item must exist."""
    states = _clips_registration_states(m)
    if not states:
        return False
    ok = {"registered"} | ({"payload_written"} if allow_unregistered else set())
    return all(state in ok for state in states.values())

def _clips_registration_gap(m, allow_unregistered=False):
    """Names which clip(s) block `_clips_done` and why -- the generic "needs 'clips'
    bound first" hides exactly this, and it is the one piece of information a
    caller chasing the gap actually needs."""
    states = _clips_registration_states(m)
    if not states:
        return "no stages.clips.items on the manifest -- run `clips bind` first"
    ok = {"registered"} | ({"payload_written"} if allow_unregistered else set())
    gaps = ["%s (registration=%s)" % (clip, state or "none")
            for clip, state in sorted(states.items()) if state not in ok]
    return "clips not registered: %s" % ", ".join(gaps)

def is_done(m, stage, allow_unregistered=False):
    entry = m["stages"].get(stage)
    if not entry:
        return False
    if stage == "clips":
        return _clips_done(m, allow_unregistered=allow_unregistered)
    if stage in LOCAL_STAGES:
        return "result" in entry
    return bool(entry.get("media_id"))

def stages_for(m):
    """The gated stage order for this manifest: `m["stage_order"]` when the manifest
    carries an explicit one (a `kind="location"` biome manifest's own chain),
    else STATIC_STAGES for a static (prop) manifest, else the full
    skinned-rig STAGES."""
    if "stage_order" in m:
        return tuple(m["stage_order"])
    return STATIC_STAGES if m.get("kind") == "static" else STAGES

def require_stage(m, stage, allow_unregistered=False):
    """Every stage before `stage` (in this manifest's stage order) must be done.
    Raises StageMissing naming the gap. `allow_unregistered` only relaxes what
    counts as "done" for the `clips` stage (see `_clips_done`); every other stage
    is unaffected and the argument is accepted uniformly so a caller (`record.run`)
    can thread one flag through without knowing which prior stage it lands on."""
    order = stages_for(m)
    idx = order.index(stage)
    for prior in order[:idx]:
        if not is_done(m, prior, allow_unregistered=allow_unregistered):
            detail = ": %s" % _clips_registration_gap(m, allow_unregistered=allow_unregistered) if prior == "clips" else ""
            raise StageMissing("stage %r needs %r bound first%s (manifest %s)" % (stage, prior, detail, path_for(m)))

def note(m, text):
    m["notes"].append(text)
