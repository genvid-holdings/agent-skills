"""Equirectangular panorama -> six cubemap face PNGs.

For each face, every output pixel's world direction is computed directly (a face
normal N plus a face-local right/down basis R/D), then inverse-mapped to the
equirect image's UV (`lat = asin(dir.y)`, `v = 0.5 - lat/pi`,
`u = (atan2(dir.x, -dir.z)/(2*pi) + 0.5) % 1`) and sampled nearest-neighbour.
Face orientation (the FACES table below) is a self-consistent, right-handed,
Y-up, INSIDE-VIEW convention: `ft` looks down -Z with R=+X/D=-Y, `rt` N=+X
R=+Z, `lf` N=-X R=-Z, `up` N=+Y R=+X D=-Z, `dn` N=-Y R=+X D=+Z. That table is
pure geometry and never needs to change for a target engine's slot layout --
only which cutter face lands in which output file, and how it's turned, does.

Roblox slot convention (WITNESSED 2026-09-05, against Roblox's own default sky:
the six `sky512_*.tex` DDS faces decoded out of the Studio app, edge-tested the
same way as the cutter's own faces): this module's previous header called the
yaw/roll fit against a live Roblox Sky "Studio-side visual" QA, which
undersold the gap. Measured against Roblox's own faces: the ft/bk/lf/rt ring
is a straight relabeling of the
cutter's ring with no mirror needed (ft.right->lf.left, lf.right->bk.left,
bk.right->rt.left, rt.right->ft.left, each 0.3-0.6 mean level), but the poles
do not fall out of the cutter's own naming -- ft.top meets up's RIGHT edge
(reversed), ft.bottom meets dn's RIGHT edge, rt.top meets up's bottom, lf.top
meets up's TOP edge (reversed), bk.top meets up's left. The fix, verified with
all nine resulting edge pairings continuous (0.2-5.2 mean levels) against the
real Roblox faces: output slot `lf` takes the cutter's +X face (named `rt` in
FACES above), slot `rt` takes the cutter's -X face (named `lf`), slot `up` is
the cutter's `up` face turned 90 degrees counter-clockwise, slot `dn` is the
cutter's `dn` face turned 90 degrees clockwise; `ft`/`bk` pass straight
through. ROBLOX_SLOTS below encodes exactly that remap, applied at save time
(after the FACES-table math, not instead of it) so the pure geometry stays
provably self-consistent on its own and the engine-specific remap stays a
small, separately testable step.

Run: blender --background --python equirect_to_cube.py -- sky_equirect.png out/faces 1024
Writes out_dir/face_{ft,bk,lf,rt,up,dn}.png (already in Roblox slot order/
orientation per ROBLOX_SLOTS). Prints exactly one line:
RUNNER_RESULT {"faces": {face: path, ...}, "mean_rgb": {face: [r, g, b], ...}}

bpy (and the maskutil helper, which itself imports bpy) are imported only if
present, and numpy the same way -- but that guard only keeps import from
blowing up without either dependency installed, not every function below.
FACES and the ROBLOX_SLOTS remap (remap_to_roblox_slots, _rot90_ccw,
_rotate_ccw) need neither bpy nor numpy and are unit-tested without either in
tests/test_runner_equirect_to_cube.py. The direction/UV math (_face_dirs,
_equirect_uv) calls numpy unconditionally, so it needs numpy installed
despite the guarded import, and it is exercised only end-to-end through
main() against a real synthetic equirect PNG cut by a real Blender, in
tests/test_runner_blender.py -- not unit-tested directly. Only main() itself
(the actual cutting, which also needs bpy to load/save images) requires a
real Blender.
"""
import json, math, sys
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pure-python mapping tests run without numpy installed
    np = None

try:
    import bpy
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    # Same top-down/bottom-up pixel convention maskutil.py's other callers rely on
    # (silhouette_iou.py, facing.py) -- reused here rather than re-derived so a
    # convention fix in one place can't leave this script silently disagreeing.
    from maskutil import load_rgba  # noqa: E402
except ImportError:  # pure-python mapping tests run without Blender installed
    bpy = None
    load_rgba = None

# name -> (N: face normal, R: face-local "right" / +a, D: face-local "down" / +b)
FACES = {
    "ft": ((0, 0, -1), (1, 0, 0), (0, -1, 0)),
    "bk": ((0, 0, 1), (-1, 0, 0), (0, -1, 0)),
    "rt": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "lf": ((-1, 0, 0), (0, 0, -1), (0, -1, 0)),
    "up": ((0, 1, 0), (1, 0, 0), (0, 0, -1)),
    "dn": ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
}

# output slot -> (FACES key to source from, quarter-turns counter-clockwise).
# See the module header ("Roblox slot convention", witnessed 2026-09-05) for
# how each entry was derived.
ROBLOX_SLOTS = {
    "ft": ("ft", 0),
    "bk": ("bk", 0),
    "lf": ("rt", 0),
    "rt": ("lf", 0),
    "up": ("up", 1),
    "dn": ("dn", -1),
}


