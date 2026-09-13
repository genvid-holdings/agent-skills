"""Genvid binds through the `genvid` CLI (the operator's browser login), plus JSON
payload files for the MCP-only tools the orchestrator executes.

Local bytes go multipart (`rendered_output: @path`), never base64 (a base64
field silently truncates a full-resolution image). `source_url` is only for
a provider CDN URL Genvid can fetch itself.
"""
import json, subprocess
from pathlib import Path
import manifest

BODY_MODE = "stdin"   # the confirmed mode; "shorthand" is the alternative
MODEL_LINK = "cast_member_model"   # prefix must equal the asset type

def _run(argv, body=None, run=subprocess.run):
    r = run(argv, input=body, capture_output=True, text=True, check=True)
    out = r.stdout.strip()
    return json.loads(out) if out else {}

def _json_cmd(argv, body, run):
    if BODY_MODE == "stdin":
        return _run(argv, json.dumps(body), run)
    return _run(argv + [_shorthand(body)], None, run)

def _shorthand(body):
    # restish shorthand: {"a": 1, "b": [{"c": "x"}]} -> "a: 1, b[]{c: x}"
    parts = []
    for k, v in body.items():
        if isinstance(v, list):
            for item in v:
                parts.append("%s[]{%s}" % (k, _shorthand(item)))
        elif isinstance(v, dict):
            parts.append("%s{%s}" % (k, _shorthand(v)))
        else:
            parts.append("%s: %s" % (k, json.dumps(v) if isinstance(v, str) else v))
    return ", ".join(parts)

def create_assets(project_id, items, run=subprocess.run):
    """Batch create-assets -- every kit prop for a biome in one request. `items`
    is a list of {"name", "asset_type", "description"}; one `genvid create-assets` call
    for the whole list. Returns the asset_ids in the SAME ORDER as `items` -- the
    openapi CreateAssetsBatchResponse schema documents "assets: The created assets,
    in input order" (witnessed via tooling/genvid-cli/spec/openapi.yaml), so a
    positional zip against `items` is safe, not an assumption."""
    body = {"assets": list(items)}
    out = _json_cmd(["genvid", "create-assets", str(project_id)], body, run)
    assets = out.get("assets") or out.get("items") or []
    if len(assets) != len(items):
        raise RuntimeError("create-assets returned %d asset(s) for %d requested: %r" % (len(assets), len(items), out))
    # 201 schema is assets[].asset_id* (witnessed via `genvid create-assets --help`), not "id".
    return [a["asset_id"] for a in assets]

def create_asset(project_id, name, asset_type, description, run=subprocess.run):
    return create_assets(project_id, [{"name": name, "asset_type": asset_type, "description": description}], run=run)[0]

def import_media(project_id, *, path=None, source_url=None, link_type, asset_id, model_provider,
                 model_name, render_type, prompt, params, input_media_ids, attested_cost_usd,
                 filename=None, stage=None, target=None, run=subprocess.run):
    # attested_cost_usd is REQUIRED (pack 0.9.0 budget-attestation requirement): a decimal string of what the vendor
    # charged for this generation ("0" for a free one). Omitting it records the cost as UNKNOWN
    # and understates project spend. The runner never calls this without a figure.
    if (path is None) == (source_url is None):
        raise ValueError("exactly one of path or source_url")
    if not isinstance(attested_cost_usd, str) or not attested_cost_usd:
        raise ValueError("attested_cost_usd must be a non-empty decimal string")
    fields = {
        "link_type": link_type, "asset_id": asset_id, "model_provider": model_provider,
        "model_name": model_name, "render_type": render_type, "prompt": prompt,
        "params": json.dumps(params), "input_media_ids": json.dumps(input_media_ids),
        "attested_cost_amount": attested_cost_usd, "attested_cost_currency": "USD",
    }
    if stage: fields["stage"] = stage
    if target: fields["target"] = target
    if filename: fields["filename"] = filename
    if source_url:
        fields["source_url"] = source_url
    # Every value is JSON-quoted (same technique _shorthand() uses for the create-assets
    # body): a raw comma, colon, or brace inside e.g. `prompt` is otherwise structural to
    # the restish shorthand grammar and either splits into a bogus field or corrupts the
    # value recorded in the signed provenance attestation.
    parts = ["%s: %s" % (k, json.dumps(v)) for k, v in fields.items()]
    if path:
        parts.insert(0, "rendered_output: @%s" % path)
    argv = ["genvid", "import-generated-media", str(project_id), "-c", "multipart", ", ".join(parts)]
    out = _run(argv, None, run)
    # 201 schema is a flat body with required media_id* (witnessed via
    # `genvid import-generated-media --help`), not a "media" wrapper.
    return out["media_id"]

