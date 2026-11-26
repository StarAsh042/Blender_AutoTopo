"""Unit tests for the disconnected-shell counter QuadWild uses to reject input.

Pure numpy, no bpy: the module is loaded straight from source so the package
``__init__`` (which imports bpy) never runs.

    python -m pytest test/test_shell_count.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _pkgload  # noqa: E402

_math_utils = _pkgload.load_module("utils/math_utils.py")
count_surface_shells = _math_utils.count_surface_shells


def _grid_edges(rows, cols):
    """Edge list for a rows x cols lattice, vertex index = r * cols + c."""
    edges = []
    for r in range(rows):
        for c in range(cols):
            v = r * cols + c
            if c + 1 < cols:
                edges.append((v, v + 1))
            if r + 1 < rows:
                edges.append((v, v + cols))
    return np.asarray(edges, dtype=np.int64)


def test_single_component():
    edges = _grid_edges(4, 4)
    assert count_surface_shells(16, edges) == 1


def test_two_separate_components():
    left = _grid_edges(3, 3)
    right = _grid_edges(3, 3)
    offset = 9
    edges = np.concatenate([left, right + offset])
    assert count_surface_shells(18, edges) == 2


def test_many_components():
    parts = [_grid_edges(2, 2) + (i * 4) for i in range(12)]
    edges = np.concatenate(parts)
    assert count_surface_shells(48, edges) == 12


def test_long_chain_needs_many_rounds():
    """A 200-vertex path converges slowly; the default budget must cover it."""
    n = 200
    edges = np.asarray([(i, i + 1) for i in range(n - 1)], dtype=np.int64)
    assert count_surface_shells(n, edges) == 1


def test_isolated_vertices_are_not_shells():
    """A stray vertex is not a surface, so it must not count as a shell."""
    edges = _grid_edges(3, 3)
    assert count_surface_shells(9 + 5, edges) == 1


def test_empty_input():
    assert count_surface_shells(0, np.zeros((0, 2), dtype=np.int64)) == 0
    assert count_surface_shells(10, np.zeros((0, 2), dtype=np.int64)) == 0


def test_vertex_sharing_merges_components():
    """Two islands that share one vertex are one shell."""
    left = _grid_edges(3, 3)
    right = _grid_edges(3, 3)
    # Remap the right island so its first vertex is left's last vertex (8).
    mapping = {i: i - 9 + 8 for i in range(9)}
    right = np.vectorize(mapping.get)(right)
    edges = np.concatenate([left, right])
    assert count_surface_shells(17, edges) == 1
