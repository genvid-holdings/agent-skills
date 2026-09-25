"""The emit/ingest seam every generating step shares.

The runner never calls a model. For each generating step:

    runner <group> emit   <step> --manifest M [--item K] --estimate <USD> [--model <text>] [--no-urls]
        -> gates the caller's estimate (budget.gate), writes
           <out>/requests/<stage>-<step>[-<item>].json and prints its path
    <the caller generates with any model and provider it chooses>
    runner <group> ingest <step> --manifest M [--item K] --provider <text> --model <text>
           [--params <JSON object>] (--cost <amount> [--currency <ISO-4217>] | --cost-unobserved)
           [--prompt <text>] [--render-type <T2I|I2I|I23D|T23D|RIG|T2MOTION>] [--input-media-id ID ...]
           [--record-only] [--supersede] [--unrequested "<reason>"] <file-or-url>
        -> validates the result and the attestation, records it at
           stages.<stage>.generated.<item>, then processes and binds it

A request document names the model TYPE, never a model. This module holds the
pieces every step uses: the request writer, the signed-URL inputs, the result
download and type sniff, the attestation, the ingest record with its
idempotency rule, and the bind arguments built from that record.
"""
import hashlib, json, struct, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
import ssl
from pathlib import Path
import manifest, genvid_bind, cost

SCHEMA = "genvid-runner-request/1"

# The render types an ingest may bind with (the boundary's RenderType values for
# generated stills, models, rigs and motions). A step with no boundary value of
# its own binds under the nearest one and names its model type in params.
RENDER_TYPES = ("T2I", "I2I", "I23D", "T23D", "RIG", "T2MOTION")

MIME = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp",
        "glb": "model/gltf-binary", "fbx": "application/octet-stream", "obj": "model/obj"}
IMAGE_KINDS = ("png", "jpeg", "webp")

# Wavefront OBJ is text with no magic bytes. A file is read as OBJ when its first
# statement (blank lines and comments skipped) is one of these keywords and a
# vertex line appears within the first OBJ_SNIFF_BYTES.
OBJ_KEYWORDS = (b"v", b"vt", b"vn", b"vp", b"f", b"o", b"g", b"s", b"mtllib", b"usemtl")
OBJ_SNIFF_BYTES = 1 << 16

COST_NOTE = ("The estimate and the attested cost are USD unless --currency says otherwise. Only USD "
             "counts toward project spend and budget headroom; attest another currency verbatim, or "
             "--cost-unobserved when the figure is not known.")
FREE_NOTE = ("A zero estimate still runs the budget check: it is a free read and required for every "
             "generation, a free one included.")

# Network-level failures get a bounded retry (6 tries, 5 s base, doubling). An
# HTTP error carries a real status and is not retried.
NETWORK_RETRY_TRIES = 6
NETWORK_RETRY_BASE_SECS = 5
NETWORK_ERRORS = (urllib.error.URLError, ConnectionResetError, TimeoutError, ssl.SSLError)
DOWNLOAD_TIMEOUT_SECS = 120


class IngestError(ValueError):
    """An emit or ingest refused before any governed write."""


# ---------------------------------------------------------------- request writer

def request_name(step, item=None):
    return "%s-%s" % (step, item) if item else str(step)


def request_path(m, stage, step, item=None):
    """Where a request is written. The stage is in the file name because steps
    repeat across stages (mesh and rig both emit `model`); a read follows the
    path recorded at `stages.<stage>.requests`, never this."""
    return Path(m["out_dir"]) / "requests" / ("%s-%s.json" % (stage, request_name(step, item)))


def ingest_command(m, group, step, item=None):
    """The ingest command line a request tells the caller to run, with placeholders."""
    parts = ["runner", group, "ingest", step]
    if item:
        parts += ["--item", str(item)]
    parts += ["--manifest", str(manifest.path_for(m)), "--provider <provider> --model <model>",
              "--cost <amount> | --cost-unobserved", "<file-or-url>"]
    return " ".join(parts)


