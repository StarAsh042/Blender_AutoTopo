"""Unit tests for the vertex normals the addon writes into Blender.

Blender 3.4 stores a zero-length custom normal literally and shades the surface
wrong, so every vertex that touches real surface must come back with a usable
unit normal. QuadWild hands over overlapping and degenerate triangles often
enough that this is a real path, not a corner case.

Pure numpy, no bpy: the module is loaded straight from source so the package
``__init__`` (which imports bpy) never runs.

    python -m pytest test/test_vertex_normals.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _pkgload  # noqa: E402

_math_utils = _pkgload.load_module("utils/math_utils.py")
compute_vertex_normals = _math_utils.compute_vertex_normals


def _quad_xy(z=0.0):
    """Unit square in the z = z0 plane, wound counter-clockwise from +Z."""
    return np.array([
        [0.0, 0.0, z],
        [1.0, 0.0, z],
        [1.0, 1.0, z],
        [0.0, 1.0, z],
    ], dtype=np.float64)


_QUAD_FACES = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)


def _unit_lengths(normals):
    return np.linalg.norm(normals, axis=1)


def test_flat_quad_points_along_its_normal():
    normals = compute_vertex_normals(_quad_xy(), _QUAD_FACES)

    assert normals.shape == (4, 3)
    np.testing.assert_allclose(normals, np.tile([0.0, 0.0, 1.0], (4, 1)), atol=1e-12)


def test_winding_decides_the_direction():
    flipped = compute_vertex_normals(_quad_xy(), _QUAD_FACES[:, ::-1].copy())

    np.testing.assert_allclose(flipped, np.tile([0.0, 0.0, -1.0], (4, 1)), atol=1e-12)


def test_duplicate_triangle_wound_backwards_stays_unit_length():
    """The regression: the same triangle twice with opposite winding cancels out.

    Both copies carry identical area, so the area-weighted sum is exactly
    (0, 0, 0) and the old code returned that as a "unit" normal. Blender 3.4
    then stores the zero and shades the vertex wrong.
    """
    vertices = _quad_xy()
    faces = np.vstack([_QUAD_FACES, _QUAD_FACES[:, ::-1]])

    normals = compute_vertex_normals(vertices, faces)

    lengths = _unit_lengths(normals)
    assert np.all(lengths > 0.5), f"zero-length normals left at {np.flatnonzero(lengths <= 0.5)}"
    np.testing.assert_allclose(normals, np.tile([0.0, 0.0, 1.0], (4, 1)), atol=1e-12)


def test_duplicate_triangle_same_winding_is_not_double_counted():
    """A doubled triangle has twice the weight of its neighbours if counted twice."""
    # A right-angle fold: one triangle in the XY plane, one in the XZ plane.
    vertices = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    flat = np.array([0, 1, 2], dtype=np.int64)
    upright = np.array([0, 1, 3], dtype=np.int64)
    faces = np.array([flat, upright, flat, flat])

    doubled = compute_vertex_normals(vertices, faces)
    once = compute_vertex_normals(vertices, np.array([flat, upright]))

    np.testing.assert_allclose(doubled, once, atol=1e-12)


def test_zero_area_triangles_do_not_steer_the_normal():
    vertices = _quad_xy()
    # A sliver along the quad's edge: zero area, and its face normal is undefined.
    degenerate = np.array([[0, 1, 1]], dtype=np.int64)
    faces = np.vstack([_QUAD_FACES, degenerate])

    normals = compute_vertex_normals(vertices, faces)

    np.testing.assert_allclose(normals, np.tile([0.0, 0.0, 1.0], (4, 1)), atol=1e-12)


def test_vertices_off_the_surface_come_back_zero_shaped():
    vertices = np.vstack([_quad_xy(), [[5.0, 5.0, 5.0]]])

    normals = compute_vertex_normals(vertices, _QUAD_FACES)

    assert normals.shape == (5, 3)
    assert np.all(normals[4] == 0.0)
    assert not np.isnan(normals).any()


def test_all_degenerate_input_returns_zeros_not_nan():
    vertices = _quad_xy()
    faces = np.array([[0, 1, 1], [0, 0, 0]], dtype=np.int64)

    normals = compute_vertex_normals(vertices, faces)

    assert normals.shape == (4, 3)
    assert np.all(normals == 0.0)


def test_empty_face_list_returns_zeros():
    normals = compute_vertex_normals(_quad_xy(), np.zeros((0, 3), dtype=np.int64))

    assert normals.shape == (4, 3)
    assert np.all(normals == 0.0)


def test_precomputed_face_normals_are_used():
    vertices = _quad_xy()
    given = np.tile([0.0, 0.0, 1.0], (len(_QUAD_FACES), 1))

    normals = compute_vertex_normals(vertices, _QUAD_FACES, face_normals=given)

    np.testing.assert_allclose(normals, np.tile([0.0, 0.0, 1.0], (4, 1)), atol=1e-12)


def test_no_vertex_on_live_surface_comes_back_zero_length():
    """Every vertex the usable triangles touch must carry a usable direction."""
    rng = np.random.default_rng(20240108)
    vertices = rng.normal(size=(64, 3))
    faces = rng.integers(0, len(vertices), size=(256, 3), dtype=np.int64)
    # Duplicate half of the faces with reversed winding, as QuadWild does.
    faces = np.vstack([faces, faces[:128, ::-1]])

    normals = compute_vertex_normals(vertices, faces)

    lengths = _unit_lengths(normals)
    touched = np.unique(faces)
    zero_touched = touched[lengths[touched] == 0.0]
    assert len(zero_touched) == 0, f"vertices {zero_touched} have no normal"
    assert not np.isnan(normals).any()
