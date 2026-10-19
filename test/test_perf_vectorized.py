"""Perf regression check: dihedral + silhouette on a ~600k-face mesh.

Run:
  blender --background --python test/test_perf_vectorized.py

Budgets are env-overridable so a slower CI machine can be tuned without
editing the test:
  AUTOTOPO_PERF_DIH / AUTOTOPO_PERF_SIL / AUTOTOPO_PERF_ERR (seconds)

Under pytest without Blender this module is skipped.
"""
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)
_PACKAGE_PARENT = os.path.dirname(_PROJECT_ROOT)
for _p in (_TEST_DIR, _PACKAGE_PARENT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BLENDER_TEST = True
SLOW_TEST = True

# Tightened budgets (audit finding #26): the old ``< 10.0`` seconds
# thresholds were so loose that every run passed regardless of an
# order-of-magnitude regression. These are ~3-4x the measured baseline
# on Blender 3.4 / numpy 2.2.6 (see module print output) — loose enough
# for slower machines, tight enough to catch a real slowdown.
T_DIH_BUDGET = float(os.environ.get("AUTOTOPO_PERF_DIH", "4.0"))
T_SIL_BUDGET = float(os.environ.get("AUTOTOPO_PERF_SIL", "4.0"))
T_ERR_BUDGET = float(os.environ.get("AUTOTOPO_PERF_ERR", "8.0"))


def _run():
    import time

    import numpy as np

    from Blender_AutoTopo.utils.math_utils import compute_dihedral_angles
    from Blender_AutoTopo.engines.evaluation import (
        compute_silhouette_error, get_silhouette_points,
    )
    from Blender_AutoTopo.utils.mesh_io import MeshData

    # Dense grid mesh ~ 600k triangles (548x548 quads -> 600608 tris)
    n = 549
    xs = np.linspace(0, 10, n)
    X, Y = np.meshgrid(xs, xs)
    Z = 0.3 * np.sin(X) * np.cos(Y)
    verts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)

    def idx(i, j):
        return i * n + j

    tris = []
    for j in range(n - 1):
        row = []
        for i in range(n - 1):
            a, b = idx(j, i), idx(j, i + 1)
            c, d = idx(j + 1, i), idx(j + 1, i + 1)
            row.append((a, b, d))
            row.append((a, d, c))
        tris.extend(row)
    faces = np.array(tris, dtype=np.int64)
    print(f"mesh: {len(verts)} verts, {len(faces)} faces")

    t0 = time.time()
    keys, angles = compute_dihedral_angles(verts, faces)
    t_dih = time.time() - t0
    print(f"compute_dihedral_angles: {len(keys)} edges in {t_dih:.2f}s")

    src = MeshData()
    src.vertices = verts
    src.faces = faces
    src.normals = None

    t0 = time.time()
    pts = get_silhouette_points(src)
    t_sil = time.time() - t0
    print(f"get_silhouette_points: {len(pts)} points in {t_sil:.2f}s")

    out = MeshData()
    out.vertices = verts[::200].copy()
    out.faces = faces[::200].copy()
    t0 = time.time()
    err = compute_silhouette_error(out, src)
    t_err = time.time() - t0
    print(f"compute_silhouette_error: {err:.4f} in {t_err:.2f}s")

    # Correctness first: the perf numbers are meaningless if the
    # functions silently produced nothing.
    assert len(keys) > 0, "compute_dihedral_angles returned no edges"
    assert len(angles) == len(keys), "edge/angle count mismatch"
    assert len(pts) > 0, "get_silhouette_points returned no points"
    assert np.isfinite(err), f"silhouette error not finite: {err}"

    print(f"budgets: dihedral<{T_DIH_BUDGET}s silhouette<{T_SIL_BUDGET}s "
          f"error<{T_ERR_BUDGET}s")
    assert t_dih < T_DIH_BUDGET, \
        f"dihedral too slow: {t_dih:.2f}s >= {T_DIH_BUDGET}s"
    assert t_sil < T_SIL_BUDGET, \
        f"silhouette points too slow: {t_sil:.2f}s >= {T_SIL_BUDGET}s"
    assert t_err < T_ERR_BUDGET, \
        f"silhouette error too slow: {t_err:.2f}s >= {T_ERR_BUDGET}s"
    print("=== PERF CHECK PASSED ===")


def test_perf_vectorized():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