def list_asset_media(project_id, asset_id, run=subprocess.run):
    out = _run(["genvid", "list-asset-media", str(project_id), str(asset_id)], None, run)
    # Check key presence, not truthiness: {"media": []} is zero media, not an unknown
    # response shape, and must come back as [] rather than falling through to `out`.
    if "media" in out:
        return out["media"]
    if "items" in out:
        return out["items"]
    return out

def conformance(project_id, asset_id, media_id, run=subprocess.run):
    # The CLI takes three positional path parameters -- project-id, asset-id,
    # media-id, in that order (witnessed via `genvid get-media-conformance
    # --help`, 2026-09-04) -- not two. The endpoint also documents 422 "if the
    # media is not 3D model media" (same --help output): calling it on a clip
    # or capture media id is expected to fail, not a symptom of the arg-count
    # bug.
    return _run(["genvid", "get-media-conformance", str(project_id), str(asset_id), str(media_id)], None, run)

def provenance(project_id, node_type, node_id, run=subprocess.run):
    return _run(["genvid", "get-provenance", str(project_id), node_type, str(node_id)], None, run)

def mcp_payload(tool, out_dir, **args):
    d = Path(out_dir) / "mcp"
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("%s-*.json" % tool))) + 1
    p = d / ("%s-%d.json" % (tool, n))
    p.write_text(json.dumps({"tool": tool, "args": args}, indent=2))
    return p


def require_assignee(m):
    """Refuse before any governed write when the manifest carries no explicit
    reviewer. Every asset-CREATING caller (plate.bind, biome.bind,
    biome.kit_bind, a per-title skill's static-prop plate bind) calls this
    FIRST, ahead of any `genvid create-assets` / `import-generated-media`
    subprocess call, so a missing assignee never leaves a real asset created
    with nothing claimed: an asset created under a missing assignee is
    left assigned to nobody and never enters `in_progress`.
    `ensure_claim` (below) also calls this, for every site that binds to an
    asset it did not just create (plate.bind --only front/all on an existing
    asset, plate.bind --only views, mesh.bind, rig.bind, rig.surface_prep,
    clips.bind, biome.bind on an existing asset, biome.sky_bind,
    biome.kit_bind, biome.kit_model_bind).

    Never defaults to 'me': genvid-agent-generation's own Step 0 lets an agent
    omit `assigned_to_email` (or pass "me") to self-assign, which is correct
    there because the calling agent IS the reviewer of its own generation. This
    runner's chain is different -- the caller is an orchestrator/agent session,
    not the human who reviews the asset in Genvid, so 'me' would resolve to the
    agent's own MCP token and claim the work for the wrong identity. Pass
    `--assignee <email>` to the manifest's `init` command instead."""
    assignee = m.get("assignee")
    if not assignee:
        raise ValueError(
            "manifest has no assignee: pass --assignee <email> to the `... init` "
            "command before any claim-emitting stage runs. Refusing rather than "
            "defaulting to 'me' -- on a runner chain 'me' resolves to whichever "
            "agent holds the MCP session, not the reviewer, so the asset lands "
            "assigned to nobody and never enters in_progress.")
    return assignee


def claim_assignment(m, asset_id, out_dir=None):
    """production_write create_assignment: claims (or re-claims -- idempotent on
    the orchestrator's side, it attaches to an existing assignment) an asset's
    assetImage task for `m["assignee"]`."""
    assignee = require_assignee(m)
    return mcp_payload("production_write", out_dir or m["out_dir"], method="create_assignment",
        project_id=m["project_id"], resource_type="asset", resource_id=asset_id,
        task_type="assetImage", workflow_status="in_progress", assigned_to_email=assignee)


class ClaimPending(RuntimeError):
    """Raised by `ensure_claim` when it cannot yet tell whether the bind it
    guards is safe to run: either the asset's current assignment status is not
    yet known (a `production_read list_assignments` payload was just written
    for the orchestrator), or it IS known to be in a state (`approved`/
    `in_review`) that this helper treats as blocking (see `ensure_claim`'s
    docstring for which of those is actually witnessed to 409), and a reopen
    payload was just written for that. Same shape as `plate.BudgetError`: the
    caller must run the named payload for real and (for the first case)
    record the result, then retry."""
    pass