def inputs(m, roles_ids, no_urls=False, run=subprocess.run):
    """The request's `inputs`: one entry per `(role, media_id)`, in order.

    With URLs (the default) each entry carries the signed download URL and its
    expiry from `get-media-signed-urls`; `no_urls` writes ids only, for a caller
    that fetches the media itself."""
    roles_ids = list(roles_ids)
    missing = [role for role, mid in roles_ids if mid in (None, "")]
    if missing:
        raise IngestError("no media id for input(s) %s: bind them before emitting this request"
                          % ", ".join(missing))
    if no_urls:
        return [{"role": role, "media_id": mid} for role, mid in roles_ids]
    signed = genvid_bind.signed_urls(m["project_id"], [mid for _r, mid in roles_ids], run=run)
    out = []
    for (role, _mid), entry in zip(roles_ids, signed):
        e = {"role": role, "media_id": entry["media_id"], "signed_url": entry["signed_url"]}
        for k in ("expires_at", "filename", "media_type"):
            if k in entry:
                e[k] = entry[k]
        out.append(e)
    return out


def write_request(m, stage, step, item, *, model_type, render_type, prompt, inputs, target,
                  must_satisfy, checked_at_ingest, budget_entry, ingest, extra=None):
    """Write the request document, record it at `stages.<stage>.requests`, save,
    and return its path. `budget_entry` is what `budget.gate` returned."""
    if render_type not in RENDER_TYPES:
        raise ValueError("render_type %r is not one of %s" % (render_type, ", ".join(RENDER_TYPES)))
    estimate = budget_entry.get("estimated_cost_usd")
    budget_block = {"estimate_usd": estimate, "fits": budget_entry.get("fits"),
                    "read": budget_entry.get("read")}
    try:
        if estimate is not None and float(estimate) == 0:
            budget_block["note"] = FREE_NOTE
    except (TypeError, ValueError):
        pass
    doc = {
        "schema": SCHEMA, "stage": stage, "step": step, "item": item,
        "model_type": model_type, "render_type": render_type, "prompt": prompt,
        "inputs": list(inputs), "target": target, "must_satisfy": list(must_satisfy),
        "checked_at_ingest": list(checked_at_ingest), "budget": budget_block,
        "cost_note": COST_NOTE, "vendor_hint": m.get("vendor"), "ingest": ingest,
    }
    if extra:
        doc.update(extra)
    p = request_path(m, stage, step, item)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2))
    entry = manifest.set_stage(m, stage)
    entry.setdefault("requests", {})[request_name(step, item)] = str(p)
    manifest.save(m)
    return p


def require_request(m, stage, step, item=None, unrequested=None, group=None, emit_args=None):
    """The emitted request's path for `(step, item)`: the proof the budget gate ran.

    Refuses when none was emitted, unless `unrequested` gives a reason, which is
    recorded as a manifest note (and None returned). Also refuses when the recorded
    file is missing or holds another stage's or step's request (a manifest written
    while mesh and rig shared requests/model.json). `group` is the CLI group the
    fix is run under, when it is not the stage's name (a group whose steps
    live on another group's stages), and `emit_args` any arguments that
    emit needs to name this item (such as `--prop 01`)."""
    name = request_name(step, item)
    path = ((m["stages"].get(stage) or {}).get("requests") or {}).get(name)
    if path:
        rerun = "re-run `%s emit %s%s`" % (group or stage, step, " " + emit_args if emit_args else "")
        try:
            doc = json.loads(Path(path).read_text())
        except (OSError, ValueError) as e:
            raise IngestError("the request recorded for %s %s cannot be read (%s): %s" % (stage, name, e, rerun))
        found = (doc.get("stage"), doc.get("step")) if isinstance(doc, dict) else (None, None)
        if found != (stage, step):
            raise IngestError("the request recorded for %s %s at %s is for %s %s, not %s %s: %s"
                              % (stage, name, path, found[0], found[1], stage, step, rerun))
        return path
    if unrequested is not None:
        if not str(unrequested).strip():
            raise IngestError("--unrequested needs a reason")
        manifest.note(m, "%s ingest %s: no emitted request; ingested unrequested: %s" % (stage, name, unrequested))
        return None
    raise IngestError("no emitted request for %s %s: run `emit` first (it runs the budget check), or pass "
                      "--unrequested \"<reason>\"" % (stage, name))


# ---------------------------------------------------------------- the result

def _is_obj(head):
    if b"\x00" in head:
        return False
    lines = [l.strip() for l in head.splitlines()]
    statements = [l for l in lines if l and not l.startswith(b"#")]
    if not statements or statements[0].split()[0] not in OBJ_KEYWORDS:
        return False
    return any(l.startswith(b"v ") or l.startswith(b"v\t") for l in statements)


