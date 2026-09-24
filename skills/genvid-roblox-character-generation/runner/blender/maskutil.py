"""Silhouette/mask helpers shared by the runner's Blender-side measurements
(blender/silhouette_iou.py and blender/facing.py).

Both scripts render a mesh and compare it against the approved plate, and both
need the same four operations: read a rendered PNG, separate foreground from a
flat background, crop each side to its own subject, and score the overlap. They
lived in silhouette_iou.py alone until facing.py needed the identical maths;
copying them would have let the two measurements drift apart while still
reporting numbers that look comparable.

Blender-only (imports bpy and numpy); the runner's stdlib-only modules never
import this.
"""
import bpy
import numpy as np

# plan-pinned: foreground = further than 18/255 from the border-median color
BORDER_THRESHOLD = 18.0 / 255.0


def load_rgba(path):
    """Rendered/stored PNG as a top-down float array of shape (h, w, 4)."""
    img = bpy.data.images.load(path)
    w, h = img.size[0], img.size[1]
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, -1)
    if px.shape[2] < 4:  # pad an RGB image with an opaque alpha
        px = np.concatenate([px, np.ones((h, w, 4 - px.shape[2]), dtype=np.float32)], axis=2)
    bpy.data.images.remove(img)
    return np.flipud(px[:, :, :4])  # Blender stores images bottom-up


def load_rgb(path):
    return load_rgba(path)[:, :, :3]


# Width of the left and right edge strips the background is read from.
EDGE_STRIP_FRAC = 0.025
# Height each side's background is smoothed over (a running median down the
# column). A figure touching one edge, or both, over fewer rows than half this
# is read through rather than taken for background.
EDGE_SMOOTH_FRAC = 0.25


class BackgroundUnreadable(ValueError):
    """A plate whose background cannot be read at its side edges."""


def _longest_run(flags):
    """(first, last) index of the longest run of True in `flags`, or None."""
    best, start = None, None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if best is None or i - 1 - start > best[1] - best[0]:
                best = (start, i - 1)
            start = None
    return best


def _running_median(v, window):
    """Median of each row's `window` neighbours, down the rows of `v` (h, c)."""
    half = window // 2
    padded = np.pad(v, ((half, half), (0, 0)), mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(padded, window, axis=0), axis=-1)


