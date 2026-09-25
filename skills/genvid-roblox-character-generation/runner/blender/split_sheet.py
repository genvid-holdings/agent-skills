"""Sheet PNG -> equal-tile grid crop -> per-tile PNGs.

Run: blender --background --python split_sheet.py -- sheet.png out/tiles 4 3
Writes out_dir/prop_01.png .. prop_NN.png in row-major order (row 0 left-to-right,
then row 1, ...; NN = rows*cols, zero-padded to two digits). Prints exactly one line:
RUNNER_RESULT {"tiles": {"01": path, ...}, "mean_rgb": {"01": [r, g, b], ...}}

Equal-tile crop (Interfaces: "equal-tile crop"): each tile is exactly
sheet_h // rows by sheet_w // cols pixels, no overlap, no scaling -- a numpy slice
of the loaded sheet, saved via the same bpy.data.images.new + save round-trip
equirect_to_cube.py's _save_face already uses (and the same reason it reads the
saved file back rather than trusting the in-memory array: catches a save bug the
slicing math wouldn't).
"""
import json, sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Same top-down/bottom-up pixel convention maskutil.py's other callers rely on
# (equirect_to_cube.py, silhouette_iou.py, facing.py).
from maskutil import load_rgba  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
sheet_path, out_dir, rows, cols = argv[0], argv[1], int(argv[2]), int(argv[3])


def _save_tile(key, rgb_tile, out_dir):
    h, w = rgb_tile.shape[0], rgb_tile.shape[1]
    img = bpy.data.images.new("prop_" + key, width=w, height=h)
    rgba = np.concatenate([rgb_tile, np.ones((h, w, 1), dtype=np.float32)], axis=2)
    # rgb_tile is top-down (row 0 = top, load_rgba's convention); Blender's own
    # pixel buffer is bottom-up, so flip before assigning (equirect_to_cube.py's
    # _save_face does the identical flip for the identical reason).
    img.pixels[:] = np.flipud(rgba).astype(np.float32).ravel()
    dest = Path(out_dir) / ("prop_%s.png" % key)
    img.filepath_raw = str(dest)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return dest


def main():
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    sheet_rgba = load_rgba(sheet_path)  # top-down (h, w, 4)
    sh, sw = sheet_rgba.shape[0], sheet_rgba.shape[1]
    sheet_rgb = sheet_rgba[:, :, :3]
    th, tw = sh // rows, sw // cols

    tiles = {}
    means = {}
    n = 0
    for r in range(rows):
        for c in range(cols):
            n += 1
            key = "%02d" % n
            tile_rgb = sheet_rgb[r * th:(r + 1) * th, c * tw:(c + 1) * tw]
            dest = _save_tile(key, tile_rgb, out_dir)
            tiles[key] = str(dest)
            # Read the saved tile back rather than trust the in-memory slice --
            # same "measure what actually landed on disk" discipline as above.
            saved_rgb = load_rgba(str(dest))[:, :, :3]
            means[key] = [float(x) for x in saved_rgb.reshape(-1, 3).mean(axis=0)]

    result = {"tiles": tiles, "mean_rgb": means}
    print("RUNNER_RESULT " + json.dumps(result))


main()