def sniff(path):
    """The artifact kind: png, jpeg, webp, glb or fbx (binary) by magic bytes,
    obj by its statements (OBJ is text), or None."""
    with open(path, "rb") as f:
        head = f.read(32)
        more = f.read(OBJ_SNIFF_BYTES - len(head))
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"glTF"):
        return "glb"
    if head.startswith(b"Kaydara FBX Binary"):
        return "fbx"
    if _is_obj(head + more):
        return "obj"
    return None


def check_kind(path, allowed):
    """The artifact's kind if it is one of `allowed`; raises IngestError otherwise."""
    kind = sniff(path)
    if kind not in allowed:
        raise IngestError("%s is %s, not %s: convert first" % (path, kind or "an unrecognised type",
                                                                " or ".join(allowed)))
    return kind


def _jpeg_size(f):
    f.seek(2)
    while True:
        b = f.read(1)
        while b and b != b"\xff":
            b = f.read(1)
        while b == b"\xff":
            b = f.read(1)
        if not b:
            return None
        marker = b[0]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        seg = f.read(2)
        if len(seg) < 2:
            return None
        length = struct.unpack(">H", seg)[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            data = f.read(5)
            if len(data) < 5:
                return None
            h, w = struct.unpack(">HH", data[1:5])
            return (w, h)
        f.seek(length - 2, 1)


def _webp_size(head):
    chunk = head[12:16]
    if chunk == b"VP8X" and len(head) >= 30:
        return (int.from_bytes(head[24:27], "little") + 1, int.from_bytes(head[27:30], "little") + 1)
    if chunk == b"VP8 " and len(head) >= 30:
        w, h = struct.unpack("<HH", head[26:30])
        return (w & 0x3FFF, h & 0x3FFF)
    if chunk == b"VP8L" and len(head) >= 25:
        bits = int.from_bytes(head[21:25], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    return None


def image_size(path, kind=None):
    """`(width, height)` of a PNG, JPEG or WebP image; None for anything else.
    `kind` skips the sniff when the caller already has it."""
    kind = kind or sniff(path)
    with open(path, "rb") as f:
        if kind == "png":
            head = f.read(24)
            return tuple(struct.unpack(">II", head[16:24])) if len(head) >= 24 else None
        if kind == "jpeg":
            return _jpeg_size(f)
        if kind == "webp":
            return _webp_size(f.read(30))
    return None


def download(url, dest, opener=None, sleep=time.sleep):
    """Fetch `url` into `dest` with no credentials, retrying network failures."""
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise IngestError("result URL %r is not http(s)" % url)
    opener = opener or urllib.request.urlopen
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, method="GET")
    for i in range(NETWORK_RETRY_TRIES):
        try:
            with opener(req, timeout=DOWNLOAD_TIMEOUT_SECS) as resp:
                dest.write_bytes(resp.read())
            return dest
        except urllib.error.HTTPError:
            raise
        except NETWORK_ERRORS as e:
            if i == NETWORK_RETRY_TRIES - 1:
                raise
            delay = NETWORK_RETRY_BASE_SECS * (2 ** i)
            print("runner download: network error (%r), retry %d/%d in %ss"
                  % (e, i + 1, NETWORK_RETRY_TRIES, delay), file=sys.stderr)
            sleep(delay)
    return dest


def resolve_result(src, dest, opener=None, sleep=time.sleep):
    """`(local_path, source_url)` for an ingest's result argument.

    A local path is used as is (`source_url` None); an http(s) URL is downloaded
    to `dest` (the step's own file name in the out dir) and returned with it."""
    src = str(src)
    if urllib.parse.urlparse(src).scheme.lower() in ("http", "https"):
        return download(src, dest, opener=opener, sleep=sleep), src
    p = Path(src)
    if not p.is_file():
        raise IngestError("result %s does not exist" % src)
    return p, None


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- attestation

def attestation(provider, model, params=None, cost_amount=None, currency="USD", unobserved=False):
    """The caller's attestation, validated: free-text provider and model, a params
    object, and exactly one of an attested cost and unobserved."""
    if not isinstance(provider, str) or not provider.strip():
        raise IngestError("--provider is required: the provider that ran the model")
    if not isinstance(model, str) or not model.strip():
        raise IngestError("--model is required: the model the provider ran")
    if params is None or params == "":
        parsed = {}
    elif isinstance(params, dict):
        parsed = dict(params)
    else:
        try:
            parsed = json.loads(params)
        except (TypeError, ValueError) as e:
            raise IngestError("--params is not valid JSON: %s" % e)
        if not isinstance(parsed, dict):
            raise IngestError("--params must be a JSON object")
    try:
        c = cost.record(cost_amount, currency=currency, unobserved=unobserved)
    except cost.CostError as e:
        raise IngestError(str(e))
    return {"model_provider": provider.strip(), "model_name": model.strip(), "params": parsed, "cost": c}


def attestation_from_args(args):
    return attestation(args.provider, args.model, args.params, cost_amount=args.cost,
                       currency=args.currency, unobserved=args.cost_unobserved)


# ---------------------------------------------------------------- the record

def make_record(*, artifact, source_url, attestation, prompt, render_type, input_media_ids,
                request_path, vendor_hint):
    """The ingest record for one item (stored at `generated.<item>`)."""
    if render_type not in RENDER_TYPES:
        raise IngestError("render type %r is not one of %s" % (render_type, ", ".join(RENDER_TYPES)))
    artifact = Path(artifact)
    kind = sniff(artifact)
    size = image_size(artifact, kind) if kind in IMAGE_KINDS else None
    return {
        "artifact": str(artifact), "source_url": source_url, "sha256": sha256_of(artifact),
        "mime": MIME.get(kind or ""), "size_px": list(size) if size else None,
        "model_provider": attestation["model_provider"], "model_name": attestation["model_name"],
        "params": dict(attestation["params"]), "prompt": prompt, "render_type": render_type,
        "input_media_ids": [str(i) for i in input_media_ids], "cost": dict(attestation["cost"]),
        "request": str(request_path) if request_path else None, "vendor_hint": vendor_hint,
    }


def generated_of(m, stage):
    """The `generated` map on a stage entry, created if absent."""
    return manifest.set_stage(m, stage).setdefault("generated", {})


def put_outcome(item, prior, rec, bound_media_id=None, supersede=False):
    """What `put_record` would do with `rec` over `prior`, without doing it:
    "unchanged", "recorded", "replaced" or "superseded". Raises IngestError for
    different bytes over a bound item without `supersede`."""
    if prior and prior.get("sha256") == rec["sha256"]:
        return "unchanged"
    if bound_media_id and not supersede:
        raise IngestError("%s is already bound as media %s with different bytes: pass --supersede to bind "
                          "the new result as a new row that supersedes it" % (item, bound_media_id))
    if bound_media_id:
        return "superseded"
    return "replaced" if prior else "recorded"


def put_record(m, container, item, rec, bound_media_id=None, supersede=False):
    """Store `rec` at `container[item]` and save the manifest.

    Returns "recorded", "replaced" (different bytes over an unbound record),
    "superseded" (different bytes over a bound item, with `supersede`) or
    "unchanged" (the same bytes are already recorded; a no-op with a note).
    Different bytes for an item already bound (`bound_media_id`) are refused
    unless `supersede`, which records the id being superseded; nothing is deleted."""
    prior = container.get(item)
    outcome = put_outcome(item, prior, rec, bound_media_id, supersede)
    if outcome == "unchanged":
        manifest.note(m, "ingest %s: these bytes are already recorded (sha256 %s); nothing changed"
                         % (item, rec["sha256"][:12]))
        manifest.save(m)
        return outcome
    rec = dict(rec)
    if outcome == "superseded":
        rec["supersedes_media_id"] = str(bound_media_id)
        manifest.note(m, "ingest %s: new bytes (sha256 %s) supersede bound media %s"
                         % (item, rec["sha256"][:12], bound_media_id))
    elif outcome == "replaced":
        manifest.note(m, "ingest %s: replaced an unbound record (sha256 %s, cost %r) with new bytes"
                         % (item, str(prior.get("sha256"))[:12], prior.get("cost")))
    container[item] = rec
    manifest.save(m)
    return outcome


def record_result(m, stage, item, result, make, *, stem, ext, check, bound_media_id=None, supersede=False,
                  opener=None, container=None):
    """Resolve, check and record one ingest result at `stages.<stage>.generated.<item>`,
    or at `container[item]` when a step keeps its records elsewhere (a dict inside
    `m`, such as `stages.kit.props.<prop>.generated`); returns the put_record outcome.

    `check(path)` returns the result's kind (raising IngestError to refuse it);
    `make(path, url, kind)` builds the record (make_record). A URL result is
    downloaded to `<out>/<stem>.download` and moved onto `<out>/<stem><ext[kind]>`
    only once everything that can refuse it has passed, and BEFORE the record is
    saved, so a saved record never names the staging file and a refused ingest
    leaves an already-recorded artifact intact. A local result is recorded where it is."""
    out = Path(m["out_dir"])
    path, url = resolve_result(result, out / (stem + ".download"), opener=opener)
    try:
        kind = check(path)
        rec = make(path, url, kind)
        prior = (container if container is not None
                 else ((m["stages"].get(stage) or {}).get("generated") or {})).get(item)
        outcome = put_outcome(item, prior, rec, bound_media_id, supersede)
    except Exception:
        if url:
            path.unlink(missing_ok=True)
        raise
    if url:
        if outcome == "unchanged":
            path.unlink()
        else:
            rec["artifact"] = str(path.replace(out / (stem + ext[kind])))
    return put_record(m, container if container is not None else generated_of(m, stage), item, rec,
                      bound_media_id=bound_media_id, supersede=supersede)


def bind_kwargs(rec, runner=None, artifact=None):
    """`genvid_bind.import_media` keyword arguments attested from the record.

    Provider, model, render type, prompt, input media ids and cost all come from
    the record, never a literal. The caller's params are kept; the runner's own
    measurements go under `params.runner`, which also carries the result URL.
    A URL result binds by `source_url` with the downloaded file as the multipart
    fallback; a step that processed the result passes that file as `artifact`,
    which is bound instead."""
    params = dict(rec.get("params") or {})
    params["runner"] = dict(runner or {}, source_url=rec.get("source_url"))
    if rec.get("supersedes_media_id"):
        params["supersedes_media_id"] = rec["supersedes_media_id"]
    kw = {"model_provider": rec["model_provider"], "model_name": rec["model_name"],
          "render_type": rec["render_type"], "prompt": rec.get("prompt") or "", "params": params,
          "input_media_ids": list(rec.get("input_media_ids") or []), "cost": dict(rec["cost"])}
    if artifact is not None:
        kw["path"] = str(artifact)
    elif rec.get("source_url"):
        kw["source_url"] = rec["source_url"]
        kw["fallback_path"] = rec["artifact"]
    else:
        kw["path"] = rec["artifact"]
    return kw


# ---------------------------------------------------------------- CLI flags

def add_emit_args(p, item_help="the item this request is for"):
    p.add_argument("--manifest", required=True)
    p.add_argument("--item", help=item_help)
    p.add_argument("--estimate", required=True,
                   help="your estimate in USD of what this generation will cost; gated against the Genvid "
                        "budget before anything is generated (0 for a free model)")
    p.add_argument("--model", help="optional: the model you intend to run; recorded with the budget verdict "
                                   "so a change of model gates again. Never required, never checked")
    p.add_argument("--no-urls", action="store_true",
                   help="write input media ids only, without signed download URLs")
    return p


def add_ingest_args(p, item_help="the item this result is for", positional=True):
    """The shared ingest flags. `positional=False` leaves out the `result`
    argument, for a step that names its files with its own flags."""
    p.add_argument("--manifest", required=True)
    p.add_argument("--item", help=item_help)
    p.add_argument("--provider", required=True, help="the provider that ran the model (any value)")
    p.add_argument("--model", required=True, help="the model the provider ran (any value)")
    p.add_argument("--params", help="the generation parameters you used, as a JSON object")
    c = p.add_mutually_exclusive_group(required=True)
    c.add_argument("--cost", help="what the generation cost, as a decimal amount (0 for a free one)")
    c.add_argument("--cost-unobserved", action="store_true",
                   help="the generation was charged but the amount is not known; recorded as unknown")
    p.add_argument("--currency", default="USD", help="ISO 4217 code for --cost (default USD)")
    p.add_argument("--prompt", help="the prompt you sent, when it differs from the emitted one; \"\" records that the model took no prompt")
    p.add_argument("--render-type", choices=RENDER_TYPES, help="override the emitted render type")
    p.add_argument("--input-media-id", action="append", default=[],
                   help="a Genvid media id the result was generated from (repeatable)")
    p.add_argument("--record-only", action="store_true", help="record the result without processing or binding it")
    p.add_argument("--supersede", action="store_true",
                   help="bind different bytes for an item that is already bound, as a new row that supersedes it")
    p.add_argument("--unrequested", metavar="REASON",
                   help="ingest a result no request was emitted for, recording why")
    if positional:
        p.add_argument("result", help="the result: a local file or an http(s) URL")
    return p

