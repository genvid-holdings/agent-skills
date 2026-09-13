"""fal queue API. Docs: https://docs.fal.ai/model-endpoints/queue
(fal MCP witness 2026-09-03)."""
import json
import mimetypes
import os
import time
from pathlib import Path
from . import http

QUEUE = "https://queue.fal.run"
STORAGE_INITIATE = "https://rest.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3"

# mimetypes.guess_type's builtin table for .glb varies by Python version (confirmed
# "model/gltf-binary" only from 3.14's table; 3.9-3.13 fall back to application/octet-stream
# on this machine), so pin the suffixes this runner actually uploads here rather than trust
# the interpreter's table to agree across hosts.
_CONTENT_TYPES = {".glb": "model/gltf-binary"}

def _content_type(name):
    ext = Path(name).suffix.lower()
    if ext in _CONTENT_TYPES:
        return _CONTENT_TYPES[ext]
    return mimetypes.guess_type(name)[0] or "application/octet-stream"

def transport(ledger_path=None):
    key = os.environ["FAL_KEY"]
    return http.Transport({"Authorization": "Key " + key}, ledger_path=ledger_path)

def upload_file(path, t):
    """Upload a local file to fal's CDN storage; returns the resulting file_url.

    Flow and field names CONFIRMED by
    https://fal.ai/docs/documentation/model-apis/file-access-controls#setting-an-acl-per-request
    (cURL block "A direct upload is two steps", witnessed 2026-09-03): POST
    .../storage/upload/initiate?storage_type=fal-cdn-v3 with body {file_name, content_type} ->
    the response carries {upload_url, file_url} -> PUT the raw bytes to upload_url with a
    matching Content-Type -> file_url is the CDN url callers pass as image_urls/model_url.
    content_type is derived from the file's suffix (a small pinned table for suffixes whose
    mimetypes-module answer varies by Python version, e.g. .glb -> model/gltf-binary; else
    mimetypes.guess_type, falling back to application/octet-stream) and the identical value
    is sent on both the initiate call and the PUT.
    """
    p = Path(path)
    content_type = _content_type(p.name)
    init = t.json("POST", STORAGE_INITIATE, {"file_name": p.name, "content_type": content_type})
    t.put_bytes(init["upload_url"], p.read_bytes(), content_type=content_type)
    return init["file_url"]

def _ledger_load(path):
    """The ledger is one JSON file per out_dir (`{request_id: entry}`), shared
    by every stage that submits a paid vendor job through this manifest's
    transport. A missing file reads as empty (a fresh ledger for a fresh
    manifest is normal), but a PRESENT, corrupt file raises loudly naming the
    path: `_ledger_save` writes atomically (tmp file + os.replace), so there is
    no legitimate partial-write state left to read past silently -- reading
    corruption as "empty" would turn "the ledger was lost" into "pay again",
    exactly the failure this ledger exists to prevent."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise RuntimeError("fal request ledger %s is corrupt (%s); it should never be partially "
                            "written (saves are atomic) -- inspect it by hand before resubmitting "
                            "anything, a stale entry here is the difference between resuming a paid "
                            "job and paying for it twice" % (path, e)) from e

def _ledger_save(path, ledger):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True))
    os.replace(tmp, p)  # atomic on POSIX: a reader never sees a half-written file

def _ledger_write_submit(t, model_id, request_id, out, tag):
    path = getattr(t, "ledger_path", None)
    if not path:
        return
    ledger = _ledger_load(path)
    ledger[request_id] = {
        "model_id": model_id, "request_id": request_id,
        "status_url": out.get("status_url"), "response_url": out.get("response_url"),
        "submitted_at": time.time(), "tag": tag, "done": False, "result": None,
        "failed": False, "error": None,
    }
    _ledger_save(path, ledger)

def _ledger_entry_by_id(t, request_id):
    path = getattr(t, "ledger_path", None)
    if not path:
        return None
    return _ledger_load(path).get(request_id)

def _ledger_entry_by_tag(t, model_id, tag):
    # Skips an entry marked failed: a vendor-side FAILED/ERROR job is done
    # trying under this request id, and the tag has to be free for the next
    # submit() to claim -- otherwise the same (model_id, tag) match that lets a
    # dead driver resume a paid job would instead wedge a failed one forever
    # (witnessed in a scratchpad harness 2026-09-07: a FAILED job's tag stayed
    # unresumable and unresubmittable across a fresh Transport on the same
    # ledger).
    path = getattr(t, "ledger_path", None)
    if not path or tag is None:
        return None
    for entry in _ledger_load(path).values():
        if entry.get("model_id") == model_id and entry.get("tag") == tag and not entry.get("failed"):
            return entry
    return None

def _ledger_mark_done(t, request_id, result):
    path = getattr(t, "ledger_path", None)
    if not path:
        return
    ledger = _ledger_load(path)
    if request_id in ledger:
        ledger[request_id]["done"] = True
        ledger[request_id]["result"] = result
        _ledger_save(path, ledger)

def _ledger_mark_failed(t, request_id, error):
    """Record a vendor-side FAILED/ERROR verdict on the ledger entry so its
    tag stops matching `_ledger_entry_by_tag` (pending_request_id/resume) and
    a later gen call is free to submit() a fresh job under the same tag,
    instead of the dead entry wedging it forever. Distinct from `done`: a
    failed entry is finished trying, not finished successfully, so `done`
    stays False and `result` stays None -- nothing downstream should ever read
    a failed entry's `result` as a real one."""
    path = getattr(t, "ledger_path", None)
    if not path:
        return
    ledger = _ledger_load(path)
    if request_id in ledger:
        ledger[request_id]["failed"] = True
        ledger[request_id]["error"] = str(error)
        _ledger_save(path, ledger)

