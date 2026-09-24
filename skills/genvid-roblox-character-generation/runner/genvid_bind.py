"""Genvid binds and the gates' reads through the `genvid` CLI (the operator's
browser login), plus JSON payload files for the MCP-only writes the orchestrator
executes.

Local bytes go multipart (`rendered_output: @path`), never base64 (a base64
field silently truncates a full-resolution image). `source_url` is for a
provider-hosted result Genvid fetches itself; the boundary fetches only from
result hosts it has vetted for the attested provider, so an ingest that holds
the bytes too passes `fallback_path` and is re-sent multipart when the boundary
refuses the URL.
"""
import json, subprocess, uuid
from datetime import datetime, timezone
from pathlib import Path
import manifest, cost

BODY_MODE = "stdin"   # the confirmed mode; "shorthand" is the alternative
MODEL_LINK = "cast_member_model"   # prefix must equal the asset type

# The restish-based CLI sets no request timeout of its own, and calls were
# witnessed hanging with no error (2026-09-23): `genvid get-media-signed-urls`,
# and binds for 400-900 s while the boundary never saw the request. Every call
# through `_run` is killed after one of these.
#
# A read (or gate read) that has not answered in this long is refused, never waited on.
READ_TIMEOUT_S = 60
# A write uploads a file and waits for the boundary to sign it. 300 s is the
# edge proxy's own read ceiling, so no answer the boundary can give takes longer.
BIND_TIMEOUT_S = 300


class GenvidCliTimeout(RuntimeError):
    """A `genvid` call through `_run` did not answer within its timeout."""
    pass


class GenvidBindTimeout(GenvidCliTimeout):
    """A bind did not answer, twice; it may have landed (see `_bind`)."""
    pass


