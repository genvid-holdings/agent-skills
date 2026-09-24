"""sqrt-scale timing: a giant's cadence falls with the square root of its height
(pendulum law). REF_HEIGHT 8 studs gives 0.40 at 50 studs, the spec's number."""
import math
REF_HEIGHT = 8.0

def cadence(height_studs):
    c = math.sqrt(REF_HEIGHT / float(height_studs))
    return max(0.2, min(1.0, c))

def scale_time(t, height_studs):
    return float(t) / cadence(height_studs)


def clip_time(item, t, height_studs):
    """An authored time `t` as the built clip plays it: the clip item's own
    `time_scale` (recorded by `clips build --time-scale`) when it has one,
    else the sqrt-cadence stretch for the height. Every derived clip timing
    goes through this, so it cannot disagree with the file kfs.write wrote."""
    ts = (item or {}).get("time_scale")
    return scale_time(t, height_studs) if ts is None else float(t) * float(ts)


def authored_time(item, t, height_studs):
    """The inverse of `clip_time`: a played time back to the authored one."""
    ts = (item or {}).get("time_scale")
    return float(t) * cadence(height_studs) if ts is None else float(t) / float(ts)