def pending_request_id(model_id, tag, t):
    """The request id already recorded in t's ledger under (model_id, tag), if
    any and not marked failed -- finished or not. `tag` is caller-supplied and
    names one job uniquely within a manifest's ledger (the character name,
    "sky_pano", a kit prop key, ...). Stages that submit a paid job call this
    FIRST: a hit means the job was already paid for (by this process or a dead
    one) and must be waited on, never resubmitted. A vendor-side FAILED/ERROR
    entry under this tag does NOT count as pending -- it is excluded so the
    caller submits a fresh job instead of waiting on a request that already
    failed."""
    entry = _ledger_entry_by_tag(t, model_id, tag)
    return entry.get("request_id") if entry else None

def submit(model_id, payload, t, tag=None):
    out = t.json("POST", "%s/%s" % (QUEUE, model_id), payload)
    request_id = out["request_id"]
    submits = getattr(t, "last_submit", None)
    if not isinstance(submits, dict):
        submits = {}
        t.last_submit = submits
    submits[request_id] = out
    # Persist to the on-disk ledger BEFORE returning: the queue call above
    # already billed this request, so from this line on it must be
    # recoverable from disk, not only from this process's memory. Witnessed
    # 2026-09-07: a local network outage killed the orchestrator's driver
    # after 5 of 20 submitted Tripo jobs; the other 15 ids lived only in
    # `last_submit` and had to be resubmitted (3.00 USD duplicate) once fal
    # had already run them to completion.
    _ledger_write_submit(t, model_id, request_id, out, tag)
    return request_id

def base_app_id(model_id):
    """The queue path for a request is the BASE app id -- the first two path
    segments of the model id -- not the full subpath endpoint. Witnessed
    2026-09-04 on the bake-off rig legs: `fal-ai/meshy/rigging/multi-animation`
    answers at https://queue.fal.run/fal-ai/meshy/requests/<rid>, and the full
    subpath id is not a queue path at all. Used only for the constructed
    fallback URLs; a submit response's own status_url/response_url wins."""
    parts = [p for p in model_id.split("/") if p]
    return "/".join(parts[:2])