def _rot90_ccw(face):
    """One 90-degree turn, counter-clockwise as viewed on screen (row 0 = top,
    col 0 = left). Pure Python, no numpy: works on a numpy (H, W, C) array or
    a plain nested list identically, via plain indexing. Equivalent to
    `numpy.rot90(arr, k=1)` for a top-down array -- verified by hand once
    (new[r][c] == old[c][w-1-r]) and pinned here instead of re-derived at
    review time."""
    h = len(face)
    w = len(face[0])
    return [[face[c][w - 1 - r] for c in range(h)] for r in range(w)]


def _rotate_ccw(face, quarter_turns):
    for _ in range(quarter_turns % 4):
        face = _rot90_ccw(face)
    return face


def remap_to_roblox_slots(faces):
    """faces: {FACES key: face} for all six FACES keys, each face indexable as
    face[row][col] (a numpy (H, W, C) array or a plain nested list both work).
    Returns {slot_name: face}, reoriented per ROBLOX_SLOTS -- the whole thing
    the module header's "Roblox slot convention" describes, pure Python and
    importable without Blender or numpy for unit testing."""
    return {slot: _rotate_ccw(faces[source], turns) for slot, (source, turns) in ROBLOX_SLOTS.items()}


def _face_dirs(n, r, d, size):
    """Unit direction vector per output pixel, shape (size, size, 3): axis 0
    walks the face's "down" (b) coordinate, axis 1 its "right" (a) coordinate --
    the same row-then-column layout as a top-down image array."""
    a = (np.arange(size, dtype=np.float64) + 0.5) / size * 2 - 1
    b = (np.arange(size, dtype=np.float64) + 0.5) / size * 2 - 1
    A, B = np.meshgrid(a, b)  # A varies along columns (a), B along rows (b)
    n = np.array(n, dtype=np.float64); r = np.array(r, dtype=np.float64); d = np.array(d, dtype=np.float64)
    dirs = n[None, None, :] + A[:, :, None] * r[None, None, :] + B[:, :, None] * d[None, None, :]
    norm = np.linalg.norm(dirs, axis=2, keepdims=True)
    return dirs / norm


def _equirect_uv(dirs):
    x, y, z = dirs[..., 0], dirs[..., 1], dirs[..., 2]
    lon = np.arctan2(x, -z)
    u = (lon / (2 * math.pi) + 0.5) % 1.0
    lat = np.arcsin(np.clip(y, -1.0, 1.0))
    v = 0.5 - lat / math.pi
    return u, v


def _save_face(name, rgb_face, out_dir):
    h, w = rgb_face.shape[0], rgb_face.shape[1]
    img = bpy.data.images.new(name, width=w, height=h)
    rgba = np.concatenate([rgb_face, np.ones((h, w, 1), dtype=np.float32)], axis=2)
    # rgb_face is top-down (row 0 = top, matching load_rgba's convention below);
    # Blender's own pixel buffer is bottom-up, so flip before assigning.
    img.pixels[:] = np.flipud(rgba).astype(np.float32).ravel()
    dest = Path(out_dir) / ("face_%s.png" % name)
    img.filepath_raw = str(dest)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return dest


def main():
    if bpy is None:
        raise RuntimeError(
            "equirect_to_cube.py needs a real Blender to cut faces -- run it via "
            "`blender --background --python equirect_to_cube.py -- <equirect> <out_dir> <size>`. "
            "FACES and remap_to_roblox_slots are importable and unit-tested without "
            "Blender or numpy; the direction/UV math additionally needs numpy at "
            "runtime and is only covered end-to-end via a real Blender.")
    argv = sys.argv[sys.argv.index("--") + 1:]
    equirect_path, out_dir, size = argv[0], argv[1], int(argv[2])

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    equirect_rgba = load_rgba(equirect_path)  # top-down (h, w, 4)
    eh, ew = equirect_rgba.shape[0], equirect_rgba.shape[1]
    equirect_rgb = equirect_rgba[:, :, :3]

    faces = {}
    for name, (n, r, d) in FACES.items():
        dirs = _face_dirs(n, r, d, size)
        u, v = _equirect_uv(dirs)
        col = np.clip((u * ew).astype(int), 0, ew - 1)
        row = np.clip((v * eh).astype(int), 0, eh - 1)
        faces[name] = equirect_rgb[row, col].astype(np.float32)

    slots = remap_to_roblox_slots(faces)

    out_faces = {}
    means = {}
    for slot_name, face_rgb in slots.items():
        face_rgb = np.asarray(face_rgb, dtype=np.float32)
        dest = _save_face(slot_name, face_rgb, out_dir)
        out_faces[slot_name] = str(dest)
        # Read the saved face back rather than trust the in-memory array -- the
        # same "measure what actually landed on disk" discipline maskutil's other
        # callers use, and it catches a save/round-trip bug this script's own math
        # would not.
        saved_rgb = load_rgba(str(dest))[:, :, :3]
        means[slot_name] = [float(x) for x in saved_rgb.reshape(-1, 3).mean(axis=0)]

    result = {"faces": out_faces, "mean_rgb": means}
    print("RUNNER_RESULT " + json.dumps(result))


if __name__ == "__main__":
    main()