def _run(argv, body=None, run=subprocess.run, timeout=READ_TIMEOUT_S):
    try:
        r = run(argv, input=body, capture_output=True, text=True, check=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GenvidCliTimeout("`%s` did not answer within %ss" % (" ".join(map(str, argv)), timeout))
    out = r.stdout.strip()
    return json.loads(out) if out else {}


def _bind(argv_head, argv_tail, run):
    """One bind, sent with an idempotency key and resent once on a timeout.

    A timed-out bind may have landed with its answer lost (witnessed 2026-09-23),
    so the resend carries the SAME key: the boundary replays the original
    answer instead of creating a second row. Each attempt carries its own
    X-Request-Id, which the boundary logs, so either attempt can be found."""
    key, request_ids = str(uuid.uuid4()), []
    for _ in range(2):
        request_ids.append(uuid.uuid4().hex)
        argv = argv_head + ["--idempotency-key", key, "-H", "X-Request-Id: %s" % request_ids[-1]] + argv_tail
        try:
            return _run(argv, None, run, timeout=BIND_TIMEOUT_S)
        except GenvidCliTimeout:
            continue
    raise GenvidBindTimeout(
        "`%s` did not answer within %ss, twice (request ids %s). It may have landed: resend it only with "
        "the same idempotency key %s, which replays the original answer, or check list-asset-media first."
        % (" ".join(argv_head), BIND_TIMEOUT_S, ", ".join(request_ids), key))

def _json_cmd(argv, body, run):
    if BODY_MODE == "stdin":
        return _run(argv, json.dumps(body), run, timeout=BIND_TIMEOUT_S)
    return _run(argv + [_shorthand(body)], None, run, timeout=BIND_TIMEOUT_S)

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

# The boundary's refusals of a source_url it will not fetch: the provider has no
# vetted result-host list, or the URL's host is not on it. Only these fall back
# to a multipart upload; any other failure (a claim conflict, a bad field) is
# re-raised as is.
SOURCE_URL_REFUSALS = ("source_url ingest is not supported for provider",
                       "source_url rejected by the result fence")


def _cost_fields(attested_cost_usd, cost_record):
    """The attested_cost_* fields for one bind, from exactly one of the legacy
    `attested_cost_usd` string or a cost.py record. An unobserved cost sends
    neither field (the boundary takes them as a pair and records the omission as
    unknown); a known cost sends both."""
    if (attested_cost_usd is None) == (cost_record is None):
        raise ValueError("give exactly one of attested_cost_usd or cost")
    if cost_record is not None:
        rec = cost.check_record(cost_record)
    elif not isinstance(attested_cost_usd, str) or not attested_cost_usd:
        raise ValueError("attested_cost_usd must be a non-empty decimal string")
    elif attested_cost_usd == cost.COST_UNOBSERVED:
        rec = {"unobserved": True}
    else:
        rec = {"amount": attested_cost_usd, "currency": "USD"}
    if cost.is_unobserved(rec):
        return {}
    return {"attested_cost_amount": rec["amount"], "attested_cost_currency": rec["currency"]}


def _is_source_url_refusal(err):
    text = "%s\n%s" % (err.stdout or "", err.stderr or "")
    return any(r in text for r in SOURCE_URL_REFUSALS)


def import_media(project_id, *, path=None, source_url=None, link_type, asset_id, model_provider,
                 model_name, render_type, prompt, params, input_media_ids, attested_cost_usd=None,
                 cost=None, fallback_path=None, filename=None, stage=None, target=None,
                 run=subprocess.run):
    """Bind generated bytes to an asset with the caller's attestation.

    The cost is REQUIRED, as exactly one of `cost` (a cost.py record: an amount
    with its currency, or unobserved) or the older `attested_cost_usd` (a USD
    decimal string, or cost.COST_UNOBSERVED). An unobserved cost omits both
    attested fields, which the boundary records as unknown; it is never sent as
    "0", which claims the generation was free.

    Exactly one of `path` (multipart upload) and `source_url` is the primary
    route. `fallback_path` goes with `source_url`: when the boundary refuses the
    URL's host (SOURCE_URL_REFUSALS), the same bind is sent again with the file
    at `fallback_path` uploaded multipart."""
    if (path is None) == (source_url is None):
        raise ValueError("exactly one of path or source_url")
    if fallback_path is not None and source_url is None:
        raise ValueError("fallback_path goes with source_url")
    cost_fields = _cost_fields(attested_cost_usd, cost)
    fields = {
        "link_type": link_type, "asset_id": asset_id, "model_provider": model_provider,
        "model_name": model_name, "render_type": render_type, "prompt": prompt,
        "params": json.dumps(params), "input_media_ids": json.dumps(input_media_ids),
    }
    fields.update(cost_fields)
    if stage: fields["stage"] = stage
    if target: fields["target"] = target
    if filename: fields["filename"] = filename

    def send(upload_path, url):
        f = dict(fields)
        if url:
            f["source_url"] = url
        # Every value is JSON-quoted (same technique _shorthand() uses for the create-assets
        # body): a raw comma, colon, or brace inside e.g. `prompt` is otherwise structural to
        # the restish shorthand grammar and either splits into a bogus field or corrupts the
        # value recorded in the signed provenance attestation.
        parts = ["%s: %s" % (k, json.dumps(v)) for k, v in f.items()]
        if upload_path:
            parts.insert(0, "rendered_output: @%s" % upload_path)
        # Each send gets its own key: a key names one request body, and the multipart
        # fallback is a different body from the source_url send it follows.
        # 201 schema is a flat body with required media_id* (witnessed via
        # `genvid import-generated-media --help`), not a "media" wrapper.
        return _bind(["genvid", "import-generated-media", str(project_id)],
                     ["-c", "multipart", ", ".join(parts)], run)["media_id"]

    if source_url is None:
        return send(path, None)
    try:
        return send(None, source_url)
    except subprocess.CalledProcessError as e:
        if fallback_path is None or not _is_source_url_refusal(e):
            raise
        return send(fallback_path, None)


def signed_urls(project_id, media_ids, run=subprocess.run):
    """Download URLs for `media_ids`, in the order given, from the batch
    `get-media-signed-urls` read (the handoff for a caller that feeds Genvid media
    to its own generator). Each entry carries at least `media_id` and
    `signed_url`, plus `expires_at`, `filename`, `media_type` when the boundary
    sends them.

    The read answers 200 with unresolvable ids listed in `errors`; any requested
    id that did not come back with a signed URL raises, naming it, so a request is
    never written with an input missing."""
    ids = [str(i) for i in media_ids]
    if not ids:
        return []
    out = _run(["genvid", "get-media-signed-urls", str(project_id), ",".join(ids)], None, run)
    by_id = {str(e.get("media_id")): e for e in (out.get("media") or []) if isinstance(e, dict)}
    errors = {str(e.get("media_id")): e.get("reason") for e in (out.get("errors") or []) if isinstance(e, dict)}
    missing = ["%s (%s)" % (i, errors.get(i) or "not returned") for i in ids
               if i not in by_id or not by_id[i].get("signed_url")]
    if missing:
        raise RuntimeError("get-media-signed-urls could not sign media %s; refusing to write a request "
                           "without every input" % ", ".join(missing))
    return [by_id[i] for i in ids]


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



class GenvidReadError(RuntimeError):
    """A gate's read through the `genvid` CLI failed, timed out, or answered
    something that is not the read it asked for."""
    pass


class GenvidCommandMissing(GenvidReadError):
    """The installed `genvid` CLI has no such command (it predates it)."""
    pass


def cli_version(run=subprocess.run):
    """The installed `genvid` CLI's version string, as `genvid version` prints it."""
    try:
        r = run(["genvid", "version"], capture_output=True, text=True, check=True, timeout=READ_TIMEOUT_S)
    except (subprocess.SubprocessError, OSError) as e:
        return "unknown (`genvid version` failed: %s)" % e
    return r.stdout.strip() or "unknown"


def cli_read(argv, timeout=READ_TIMEOUT_S, run=subprocess.run):
    """Run one read-only `genvid` command and return its provenance record:
    `{"command": argv, "response": <parsed JSON>, "read_at": <UTC ISO>}`. The
    gates store this record next to the verdict they take from it, so what the
    manifest says was read is what the CLI printed, never a retyped value."""
    argv = [str(a) for a in argv]
    cmd = " ".join(argv)
    try:
        r = run(argv, capture_output=True, text=True, check=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GenvidReadError("`%s` did not answer within %ss; refusing rather than waiting" % (cmd, timeout))
    except FileNotFoundError:
        raise GenvidReadError("`%s`: the genvid CLI is not on PATH" % cmd)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or "").strip()
        if "unknown command" in err:
            raise GenvidCommandMissing("`%s`: this genvid CLI has no %r command; install a genvid CLI whose "
                                       "`genvid --help` lists it" % (cmd, argv[1]))
        raise GenvidReadError("`%s` exited %s: %s" % (cmd, e.returncode, err))
    try:
        response = json.loads(r.stdout)
    except (TypeError, ValueError):
        raise GenvidReadError("`%s` printed something that is not JSON: %r" % (cmd, (r.stdout or "")[:200]))
    if not isinstance(response, dict):
        raise GenvidReadError("`%s` answered %r, not a JSON object" % (cmd, response))
    return {"command": argv, "response": response,
            "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def organization_id(m):
    """The project's organization id, from `genvid get-project` (list-tasks is
    org-scoped). Read once and kept at `m["organization_id"]`."""
    if m.get("organization_id"):
        return m["organization_id"]
    read = cli_read(["genvid", "get-project", m["project_id"]])
    org = read["response"].get("organization_id")
    if not org:
        raise GenvidReadError("`%s` answered no organization_id" % " ".join(read["command"]))
    m["organization_id"] = org
    manifest.note(m, "organization_id %s read with `%s` at %s" % (org, " ".join(read["command"]), read["read_at"]))
    manifest.save(m)
    return org


def asset_image_status(m, asset_id):
    """Read the asset's assetImage task with `genvid list-tasks` and return
    `(workflow_status, read)`, the status `"none"` when no such task exists. A
    response that is not about this asset, or that holds more than one
    assetImage task for it, is refused rather than picked from."""
    read = cli_read(["genvid", "list-tasks", organization_id(m), m["project_id"],
                     "--resource-type", "asset", "--resource-id", asset_id,
                     "--task-type", "assetImage", "--limit", "100"])
    status = _status_of(read, m, asset_id)
    # Keep what the verdict rests on, not the whole response: no emails or
    # assignee lists land in the manifest.
    read["response"] = {"has_more": read["response"]["has_more"],
                        "items": [{k: t.get(k) for k in _TASK_FIELDS} for t in read["response"]["items"]]}
    return status, read


_TASK_FIELDS = ("id", "resource_type", "resource_id", "task_type", "project_id", "workflow_status")


def _status_of(read, m, asset_id):
    """The assetImage status a list-tasks read answers for `asset_id`, refusing
    one that is not about this asset or holds more than one such task."""
    cmd, resp = " ".join(read["command"]), read["response"]
    items = resp.get("items")
    if not isinstance(items, list) or resp.get("has_more") is not False:
        raise GenvidReadError("`%s` answered no complete items list (has_more=%r)" % (cmd, resp.get("has_more")))
    for t in items:
        if (not isinstance(t, dict) or str(t.get("resource_id")) != str(asset_id)
                or t.get("resource_type") != "asset" or t.get("task_type") != "assetImage"
                or str(t.get("project_id")) != str(m["project_id"])):
            raise GenvidReadError("`%s` answered a task that is not asset %s's assetImage task in project %s: %r"
                                  % (cmd, asset_id, m["project_id"], t))
    if len(items) > 1:
        raise GenvidReadError("`%s` answered %d assetImage tasks for asset %s; refusing to pick one"
                              % (cmd, len(items), asset_id))
    if not items:
        return "none"
    status = items[0].get("workflow_status")
    if not isinstance(status, str) or not status:
        raise GenvidReadError("`%s` answered a task with no workflow_status: %r" % (cmd, items[0]))
    return status


def _claim_holds(entry, m, asset_id):
    """A cached claim status holds only when its own list-tasks read of this
    asset answers that status. A status with no such read behind it -- written
    by hand, by the payload-era gate, or cached next to a claim payload -- is
    read again."""
    status, read = entry.get("workflow_status"), entry.get("read")
    if not (isinstance(read, dict) and isinstance(read.get("command"), list)
            and read["command"][1:2] == ["list-tasks"] and str(asset_id) in read["command"]):
        return False
    try:
        return _status_of(read, m, asset_id) == status
    except (GenvidReadError, KeyError, TypeError, AttributeError):
        return False


def _pending_claim(m, asset_id):
    """This runner's own create_assignment payload for `asset_id`'s assetImage
    task, if one was already written (the CLI has no create-task command, so
    the orchestrator runs it); None when there is none."""
    for p in sorted((Path(m["out_dir"]) / "mcp").glob("production_write-*.json")):
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        args = data.get("args") or {}
        if (data.get("tool") == "production_write" and args.get("method") == "create_assignment"
                and args.get("resource_type") == "asset" and str(args.get("resource_id")) == str(asset_id)
                and args.get("task_type") == "assetImage"):
            return p
    return None


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
    """Raised by `ensure_claim` when the asset's assetImage task is in a state
    (`approved`/`in_review`) that this helper treats as blocking (see
    `ensure_claim`'s docstring for which of those is actually witnessed to
    409): a reopen payload was written for it, or was written earlier and the
    task still reads as that state. The caller runs the named payload for real,
    then retries; the retry reads the task again itself."""
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
    `mesh.bind`, `rig.bind` (whose site `rig.bind_clips` deliberately reuses:
    the bundled clips bind to the same asset in the same ingest), `rig.surface_prep`,
    `clips.bind`, `clips.ingest_motion` (site `clips.motion`), `biome.bind` on
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

    The status comes from `asset_image_status` (`genvid list-tasks`, read by
    this helper itself): the first call for a given `(asset_id, site)` reads it
    and caches it with the read's provenance (command, response, time) at
    `m["claims"]["<asset_id>:<site>"]`, `"none"` if no assetImage task exists.
    Nothing is recorded by hand: a cached status holds only while
    `_claim_holds` (its own read answers it), and any other entry is read
    again. `site` keys the cache so an
    already-resolved plate.front claim never satisfies a later mesh/rig/clips
    site on the same asset that was approved in between; `asset_id` keys it so
    two different characters' manifests never share a cache entry. The cache
    is not re-validated once resolved (same tradeoff `budget_gate` makes): a
    same-site rebind after a LATER approval reads the stale cached
    `in_progress` and can still 409 -- delete `m["claims"][key]` to force a
    fresh read. The one status this helper never caches without reading it is
    the post-reopen one: after writing a reopen payload it DROPS the cached
    status, and the next call reads the task again (see the `approved` bullet
    below).

    Once the status is known:
    - `"none"`: writes the `create_assignment` claim (same shape
      `claim_assignment` uses) and returns `"created"` -- fire-and-forget,
      since a freshly-claimed task does not put the resource in a state that
      blocks the very next governed write, the same trust
      `claim_assignment` already relies on. The status is not cached: the next
      call reads the task again, and while it still reads unclaimed with this
      runner's own claim payload for the asset already written
      (`_pending_claim`), it raises `ClaimPending` naming that payload instead
      of writing a duplicate.
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
      is written, and every later call reads the task again and raises
      `ClaimPending` naming that same payload while it is still
      `approved`/`in_review`; only a freshly read `in_progress` lets the bind
      through.
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
        # A reopen was written on an earlier call: read the task again and let the
        # bind through only on a fresh in_progress, the reopen having landed.
        status, read = asset_image_status(m, asset_id)
        entry["read"] = read
        if status == "in_progress":
            entry["workflow_status"] = status
            manifest.save(m)
            return "noop"
        manifest.save(m)
        if status in _REOPENABLE_STATUSES:
            raise ClaimPending(
                "ensure_claim (%s): asset %s's assetImage task is still %r (`%s` at %s): run the reopen "
                "payload %s for real, then retry this bind" % (site, asset_id, status,
                    " ".join(read["command"]), read["read_at"], entry["reopen_payload"]))
        raise RuntimeError(
            "ensure_claim (%s): asset %s's assetImage task is %r after the reopen payload %s, which this "
            "helper does not know how to recover from -- resolve it by hand in Genvid, then retry"
            % (site, asset_id, status, entry["reopen_payload"]))
    if entry is None or "workflow_status" not in entry or not _claim_holds(entry, m, asset_id):
        status, read = asset_image_status(m, asset_id)
        entry = claims[key] = {"workflow_status": status, "read": read}
        manifest.save(m)

    status = entry["workflow_status"]
    if status == "in_progress":
        return "noop"
    if status in _UNCLAIMED_STATUSES:
        pending = _pending_claim(m, asset_id)
        if pending is not None:
            # Our own claim was written earlier and the task still reads unclaimed:
            # never write a duplicate; the bind waits for that payload to run.
            del entry["workflow_status"]
            entry["claim_payload"] = str(pending)
            manifest.save(m)
            raise ClaimPending(
                "ensure_claim (%s): asset %s's assetImage task still reads %r and this runner's claim "
                "payload %s has not landed: run it, then re-run this stage (the re-run reads the task "
                "again). If it already ran and the task still reads %r, the claim failed: resolve it "
                "in Genvid" % (site, asset_id, status, pending, status))
        p = mcp_payload("production_write", m["out_dir"], method="create_assignment",
            project_id=m["project_id"], resource_type="asset", resource_id=asset_id,
            task_type="assetImage", workflow_status="in_progress", assigned_to_email=assignee)
        entry["claim_payload"] = str(p)
        # Not cached as in_progress: the next call reads the task again, and
        # proceeds once this payload has run.
        del entry["workflow_status"]
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
        # status READ after the reopen ran. Setting it here
        # would let the very next retry no-op past an unrun (or failed) reopen and
        # 409 exactly as before.
        del entry["workflow_status"]
        manifest.note(m, "ensure_claim (%s): asset %s's assetImage task was %s; wrote %s to reopen it "
                          "to in_progress -- run that for real before retrying this bind"
                          % (site, asset_id, status, Path(p).name))
        manifest.save(m)
        raise ClaimPending(
            "ensure_claim (%s): asset %s's assetImage task is %r; wrote %s to reopen it to "
            "in_progress -- the boundary answers 409 to a bind on an approved task (witnessed "
            "2026-09-07); in_review is reopened on the same rule but its 409 is "
            "not itself separately witnessed. Run that payload for real, then retry this bind "
            "(the retry reads the task again)" % (site, asset_id, status, p))
    raise RuntimeError(
        "ensure_claim (%s): asset %s's assetImage task has workflow_status %r, which this helper "
        "does not know how to recover from -- resolve it by hand in Genvid, then retry" % (site, asset_id, status))