def _merge_metrics(status, out):
    # metrics.inference_time lives on the COMPLETED STATUS body, not on the response
    # body (https://fal.ai/docs/documentation/model-apis/inference/queue#check-status;
    # witnessed 2026-09-04 on bake-off leg A, whose mesh cost read "estimated" because
    # of it). Merge the status body's metrics in -- without overwriting a response
    # body that carries its own, which is the more specific number of the two -- so
    # a caller reading `metrics` off the returned dict sees them. No endpoint is
    # priced per compute second today (pricing.PRICES bills them all per
    # generation, image or credit), so nothing costs off this any more; it is the
    # only place the timing is reported at all.
    if isinstance(out, dict) and isinstance(status, dict) and status.get("metrics") and not out.get("metrics"):
        out = dict(out)
        out["metrics"] = status["metrics"]
    return out

def wait(model_id, request_id, t, timeout=600, poll_secs=3):
    # last_submit is keyed by request_id so an interleaved submit(A); submit(B); wait(A)
    # (the bake-off shape, two vendor calls on one shared transport) polls A's own
    # status/response URLs rather than whichever request happened to submit last.
    submits = getattr(t, "last_submit", None) or {}
    sub = submits.get(request_id)
    if sub is None:
        # Not in this process's memory -- a fresh process resuming a request id
        # from a dead driver, or `resume gen --resume <id>` with a bare
        # transport. Fall back to the on-disk ledger for the exact status_url/
        # response_url this request was submitted with, before falling further
        # back to the constructed base-app-id URL (which only works for a
        # subpath endpoint whose queue path happens to be its base app id).
        sub = _ledger_entry_by_id(t, request_id) or {}
    app = base_app_id(model_id)
    status_url = sub.get("status_url") or "%s/%s/requests/%s/status" % (QUEUE, app, request_id)
    response_url = sub.get("response_url") or "%s/%s/requests/%s" % (QUEUE, app, request_id)
    try:
        status = http.poll(lambda: t.json("GET", status_url), lambda o: o.get("status") == "COMPLETED",
                           lambda o: o.get("status") in ("FAILED", "ERROR") or o.get("error"), timeout, poll_secs)
    except RuntimeError as e:
        # http.poll's is_failed raised this -- a genuine vendor-side FAILED/ERROR
        # verdict, distinct from a TimeoutError (still running) or an HTTPError-
        # derived RuntimeError from t.json (a transport-level failure, which
        # leaves the entry alone so a retry can still resume it). Mark the
        # ledger entry failed BEFORE re-raising so its tag frees up for a fresh
        # submit() instead of wedging forever (see _ledger_entry_by_tag).
        if str(e).startswith("vendor task failed:"):
            _ledger_mark_failed(t, request_id, e)
        raise
    out = _merge_metrics(status, t.json("GET", response_url))
    _ledger_mark_done(t, request_id, out)
    return out

def resume(model_id, tag, t):
    """Non-blocking lookup for the stage-level "resume instead of resubmit"
    path: does (model_id, tag) already have a ledger entry, and is it done?

    - No matching entry: returns None (nothing to resume; the caller is free
      to submit()).
    - Entry already marked done (a prior wait()/resume() fetched it): returns
      the stored result with NO network call.
    - Entry exists but not yet done: makes exactly ONE status check (never a
      blocking poll loop) and returns the fetched result if the vendor now
      reports COMPLETED (marking the ledger done), or None if it is still
      queued/in progress -- the caller should fall back to
      `wait(model_id, pending_request_id(model_id, tag, t), t)` to actually
      block on it. Raises the same way wait() does if the vendor reports
      FAILED/ERROR, and -- like wait() -- marks the ledger entry failed first
      so the tag is free for a fresh submit() on the next call rather than
      wedged on this dead request forever.
    """
    entry = _ledger_entry_by_tag(t, model_id, tag)
    if entry is None:
        return None
    if entry.get("done"):
        return entry.get("result")
    status = t.json("GET", entry["status_url"])
    if status.get("status") in ("FAILED", "ERROR") or status.get("error"):
        error = "vendor task failed: %r" % status
        _ledger_mark_failed(t, entry["request_id"], error)
        raise RuntimeError(error)
    if status.get("status") != "COMPLETED":
        return None
    out = _merge_metrics(status, t.json("GET", entry["response_url"]))
    _ledger_mark_done(t, entry["request_id"], out)
    return out