def background(rgb):
    """The plate's background color at every pixel, (h, w, 3). Each side's color
    is the median of its edge strip per row, smoothed down the column; each row
    interpolates from its left color to its right one. One median over the whole
    border misreads a plate painted on a gradient: on one front plate
    (2026-09-23) it marked 70% of the frame as foreground with a full-frame bbox,
    and facing.py turned the mesh to a side profile."""
    h, w = rgb.shape[:2]
    strip = max(1, int(round(w * EDGE_STRIP_FRAC)))
    window = max(1, int(round(h * EDGE_SMOOTH_FRAC))) | 1
    left = _running_median(np.median(rgb[:, :strip, :], axis=1), window)
    right = _running_median(np.median(rgb[:, -strip:, :], axis=1), window)
    # A clean background differs side to side by one steady offset (zero unless
    # it is shaded across). A subject touching one edge over more rows than the
    # smoothing reads through becomes that side's background, which breaks the
    # offset over one unbroken run at least that long: refused, not guessed.
    # Shorter breaks (a tilted floor line, noise) are read through as before.
    diff = left - right
    off = np.sqrt(np.sum((diff - np.median(diff, axis=0)) ** 2, axis=-1)) / np.sqrt(3.0)
    run = _longest_run(off > BORDER_THRESHOLD)
    if run and run[1] - run[0] + 1 > window // 2:
        raise BackgroundUnreadable(
            "the plate's left and right backgrounds disagree over rows %d-%d of %d, an unbroken run longer than "
            "the %d rows the edge smoothing reads through: either the subject touches a side edge there or the "
            "background is shaded differently on the two sides; the plate needs a plain background with a "
            "margin on both sides" % (run[0], run[1], h, window // 2))
    t = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :, None]
    return left[:, None, :] * (1.0 - t) + right[:, None, :] * t


def foreground_mask(rgb):
    """Foreground of a plain-background image: everything far enough from the
    background color at that pixel. This is what a PLATE needs -- it has no
    alpha. On a flat background with the subject clear of both side edges it is
    the same mask one border median gives; raises BackgroundUnreadable when the
    subject runs off a side edge (see background())."""
    dist = np.sqrt(np.sum((rgb - background(rgb)) ** 2, axis=-1)) / np.sqrt(3.0)
    return dist > BORDER_THRESHOLD


def alpha_mask(rgba, threshold=0.5):
    """Foreground of a render made with film_transparent: the alpha channel.
    Unambiguous where a dark texture would otherwise read as background."""
    return rgba[:, :, 3] > threshold


def bbox(mask):
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any() or not cols.any():
        return None
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    return int(r0), int(r1), int(c0), int(c1)


def crop_to_bbox(mask):
    box = bbox(mask)
    if box is None:
        return mask[0:0, 0:0]
    r0, r1, c0, c1 = box
    return mask[r0:r1 + 1, c0:c1 + 1]


def resize_nearest(mask, out_h, out_w):
    h, w = mask.shape[:2]
    if h == 0 or w == 0 or out_h <= 0 or out_w <= 0:
        return np.zeros((max(out_h, 0), max(out_w, 0)) + mask.shape[2:], dtype=mask.dtype)
    row_idx = (np.arange(out_h) * h / out_h).astype(int).clip(0, h - 1)
    col_idx = (np.arange(out_w) * w / out_w).astype(int).clip(0, w - 1)
    return mask[row_idx][:, col_idx]


def iou(mask_a, mask_b):
    """Crop both to their own bbox, scale both to the smaller crop's height
    (keeping each crop's own aspect ratio), center them in a shared canvas, IoU."""
    a = crop_to_bbox(mask_a)
    b = crop_to_bbox(mask_b)
    if a.size == 0 or b.size == 0:
        return 0.0
    target_h = min(a.shape[0], b.shape[0])
    aw = max(1, round(a.shape[1] * target_h / a.shape[0]))
    bw = max(1, round(b.shape[1] * target_h / b.shape[0]))
    a2 = resize_nearest(a, target_h, aw)
    b2 = resize_nearest(b, target_h, bw)
    canvas_w = max(aw, bw)
    A = np.zeros((target_h, canvas_w), dtype=bool)
    B = np.zeros((target_h, canvas_w), dtype=bool)
    a_off = (canvas_w - aw) // 2
    b_off = (canvas_w - bw) // 2
    A[:, a_off:a_off + aw] = a2
    B[:, b_off:b_off + bw] = b2
    inter = np.logical_and(A, B).sum()
    union = np.logical_or(A, B).sum()
    return float(inter) / float(union) if union else 0.0


def head_patch(rgb, mask, band=0.25, size=32):
    """The subject's head region as a fixed `size` x `size` RGB patch, or None.

    The top `band` of the subject's own bounding box, cropped to that box's
    width, resized so two images of different resolutions are comparable
    pixel-for-pixel. Background pixels are carried as the border/transparent
    color they already hold; the comparison below is over the whole patch, so a
    silhouette difference in the head region counts too.
    """
    box = bbox(mask)
    if box is None:
        return None
    r0, r1, c0, c1 = box
    height = r1 - r0 + 1
    band_end = r0 + max(1, int(round(height * band)))
    patch = rgb[r0:band_end, c0:c1 + 1, :]
    if patch.size == 0:
        return None
    return resize_nearest(patch, size, size)


def patch_distance(a, b):
    """Mean per-pixel RGB distance between two patches, in [0, sqrt(3)].

    Front and back of a symmetric character are a silhouette tie (0.449 vs 0.448
    on bake-off leg B), so the discriminator has to be COLOR. Plain mean distance
    rather than normalized cross-correlation: NCC is undefined on a flat-colored
    region, which is exactly the case a stylized giant character's head presents.
    """
    if a is None or b is None:
        return None
    return float(np.mean(np.sqrt(np.sum((a - b) ** 2, axis=-1))))


def patch_ncc(a, b):
    """Normalized cross-correlation of two patches' luminance, or None where
    either side is flat (zero variance). Recorded beside patch_distance as
    evidence, never as the decision on its own."""
    if a is None or b is None:
        return None
    la = np.mean(a, axis=-1).ravel()
    lb = np.mean(b, axis=-1).ravel()
    la = la - la.mean()
    lb = lb - lb.mean()
    denom = float(np.sqrt(np.sum(la * la) * np.sum(lb * lb)))
    if denom < 1e-9:
        return None
    return float(np.sum(la * lb) / denom)
