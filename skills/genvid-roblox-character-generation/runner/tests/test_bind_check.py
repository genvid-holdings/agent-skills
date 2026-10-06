"""The bind check's direction rule (blender/poses.py), run without Blender.

poses.py is a Blender script and runs on import, so the functions under test
are read from its source and compiled here with numpy alone.

    python3 -m unittest discover -s skills/genvid-roblox-character-generation/runner/tests
"""
import ast
import math
import unittest
from pathlib import Path

import numpy as np

POSES = Path(__file__).resolve().parents[1] / "blender" / "poses.py"
FUNCTIONS = ("segments", "angle_deg", "trimmed_fit", "bind_off_rest", "over")
CONSTANTS = ("BIND_TOL_DEG", "SEGMENT_FLOOR")


def load():
    """The bind check's functions and constants, as a namespace."""
    wanted = []
    for node in ast.parse(POSES.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            wanted.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets):
            wanted.append(node)
    ns = {"np": np, "math": math}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(POSES), "exec"), ns)
    return ns


# A small skeleton. `Chest` sits on `Body`: a zero-length joint.
PARENTS = {"Root": None, "Body": "Root", "Chest": "Body", "Neck": "Chest", "Tail": "Body", "LegL": "Body",
           "LegR": "Body"}
RB = {name: {"parent": parent} for name, parent in PARENTS.items()}
ORDER = [name for name in PARENTS if PARENTS[name] is not None]
REST = {"Root": [0, 0, 0], "Body": [0, 10, 0], "Chest": [0, 10, 0], "Neck": [0, 12, 3], "Tail": [0, 9, -4],
        "LegL": [2, 5, 0], "LegR": [-2, 5, 0]}


def moved(skeleton, **bones):
    out = {name: list(p) for name, p in skeleton.items()}
    out.update({name: list(p) for name, p in bones.items()})
    return out


class ZeroLengthJoint(unittest.TestCase):
    def setUp(self):
        self.ns = load()

    def off(self, bind, rest):
        return self.ns["bind_off_rest"](bind, RB, ORDER, rest)

    def test_the_functions_under_test_are_all_found(self):
        for name in FUNCTIONS + CONSTANTS:
            self.assertIn(name, self.ns)

    def test_float_noise_on_a_zero_length_joint_is_not_a_bone_direction(self):
        # the joint's offset is noise in both skeletons, in different
        # directions; every real bone is identical
        rest = moved(REST, Chest=[0, 10, 1.85e-6])
        bind = moved(REST, Chest=[1.1e-6, 10, 2.9e-6])
        off = self.off(bind, rest)
        self.assertEqual(self.ns["over"](off), {})
        self.assertLess(max(off.values()), 0.01)

    def test_the_noise_offset_is_left_out_of_the_segments(self):
        rest = moved(REST, Chest=[0, 10, 1.85e-6])
        bind = moved(REST, Chest=[1.1e-6, 10, 2.9e-6])
        parents = [pr for pr, _a, _b in self.ns["segments"](rest, bind, RB, ORDER)]
        self.assertEqual(parents.count("Body"), 3)   # Tail, LegL, LegR; not Chest
        self.assertEqual(len(parents), 5)

    def test_noise_on_one_side_only_is_left_out_too(self):
        # a short real offset in one skeleton, noise across it in the other
        real = moved(REST, Chest=[0, 10, 0.05])
        noise = moved(REST, Chest=[2.9e-6, 10, 0])
        for rest, bind in ((real, noise), (noise, real)):
            self.assertEqual(len(self.ns["segments"](rest, bind, RB, ORDER)), 5)
            self.assertEqual(self.ns["over"](self.off(bind, rest)), {})

    def test_the_floor_follows_the_skeletons_own_size(self):
        # the same skeleton and the same noise, in a file a thousand times
        # larger and one a thousand times smaller than the rest
        rest = moved(REST, Chest=[0, 10, 1.85e-6])
        bind = moved(REST, Chest=[1.1e-6, 10, 2.9e-6])
        for scale in (1000.0, 0.001):
            scaled = {name: [c * scale for c in p] for name, p in bind.items()}
            self.assertEqual(len(self.ns["segments"](rest, scaled, RB, ORDER)), 5, scale)
            self.assertEqual(self.ns["over"](self.off(scaled, rest)), {}, scale)
            # and a limb posed in that file is still seen
            swung = moved(scaled, LegL=[5 * scale, 7 * scale, 0])
            self.assertIn("Body", self.ns["over"](self.off(swung, rest)), scale)

    def test_a_short_real_bone_is_still_measured(self):
        # a bone a hundredth of the longest segment, turned a quarter turn
        longest = max(float(np.linalg.norm(np.subtract(REST[n], REST[PARENTS[n]]))) for n in ORDER)
        short = longest / 100
        rest = moved(REST, Chest=[0, 10, short])
        bind = moved(REST, Chest=[short, 10, 0])
        off = self.off(bind, rest)
        self.assertGreater(off["Body"], 85.0)
        self.assertEqual(list(self.ns["over"](off)), ["Body"])

    def test_a_posed_limb_is_still_refused(self):
        bind = moved(REST, LegL=[5, 7, 0])   # a leg swung out
        over = self.ns["over"](self.off(bind, REST))
        self.assertIn("Body", over)
        self.assertGreater(over["Body"], self.ns["BIND_TOL_DEG"])

    def test_a_matching_bind_reads_zero_on_every_bone(self):
        self.assertLess(max(self.off(REST, REST).values()), 1e-4)

    def test_a_skeleton_with_no_length_at_all_gives_no_segments(self):
        flat = {name: [0, 0, 0] for name in REST}
        self.assertEqual(self.ns["segments"](flat, flat, RB, ORDER), [])
        self.assertEqual(self.off(flat, flat), {})

    def test_the_floor_is_a_fraction_of_the_longest_segment(self):
        floor = self.ns["SEGMENT_FLOOR"]
        self.assertGreater(floor, 0)
        self.assertLess(floor, 0.01)
        longest = max(float(np.linalg.norm(np.subtract(REST[n], REST[PARENTS[n]]))) for n in ORDER)
        kept = moved(REST, Chest=[0, 10, longest * floor * 1.01])
        dropped = moved(REST, Chest=[0, 10, longest * floor * 0.99])
        self.assertEqual(len(self.ns["segments"](kept, kept, RB, ORDER)), 6)
        self.assertEqual(len(self.ns["segments"](dropped, dropped, RB, ORDER)), 5)


if __name__ == "__main__":
    unittest.main()