# Task statuses the boundary's assignment contract documents (SKILL.md 0,
# genvid-agent-generation SKILL.md Step 0): not_started, in_progress,
# in_review, rejected, approved, cancelled. "none" is this helper's own
# sentinel for "no assetImage task exists yet on this resource at all" --
# never a real workflow_status value.
_UNCLAIMED_STATUSES = ("none", "not_started")
_REOPENABLE_STATUSES = ("approved", "in_review")


def ensure_claim(m, asset_id, site):
    """Gate every site that binds to an asset it did not just create (`plate
    bind --only front/all` on an existing asset, `plate bind --only views`,
    `mesh.bind`, `rig.bind`, `rig.surface_prep`, `clips.bind`, `biome.bind` on
    an existing asset, `biome.sky_bind`, `biome.kit_bind`,
    `biome.kit_model_bind`) the same way `require_assignee` gates every
    asset-CREATING site -- called BEFORE that site's first governed write,
    never after. `require_assignee`'s and `manifest.new`'s own caller lists
    name the asset-creating gates; the sites above are the gates added by this
    function. Unlike `claim_assignment`, this asset was not
    necessarily just created here: it may be hand-created and never claimed,
    already claimed and still `in_progress` (the common case -- must cost
    nothing), or already `approved`/`in_review` because the reviewer acted
    on an earlier bind on it, in which case the boundary may answer 409 to this one
    unless the task is reopened first.

    `production_read(method="list_assignments", ...)` is a governed read this
    runner cannot make itself (same reason `plate.budget_gate` defers
    `check_generation_budget`): the first call for a given `(asset_id, site)`
    writes that payload and raises `ClaimPending` naming exactly where to
    record the assetImage task's `workflow_status` (`"none"` if no such task
    exists) -- at `m["claims"]["<asset_id>:<site>"]["workflow_status"]` --
    before this site's bind may run at all. `site` keys the cache so an
    already-resolved plate.front claim never satisfies a later mesh/rig/clips
    site on the same asset that was approved in between; `asset_id` keys it so
    two different characters' manifests never share a cache entry. The cache
    is not re-validated once resolved (same tradeoff `budget_gate` makes): a
    same-site rebind after a LATER approval reads the stale cached
    `in_progress` and can still 409 -- delete `m["claims"][key]` (the whole
    key, not just its `workflow_status`: an entry left with a `reopen_payload`
    and no status is read as an unrecorded reopen and blocks on that payload
    instead of re-listing) to force a fresh list. The one status this helper
    never writes into the cache itself
    is the post-reopen one: after writing a reopen payload it DROPS the cached
    status, so the bind proceeds only on a status the orchestrator recorded
    after actually running that reopen (see the `approved` bullet below).

    Once the status is known:
    - `"none"`: writes the `create_assignment` claim (same shape
      `claim_assignment` uses) and returns `"created"` -- fire-and-forget,
      since a freshly-claimed task does not put the resource in a state that
      blocks the very next governed write, the same trust
      `claim_assignment` already relies on.
    - `"not_started"` (an assignment record exists but nobody has started it):
      treated the same as `"none"` -- `create_assignment` is documented
      idempotent, attaching to an existing assignment rather than erroring on
      one (assumption: that idempotency is attested by `claim_assignment`'s
      own docstring, not independently re-witnessed here).
    - `"in_progress"`: no-op, no payload written, returns `"noop"`.
    - `"approved"`: writes the `set_assignment_status` reopen payload
      (references/boundary-tools.md does not break `set_assignment_status`'s
      parameters out from production_write's shared set, so this reuses
      create_assignment's resource_type/resource_id/task_type shape --
      UNVERIFIED against a published per-method schema) and raises
      `ClaimPending` -- this one DOES block, because the very next line in
      every one of these sites is a synchronous `genvid` CLI call (or a
      register/finalize payload the orchestrator runs next) that would
      otherwise still hit the resource while it is still `approved` and 409
      (witnessed 2026-09-07). A fire-and-forget reopen loses that race: the
      next call reaches the resource before the reopen has landed. The block is
      real, not one-shot: the cached status is dropped when the reopen payload
      is written, and every later call raises `ClaimPending` naming that same
      payload (no second list read) until the orchestrator has run it and
      recorded the resulting `workflow_status` at `m["claims"][key]`; only a
      recorded `in_progress` lets the bind through.
    - `"in_review"`: reopened and blocked the same way as `approved`, on the
      same reasoning (a human-held review state, same shape) -- its own 409 is
      not separately witnessed, only inferred from the `approved` case.
    - any other status (`"rejected"`, `"cancelled"`, or anything this helper
      does not recognize): raises loudly rather than guess whether it also
      409s a bind.

    Refuses before any read or write when the manifest has no assignee,
    naming `site` in the error (never defaults to `"me"` -- see
    `require_assignee`)."""
    try:
        assignee = require_assignee(m)
    except ValueError as e:
        raise ValueError("ensure_claim (%s): %s" % (site, e))
    if not asset_id:
        raise ValueError("ensure_claim (%s): no asset_id given" % site)

    claims = m.setdefault("claims", {})
    key = "%s:%s" % (asset_id, site)
    entry = claims.get(key)
    if entry is not None and "workflow_status" not in entry and entry.get("reopen_payload"):
        # A reopen was written on an earlier call and its result has not been
        # recorded yet: keep blocking on THAT payload (no second list read) until
        # the orchestrator has run it and written the resulting status back.
        raise ClaimPending(
            "ensure_claim (%s): asset %s's assetImage task was %s and the reopen payload %s has not "
            "been recorded as run: run it for real, then record the task's resulting workflow_status "
            "at claims[%r].workflow_status ('in_progress' once the reopen succeeded) before this "
            "bind may run" % (site, asset_id, entry.get("reopened_from", "approved/in_review"),
                              entry["reopen_payload"], key))
    if entry is None or "workflow_status" not in entry:
        payload_path = mcp_payload("production_read", m["out_dir"], method="list_assignments",
            project_id=m["project_id"], resource_type="asset", resource_id=asset_id)
        claims[key] = {"list_payload": str(payload_path)}
        manifest.save(m)
        raise ClaimPending(
            "ensure_claim (%s): asset %s's assetImage assignment status is not yet known: wrote %s "
            "for the orchestrator to run; record the assetImage task's workflow_status ('none' if no "
            "such task exists) at claims[%r].workflow_status on the manifest before this bind may run"
            % (site, asset_id, payload_path, key))

    status = entry["workflow_status"]
    if status == "in_progress":
        return "noop"
    if status in _UNCLAIMED_STATUSES:
        p = mcp_payload("production_write", m["out_dir"], method="create_assignment",
            project_id=m["project_id"], resource_type="asset", resource_id=asset_id,
            task_type="assetImage", workflow_status="in_progress", assigned_to_email=assignee)
        entry["claim_payload"] = str(p)
        entry["workflow_status"] = "in_progress"
        manifest.note(m, "ensure_claim (%s): asset %s's assetImage task was %r; claimed it for %s (%s)"
                          % (site, asset_id, status, assignee, Path(p).name))
        manifest.save(m)
        return "created"
    if status in _REOPENABLE_STATUSES:
        p = mcp_payload("production_write", m["out_dir"], method="set_assignment_status",
            project_id=m["project_id"], resource_type="asset", resource_id=asset_id,
            task_type="assetImage", workflow_status="in_progress")
        entry["reopen_payload"] = str(p)
        entry["reopened_from"] = status
        # NOT optimistically cached as in_progress: the bind may only proceed on a
        # status the orchestrator RECORDED after running the reopen. Setting it here
        # would let the very next retry no-op past an unrun (or failed) reopen and
        # 409 exactly as before.
        del entry["workflow_status"]
        manifest.note(m, "ensure_claim (%s): asset %s's assetImage task was %s; wrote %s to reopen it "
                          "to in_progress -- run that for real and record the resulting status at "
                          "claims[%r].workflow_status before retrying this bind" % (site, asset_id, status, Path(p).name, key))
        manifest.save(m)
        raise ClaimPending(
            "ensure_claim (%s): asset %s's assetImage task is %r; wrote %s to reopen it to "
            "in_progress -- the boundary answers 409 to a bind on an approved task (witnessed "
            "2026-09-07); in_review is reopened on the same rule but its 409 is "
            "not itself separately witnessed. Run that payload for real, then record the task's "
            "resulting workflow_status at claims[%r].workflow_status, then retry this bind"
            % (site, asset_id, status, p, key))
    raise RuntimeError(
        "ensure_claim (%s): asset %s's assetImage task has workflow_status %r, which this helper "
        "does not know how to recover from -- resolve it by hand in Genvid, then retry" % (site, asset_id, status))
