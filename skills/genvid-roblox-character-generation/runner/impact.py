"""Impact keyframe from predicted world trajectories (damage fires here: attackImpactDelaySecs).

`traj` is the `traj` block `blender/poses.py` emits: `{bone: [[t, x, y, z], ...]}` in
the Roblox rig's own frame (index 2 is UP), predicted from the transferred pose rather
than measured in Studio. Each bone is read on its own. Its drop is its largest fall from
any sample to a later one (a wind-up peak, then the strike's low), whatever it does after
the low: a swipe may follow through higher than it wound up. A bone drops only when that
fall is real. The striking limb is, among the bones whose drop is at least
`STRIKE_DROP_FRAC` of the largest, the one whose low reaches lowest (lows within
`STRIKE_LEVEL_STUDS` are level, and the larger drop strikes): a stomp's foot comes down to
the ground while the arms may swing further without reaching it, and a foot planted
through a hand strike does not drop at all. The impact is that bone's low.

Any clip whose limbs move has a strike: a walk's feet lift and come down, so a walk
reports a time too. Only a clip where no limb ever drops (a held pose) reports 0.0, and
the caller treats that as "no impact in this clip" rather than damage on frame one.
`clips impact` is run on attack clips. `metrics.impact_height` scores the striking bone
at the time returned here, and eval row E21 gates it against the sole plane.
"""
BONES = ("LeftFoot", "RightFoot", "LeftHand", "RightHand")
HANDS = ("LeftHand", "RightHand")
# A bone whose drop is at least this fraction of the largest drop is a candidate striker.
STRIKE_DROP_FRAC = 0.5
# Lows within this many studs of each other are level: the larger drop strikes.
STRIKE_LEVEL_STUDS = 1e-3


def drop(samples):
    """(fall, time of the low, height of the low): the largest fall from any
    sample to a later one, or None when the bone never falls."""
    best, high = None, None
    for t, _x, y, _z in samples:
        if high is not None and high - y > 1e-6 and (best is None or high - y > best[0]):
            best = (high - y, float(t), y)
        if high is None or y > high:
            high = y
    return best


def strike(traj, bones=BONES, prefer=None):
    """(bone, time) of the strike, or None when no bone drops. `prefer` (a
    tuple of bones) narrows the candidates to those bones whenever one of them
    qualifies: a slam is scored on its hands, and falls back to the feet only
    when no hand drops far enough to be a candidate."""
    drops = {b: d for b in bones for d in (drop(traj.get(b) or []),) if d is not None}
    if not drops:
        return None
    floor = STRIKE_DROP_FRAC * max(d[0] for d in drops.values())
    candidates = [b for b, d in drops.items() if d[0] >= floor]
    preferred = [b for b in candidates if b in (prefer or ())]
    pool = preferred or candidates
    lowest = min(drops[b][2] for b in pool)
    level = [b for b in pool if drops[b][2] - lowest <= STRIKE_LEVEL_STUDS]
    bone = max(level, key=lambda b: drops[b][0])
    return bone, drops[bone][1]


def impact_time(traj, bones=BONES):
    hit = strike(traj, bones)
    return 0.0 if hit is None else hit[1]
