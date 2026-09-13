"""Impact keyframe from predicted world trajectories (damage fires here: attackImpactDelaySecs).

`traj` is the `traj` block `blender/poses.py` emits: `{bone: [[t, x, y, z], ...]}` in
the Roblox rig's own frame (index 2 is UP), predicted from the transferred pose rather
than measured in Studio. The slam is the global minimum height that follows the global
maximum -- a wind-up peak then the strike -- so a clip with no lift (a walk, an idle)
reports 0.0 and the caller treats it as "no impact in this clip" rather than damage on
frame one. `metrics.impact_height` scores the same trajectory at the time returned here,
and eval row E21 gates it against the feet plane.
"""
def impact_time(traj, bones=("LeftFoot", "RightFoot", "LeftHand", "RightHand")):
    best_peak, best_peak_t = -1e9, 0.0
    for b in bones:
        for t, _x, y, _z in traj.get(b, []):
            if y > best_peak: best_peak, best_peak_t = y, t
    best_min, best_min_t = 1e9, 0.0
    for b in bones:
        for t, _x, y, _z in traj.get(b, []):
            if t >= best_peak_t and y < best_min: best_min, best_min_t = y, t
    if best_peak - best_min < 1e-6:
        return 0.0
    return float(best_min_t)
