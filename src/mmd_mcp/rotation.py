"""MMD bone-panel degrees <-> VMD quaternion (x,y,z,w).

Verified against MMD 9.32: R = Ry(-UI.y) Rx(UI.x) Rz(-UI.z).
These are bone angles, not camera angles or generic XYZ Euler angles.
"""
import math


def multiply(a, b):
    x, y, z, w = a
    X, Y, Z, W = b
    return (w*X+x*W+y*Z-z*Y, w*Y-x*Z+y*W+z*X,
            w*Z+x*Y-y*X+z*W, w*W-x*X-y*Y-z*Z)


def axis_angle(axis, degrees):
    length = math.sqrt(sum(v*v for v in axis))
    if not length or not math.isfinite(length) or not math.isfinite(degrees):
        raise ValueError('Finite nonzero rotation axis required.')
    angle = math.radians(degrees)/2
    return (*[v/length*math.sin(angle) for v in axis], math.cos(angle))


def from_ui(x, y, z):
    return multiply(multiply(axis_angle((0, 1, 0), -y), axis_angle((1, 0, 0), x)),
                    axis_angle((0, 0, 1), -z))


def to_ui(q):
    n = math.sqrt(sum(v*v for v in q))
    if len(q) != 4 or not n or not math.isfinite(n):
        raise ValueError('Finite nonzero quaternion required.')
    x, y, z, w = [v/n for v in q]
    r12 = 2*(y*z-x*w)
    a = math.asin(max(-1., min(1., -r12)))
    if abs(math.cos(a)) > 1e-7:
        b = math.atan2(2*(x*z+y*w), 1-2*(x*x+y*y))
        c = math.atan2(2*(x*y+z*w), 1-2*(x*x+z*z))
    else:
        b = math.atan2(-2*(x*z-y*w), 1-2*(y*y+z*z))
        c = 0.
    return tuple(math.degrees(v) for v in (a, -b, -c))
