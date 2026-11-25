"""The guard that stops a junk read from being written back into the mesh.

On 3.6 ``loops.foreach_get("normal")`` intermittently reports uninitialised
memory for a mesh that was just written: values up to 1e38, or NaN. The repair
that gives zero-length loops their face normal reads the stored normals back
first, so on that build it could read the junk, decide nothing looked broken,
and hand the whole buffer back to ``normals_split_custom_set``. That is the
corrupted 3.6 surface in issue #8.

So before repairing, the read has to pass a sanity check: every value finite
and no loop longer than a unit normal could ever be. These tests pin that check
down, because the failure it prevents is silent and only visible on screen.
"""
import os
import sys

import numpy as np
import pytest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
if _TEST_DIR not in sys.path:
    sys.path.insert(0, _TEST_DIR)

import _pkgload  # noqa: E402


math_utils = _pkgload.load_module("utils/math_utils.py")


def test_unit_normals_are_trusted():
    normals = np.array([[0.0, 0.0, 1.0], [0.6, 0.0, 0.8]], dtype=np.float64)
    assert math_utils.loop_normals_are_trustworthy(normals)


def test_zero_length_normals_are_trusted_enough_to_repair():
    """A zero is real data: it is the state the repair exists to fix."""
    normals = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    assert math_utils.loop_normals_are_trustworthy(normals)


def test_uninitialised_huge_values_are_rejected():
    """The 3.6 reading that corrupted the surface."""
    normals = np.array([[1e32, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)
    assert not math_utils.loop_normals_are_trustworthy(normals)


def test_nan_is_rejected():
    normals = np.array([[np.nan, 0.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    assert not math_utils.loop_normals_are_trustworthy(normals)


def test_inf_is_rejected():
    normals = np.array([[np.inf, 0.0, 0.0]], dtype=np.float64)
    assert not math_utils.loop_normals_are_trustworthy(normals)


def test_moderately_long_normals_are_tolerated():
    """Blender stores unnormalised custom normals; 1.55 is data, not garbage."""
    normals = np.array([[0.0, 0.0, 1.55], [0.0, 0.0, 6.36]], dtype=np.float64)
    assert math_utils.loop_normals_are_trustworthy(normals)


def test_empty_read_is_not_an_error():
    assert math_utils.loop_normals_are_trustworthy(np.zeros((0, 3), dtype=np.float64))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
