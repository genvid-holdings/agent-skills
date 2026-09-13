"""sqrt-scale timing: a giant's cadence falls with the square root of its height
(pendulum law). REF_HEIGHT 8 studs gives 0.40 at 50 studs, the spec's number."""
import math
REF_HEIGHT = 8.0

def cadence(height_studs):
    c = math.sqrt(REF_HEIGHT / float(height_studs))
    return max(0.2, min(1.0, c))

def scale_time(t, height_studs):
    return float(t) / cadence(height_studs)
