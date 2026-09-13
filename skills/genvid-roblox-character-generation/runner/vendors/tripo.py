"""Tripo3D. Primary path: tripo3d/h3.1/multiview-to-3d on fal (schema witnessed via the fal MCP
2026-09-03). Optional direct-API rig leg (bake-off leg C only), gated on TRIPO_API_KEY, against
https://api.tripo3d.ai/v2/openapi.

Task types witnessed on the live leg C run 2026-09-04: the guessed `check_riggable` /
`rig_model` spellings are REJECTED (HTTP 400, code 1003 "The request body is
malformed"). The two the API accepts are `animate_prerigcheck` ({type,
original_model_task_id} -> output {riggable, rig_type, topology}) and `animate_rig`
({type, original_model_task_id, out_format, spec, rig_type} -> output {model,
rendered_image}, 30 credits). Both take ONLY a Tripo original_model_task_id, never an
arbitrary GLB url. What `animate_rig` accepted, pinned here rather than probed at run
time: out_format fbx, spec mixamo, rig_type biped. rig_type also admits
quadruped|hexapod|octopod|avian|serpentine|aquatic|others and spec admits tripo, per
the 2026-09-02 API notes -- unwitnessed, so unused."""
import os
from . import fal, http

MESH = "tripo3d/h3.1/multiview-to-3d"
DIRECT_BASE = "https://api.tripo3d.ai/v2/openapi"

def transport(ledger_path=None):
    return fal.transport(ledger_path=ledger_path)

def multiview_to_model(image_urls, t, *, texture=True, pbr=False, face_limit=20000, texture_alignment="original_image", tag=None):
    body = {"image_urls": [image_urls["front"], image_urls["left"], image_urls["back"], image_urls["right"]],
            "texture": texture, "pbr": pbr, "face_limit": face_limit, "texture_alignment": texture_alignment}
    return fal.submit(MESH, body, t, tag=tag)

def wait(request_id, t, timeout=1800, poll_secs=15):
    return fal.wait(MESH, request_id, t, timeout=timeout, poll_secs=poll_secs)

def result_url(result):
    return result["model_mesh"]["url"]

# --- Optional direct-API rig leg (TRIPO_API_KEY only; bake-off leg C) ---

def direct_transport(ledger_path=None):
    return http.Transport({"Authorization": "Bearer " + os.environ["TRIPO_API_KEY"]}, ledger_path=ledger_path)

def direct_upload(path, t):
    return t.upload_multipart(DIRECT_BASE + "/upload", {}, "file", path)["data"]["image_token"]

def direct_multiview(tokens, t, *, texture=True, pbr=False, face_limit=20000):
    files = [{"type": "png", "file_token": tokens[k]} for k in ("front", "left", "back", "right")]
    body = {"type": "multiview_to_model", "files": files, "texture": texture, "pbr": pbr, "face_limit": face_limit}
    return t.json("POST", DIRECT_BASE + "/task", body)["data"]["task_id"]

def direct_wait(task_id, t, timeout=1800, poll_secs=15):
    url = "%s/task/%s" % (DIRECT_BASE, task_id)
    out = http.poll(lambda: t.json("GET", url), lambda o: o["data"]["status"] == "success",
                    lambda o: o["data"]["status"] in ("failed", "cancelled", "banned"), timeout, poll_secs)
    return out["data"]

# Task-type spellings the live leg C run accepted (2026-09-04). Named constants
# so a caller and its test read the same string: the rejected guesses
# ("check_riggable" / "rig_model") differed from these by a word each and cost a
# stranded run to find.
PRERIGCHECK_TYPE = "animate_prerigcheck"
RIG_TYPE_TASK = "animate_rig"

def direct_check_riggable(task_id, t, timeout=600):
    tid = t.json("POST", DIRECT_BASE + "/task",
                 {"type": PRERIGCHECK_TYPE, "original_model_task_id": task_id})["data"]["task_id"]
    return bool(direct_wait(tid, t, timeout)["output"]["riggable"])

def direct_rig(task_id, t, *, rig_type="biped", spec="mixamo", out_format="fbx"):
    body = {"type": RIG_TYPE_TASK, "original_model_task_id": task_id, "out_format": out_format,
            "rig_type": rig_type, "spec": spec}
    return t.json("POST", DIRECT_BASE + "/task", body)["data"]["task_id"]

def direct_result_url(task):
    out = task["output"]
    return out.get("model") or out.get("pbr_model") or out["model"]
