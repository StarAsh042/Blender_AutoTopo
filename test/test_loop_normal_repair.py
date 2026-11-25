"""Tests for plan_loop_normal_repair, the loop-normal repair decision.

Blender before 4.1 encodes a custom split normal as a short2 offset from the
loop's own reference normal. A normal exactly opposite that reference sits on
the singularity of that encoding and decodes as a zero vector, which shades as
a hole. That is the "degenerate" look reported on Blender 3.4 in issue #8.

No synthetic mesh reproduces the singularity on demand (eighteen hand-built
cases across a bend, a fold, a backwound fold and a cancelling pair all read
back unit length), so this test feeds the function the numbers Blender really
read back from the 950k-face scan instead of trying to make Blender produce
them again.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pkgload

_m = _pkgload.load_module("utils/math_utils.py")
plan_loop_normal_repair = _m.plan_loop_normal_repair


def test_working_normals_are_returned_untouched():
    stored = np.array([[0.6, 0.0, 0.8], [0.0, 1.0, 0.0]], dtype=np.float64)
    repaired, count = plan_loop_normal_repair(
        stored,
        face_of_loop=np.array([0, 0]),
        face_normals=np.array([[0.0, 0.0, 1.0]]),
        face_areas=np.array([1.0]),
    )
    assert count == 0, f"{count} loops rewritten although none were broken"
    assert np.array_equal(repaired, stored), "a working normal was changed"


def test_zero_length_loop_gets_its_face_normal():
    # Vertex 1953 on the real 3.4 asset: 7 loops, 4 of them came back zero.
    stored = np.array(
        [
            [0.18617, -0.411264, -0.892302],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [-0.186011, 0.411246, 0.892343],
        ],
        dtype=np.float64,
    )
    face_normal = np.array([0.0, 0.0, 1.0])
    repaired, count = plan_loop_normal_repair(
        stored,
        face_of_loop=np.array([0, 1, 2, 3]),
        face_normals=np.array([face_normal] * 4),
        face_areas=np.array([1.0, 1.0, 1.0, 1.0]),
    )
    assert count == 2, f"expected 2 loops repaired, got {count}"
    lengths = np.linalg.norm(repaired, axis=1)
    assert (lengths > 0.5).all(), f"a zero-length normal survived: {repaired}"
    for li in (1, 2):
        assert np.allclose(repaired[li], face_normal), (
            f"loop {li} got {repaired[li]} instead of the face normal {face_normal}"
        )
    # The loops that were fine keep the engine's normal exactly.
    assert np.array_equal(repaired[0], stored[0])
    assert np.array_equal(repaired[3], stored[3])


def test_zero_loop_on_zero_area_face_is_left_alone():
    # A face with no area has no direction to lend, so inventing one would
    # shade a surface that does not exist.
    stored = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
    repaired, count = plan_loop_normal_repair(
        stored,
        face_of_loop=np.array([0]),
        face_normals=np.array([[0.0, 0.0, 1.0]]),
        face_areas=np.array([0.0]),
    )
    assert count == 0, f"a zero-area face was given a normal ({count} loops)"
    assert np.array_equal(repaired, stored), "a zero-area loop was rewritten"


def test_empty_loop_list_is_not_an_error():
    repaired, count = plan_loop_normal_repair(
        np.zeros((0, 3)),
        face_of_loop=np.zeros(0, dtype=np.int64),
        face_normals=np.zeros((0, 3)),
        face_areas=np.zeros(0),
    )
    assert count == 0
    assert repaired.shape == (0, 3)


def test_stored_array_is_not_mutated():
    stored = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
    before = stored.copy()
    plan_loop_normal_repair(
        stored,
        face_of_loop=np.array([0]),
        face_normals=np.array([[0.0, 0.0, 1.0]]),
        face_areas=np.array([1.0]),
    )
    assert np.array_equal(stored, before), "the input array was modified in place"
