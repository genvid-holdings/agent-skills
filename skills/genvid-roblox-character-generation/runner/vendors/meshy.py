"""Meshy on fal: mesh, rig, rig+library clips. Schemas witnessed via the fal MCP 2026-09-03."""
from . import fal

MESH = "meshy/v7/multi-image-to-3d"
RIG = "fal-ai/meshy/rigging"
RIG_CLIPS = "fal-ai/meshy/rigging/multi-animation"

def transport(ledger_path=None):
    return fal.transport(ledger_path=ledger_path)

def multi_image_to_3d(image_urls, t, *, pose_mode="a-pose", topology="triangle", target_polycount=20000,
                      should_texture=True, enable_pbr=False, symmetry_mode="auto", tag=None):
    body = {"image_urls": list(image_urls)[:4], "pose_mode": pose_mode, "topology": topology,
            "target_polycount": target_polycount, "should_texture": should_texture,
            "enable_pbr": enable_pbr, "symmetry_mode": symmetry_mode, "should_remesh": True}
    return fal.submit(MESH, body, t, tag=tag)

def rig(model_url, t, *, height_meters=1.8, tag=None):
    return fal.submit(RIG, {"model_url": model_url, "height_meters": height_meters}, t, tag=tag)

def rig_with_clips(model_url, action_ids, t, *, height_meters=1.8, tag=None):
    ids = list(dict.fromkeys(int(i) for i in action_ids))
    if not ids or len(ids) > 10 or any(i < 0 or i > 696 for i in ids):
        raise ValueError("animation_action_ids: 1-10 distinct ids in [0, 696], got %r" % ids)
    return fal.submit(RIG_CLIPS, {"model_url": model_url, "height_meters": height_meters,
                                 "animation_action_ids": ids}, t, tag=tag)

def wait(model_id, request_id, t, timeout=1800, poll_secs=15):
    return fal.wait(model_id, request_id, t, timeout=timeout, poll_secs=poll_secs)

def clip_url(result, action_id):
    """GLB url of the library animation with this ACTION ID.

    Witnessed 2026-09-04 on the bake-off leg B rig request:
    each `animations[]` entry is `{action_id, animation_glb: {url, ...},
    animation_fbx: {...}}` -- there is no bare `url` key, and the entries do not
    come back in the requested order, so indexing `animations[i]` by the caller's
    position in `animation_action_ids` silently mislabels every clip (a Walk file
    holding the Attack take). Look the id up; raise naming what the vendor did
    return rather than guess. (The response also carries `basic_animations` --
    walking/running glb+fbx+armature -- which this runner does not use.)"""
    want = int(action_id)
    animations = result.get("animations") or []
    for a in animations:
        if a.get("action_id") is not None and int(a["action_id"]) == want:
            return a["animation_glb"]["url"]
    raise KeyError("no animation with action_id %d in the rig result; got %r"
                   % (want, [a.get("action_id") for a in animations]))


def result_url(result, key):
    if key.startswith("clip["):
        return clip_url(result, int(key[5:-1]))
    table = {"glb": "model_glb", "rig_glb": "rigged_character_glb", "rig_fbx": "rigged_character_fbx"}
    return result[table[key]]["url"]
