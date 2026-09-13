"""Stage 4 math: HipHeight from bone geometry (spec §2.1 stage 4)."""


def hip_height(root_y, feet_plane_y, root_size_y):
    return (root_y - feet_plane_y) - root_size_y / 2.0


def root_box(height_studs):
    """HumanoidRootPart size for a character `height_studs` tall.

    Derived from BODY HEIGHT, not from spine spacing. The earlier rule --
    `h = 2 * (UpperTorso.Y - LowerTorso.Y)` -- read the gap between two bones,
    and that gap is a property of the SKELETON, not of the body: a Mixamo-
    convention rig maps Spine2 (high on the chest) to UpperTorso, giving
    h = 22 studs on a 50-stud character where the other bake-off legs read
    7.7-8.3. The oversized box then ate half the hip height and E12
    (hip/height in 0.3-0.6) failed leg C at 0.234 on a rig whose feet were
    fine (witnessed 2026-09-04). At 0.15 x height the same rig reads 0.38.

    Proportions (0.9 h wide, 0.5 h deep) are unchanged.
    """
    h = 0.15 * float(height_studs)
    return (round(0.9 * h, 4), round(h, 4), round(0.5 * h, 4))


def corrected_hip(sole_offset, settled_bottom, current_hip):
    """The hip a standing settle says this rig actually needs.

    Standing still, a Humanoid hovers: the settled HumanoidRootPart bottom sits
    at `HipHeight + e`, with `e` CONSTANT per rig (witnessed 2026-09-04:
    0.45 / 0.89 / 1.03 studs across the three bake-off legs). So one settle
    measures `e = settled_bottom - current_hip`, and the corrected hip is
    `sole_offset - e`, where `sole_offset` is the HRP-bottom-to-lowest-vertex
    distance groundfit.luau already computes as `(lt.Y - minY) - rootSize.Y/2`.

    One settle and one correction converge -- pass 4 landed at gaps of +0.006 /
    -0.0003 / +0.003 studs. Two earlier passes did not, and both failures were
    the same mistake: pass 1 subtracted a gap measured MID-WALK (5.14 / 4.26 /
    2.33 studs) as if it were the standing one, and pass 2's `hip -= gap`
    treated the hover excess as a fixed fraction of hip height when it is a
    fixed number of studs.
    """
    e = float(settled_bottom) - float(current_hip)
    return float(sole_offset) - e
