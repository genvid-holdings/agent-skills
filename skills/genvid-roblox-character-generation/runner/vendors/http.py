"""urllib JSON transport with bounded retries, plus a FakeTransport for tests."""
import json, ssl, sys, time, urllib.request, urllib.error, uuid
from pathlib import Path

RETRY_STATUSES = (429, 500, 502, 503, 504)
BACKOFF = (2, 4, 8)

# Network-level failures (no HTTP response at all -- the socket died, DNS
# blipped, a TLS session dropped mid-read) get their OWN bounded retry, separate
# from RETRY_STATUSES above: an HTTPError carries a real status from fal and
# keeps its existing semantics (retried only for RETRY_STATUSES, never for a
# plain 4xx/5xx). Witnessed 2026-09-05: fal.wait raised a bare URLError mid-poll
# with no retry at all, ending the whole run on one blip. (A separate outage on
# 2026-09-07 killed the orchestrator's driver after 5 of 20 submitted Tripo
# jobs, but that witness names no mechanism -- see fal.py's ledger for that fix.)
NETWORK_RETRY_TRIES = 6
NETWORK_RETRY_BASE_SECS = 5
NETWORK_ERRORS = (urllib.error.URLError, ConnectionResetError, TimeoutError, ssl.SSLError)

def _retry_network(fn):
    """Call fn() with bounded exponential backoff (6 tries, 5s base, doubling)
    on a NETWORK_ERRORS failure; re-raises immediately on an HTTPError (that is
    a real HTTP status, RETRY_STATUSES/RuntimeError above decide its fate, not
    this) and re-raises the last network error once tries are exhausted. Each
    retry is logged to stderr so a stuck driver's log shows why it is slow
    rather than silently hanging."""
    last = None
    for i in range(NETWORK_RETRY_TRIES):
        try:
            return fn()
        except urllib.error.HTTPError:
            raise
        except NETWORK_ERRORS as e:
            last = e
            if i == NETWORK_RETRY_TRIES - 1:
                raise
            delay = NETWORK_RETRY_BASE_SECS * (2 ** i)
            print("runner http: network error (%r), retry %d/%d in %ss" %
                  (e, i + 1, NETWORK_RETRY_TRIES, delay), file=sys.stderr)
            time.sleep(delay)
    raise last

class Transport:
    def __init__(self, base_headers=None, ledger_path=None):
        self.base_headers = dict(base_headers or {})
        self.calls = []
        # Where vendors/fal.py's submit()/wait() persist fal request ids
        # (model_id, request_id, status_url, response_url, submitted_at, tag) so
        # a dead driver never loses a paid job's id -- None (the default) keeps
        # the old in-memory-only behaviour (last_submit) for tests and any
        # caller that has not opted in.
        self.ledger_path = ledger_path
    def json(self, method, url, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        hdrs = dict(self.base_headers); hdrs.update(headers or {})
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
        self.calls.append({"method": method, "url": url, "body": body})
        last = None
        for i in range(len(BACKOFF) + 1):
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            def _send():
                with urllib.request.urlopen(req, timeout=120) as r:
                    text = r.read().decode()
                    return json.loads(text) if text else {}
            try:
                return _retry_network(_send)
            except urllib.error.HTTPError as e:
                last = e
                if e.code not in RETRY_STATUSES or i == len(BACKOFF):
                    raise RuntimeError("%s %s -> %s: %s" % (method, url, e.code, e.read().decode()[:400]))
                time.sleep(BACKOFF[i])
        raise RuntimeError("unreachable: %r" % last)
    def download(self, url, dest):
        dest = Path(dest); dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers=self.base_headers)
        with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk: break
                f.write(chunk)
        return dest
    @staticmethod
    def _put_headers(content_type):
        # Presigned upload URLs (fal's storage/upload flow) reject a second auth mechanism,
        # so this sends ONLY Content-Type — base_headers' Authorization never goes on this call.
        # Single source of truth: FakeTransport.put_bytes below calls this too, so a
        # regression here (e.g. reverting to dict(self.base_headers)) shows up in the
        # fake-transport tests as well as the real-Transport one.
        return {"Content-Type": content_type}
    def put_bytes(self, url, data, content_type="application/octet-stream"):
        hdrs = self._put_headers(content_type)
        self.calls.append({"method": "PUT", "url": url, "body": {"bytes": len(data)}, "headers": dict(hdrs)})
        req = urllib.request.Request(url, data=data, method="PUT", headers=hdrs)
        with urllib.request.urlopen(req, timeout=600) as r:
            text = r.read().decode()
            return json.loads(text) if text else {}
    def upload_multipart(self, url, fields, file_field, file_path):
        boundary = "----runner" + uuid.uuid4().hex
        body = b""
        for k, v in fields.items():
            body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode()
        p = Path(file_path)
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n" % (boundary, file_field, p.name)).encode()
        body += p.read_bytes() + ("\r\n--%s--\r\n" % boundary).encode()
        hdrs = dict(self.base_headers); hdrs["Content-Type"] = "multipart/form-data; boundary=%s" % boundary
        self.calls.append({"method": "POST", "url": url, "body": {"file": str(p)}})
        req = urllib.request.Request(url, data=body, method="POST", headers=hdrs)
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read().decode())

class FakeTransport(Transport):
    def __init__(self, script, ledger_path=None):
        super().__init__(ledger_path=ledger_path)
        self.script = list(script)
    def json(self, method, url, body=None, headers=None):
        self.calls.append({"method": method, "url": url, "body": body})
        if not self.script:
            raise AssertionError("FakeTransport exhausted at %s %s" % (method, url))
        item = self.script.pop(0)
        # A script entry that IS an exception instance is raised rather than
        # returned -- how tests simulate a network error (or any other
        # failure) at a specific point in a submit/poll sequence.
        if isinstance(item, BaseException):
            raise item
        return item
    def download(self, url, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True); Path(dest).write_bytes(b"fake"); return Path(dest)
    def put_bytes(self, url, data, content_type="application/octet-stream"):
        hdrs = self._put_headers(content_type)
        self.calls.append({"method": "PUT", "url": url, "body": {"bytes": len(data)}, "headers": dict(hdrs)})
        return {}
    def upload_multipart(self, url, fields, file_field, file_path):
        return self.json("POST", url, {"file": str(file_path)})

def poll(fetch, is_done, is_failed, timeout, poll_secs):
    t0 = time.time()
    while True:
        out = _retry_network(fetch)
        if is_failed(out):
            raise RuntimeError("vendor task failed: %r" % out)
        if is_done(out):
            return out
        if time.time() - t0 > timeout:
            raise TimeoutError("vendor task still running after %ss" % timeout)
        time.sleep(poll_secs)
