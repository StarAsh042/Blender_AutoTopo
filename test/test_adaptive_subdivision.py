"""Standalone test for adaptive_subdivision (system python, no bpy).

Builds a synthetic "flat plane + bump + dent" source surface and a
coarse 8x8 quad base, then verifies:
1. face budget respected
2. quad ratio >= 80%
3. result is watertight (edge shared by <= 2 faces) with no
   T-junctions (Euler characteristic of a disc == 1)
4. face density concentrates at the detail regions
5. output vertices stay close to the source surface

Runs under plain Python (needs numpy only) via pytest, and can also be
executed directly: ``python test/test_adaptive_subdivision.py``.
"""
import os
import sys
from collections import Counter

# Make the sibling _pkgload helper importable both under pytest and when
# this file is run directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import _pkgload  # noqa: E402

# The addon package is ``Blender_AutoTopo`` (project root); load only the
# numpy-only submodules so no bpy is required.
_pkgload.load_module("utils/logger.py")
subd = _pkgload.load_module("engines/adaptive_subdivision.py")


def make_source(n=101):
    """Dense plane with a bump at (+0.5,+0.5) and a dent at (-0.5,-0.5)."""
    xs = np.linspace(-1, 1, n)
    ys = np.linspace(-1, 1, n)
    X, Y = np.meshgrid(xs, ys)
    Z = (0.18 * np.exp(-(((X - 0.5) ** 2 + (Y - 0.5) ** 2) / 0.012))
         - 0.14 * np.exp(-(((X + 0.5) ** 2 + (Y + 0.5) ** 2) / 0.008)))
    return np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)


def make_source_faces(n=101):
    """Triangle indices for the ``make_source(n)`` grid (row-major order).

    The subdivision projects new vertices onto the source *surface*, so it
    needs the source triangles, not just the vertex cloud.
    """
    idx = np.arange(n * n).reshape(n, n)
    v00 = idx[:-1, :-1].ravel()
    v10 = idx[:-1, 1:].ravel()
    v01 = idx[1:, :-1].ravel()
    v11 = idx[1:, 1:].ravel()
    return np.concatenate([
        np.stack([v00, v10, v11], axis=1),
        np.stack([v00, v11, v01], axis=1),
    ], axis=0).astype(np.int64)


def make_base(m=8):
    """Coarse flat m x m quad grid over [-1, 1]^2."""
    xs = np.linspace(-1, 1, m + 1)
    ys = np.linspace(-1, 1, m + 1)
    X, Y = np.meshgrid(xs, ys)
    verts = np.stack([X.ravel(), Y.ravel(), np.zeros((m + 1) ** 2)], axis=1)
    faces = []
    for j in range(m):
        for i in range(m):
            a = j * (m + 1) + i
            faces.append((a, a + 1, a + m + 2, a + m + 1))
    return verts, faces


def test_adaptive_subdivision():
    source = make_source()
    source_faces = make_source_faces()
    base_verts, base_faces = make_base()

    TARGET = 800
    new_verts, final_faces, tri_count = subd.adaptive_subdivide(
        base_verts, base_faces, source, TARGET, max_depth=3,
        source_faces=source_faces,
    )

    n_faces = len(final_faces)
    n_quads = sum(1 for f in final_faces if len(f) == 4)
    n_tris = sum(1 for f in final_faces if len(f) == 3)
    print(f"faces: {n_faces} (quads {n_quads}, tris {n_tris}, "
          f"reported tris {tri_count}), verts {len(new_verts)}")

    # 1. budget respected (repair pass may overshoot slightly)
    assert n_faces <= TARGET + 40, f"budget exceeded: {n_faces}"
    assert n_faces >= TARGET * 0.5, f"budget barely used: {n_faces}"

    # 2. quad ratio (transition triangles are unavoidable at odd-midpoint
    # borders; synthetic worst case has a high detail-perimeter ratio).
    assert n_quads / n_faces >= 0.80, f"quad ratio too low: {n_quads/n_faces}"
    assert n_tris == tri_count

    # 3a. watertight: every edge used by at most 2 faces
    edge_count = Counter()
    for f in final_faces:
        k = len(f)
        for j in range(k):
            a, b = f[j], f[(j + 1) % k]
            edge_count[(min(a, b), max(a, b))] += 1
    over = {e: c for e, c in edge_count.items() if c > 2}
    assert not over, f"non-manifold edges: {list(over.items())[:5]}"

    # 3b. topology: Euler characteristic of a disc must be exactly 1.
    used_verts = set()
    for f in final_faces:
        used_verts.update(f)
    chi = len(used_verts) - len(edge_count) + n_faces
    print(f"Euler: V={len(used_verts)} E={len(edge_count)} F={n_faces} "
          f"chi={chi} (expect 1 for a disc)")
    assert chi == 1, f"topology broken (T-junctions?): chi={chi}"

    # 4. density concentration around the two detail regions
    centroids = np.array([
        np.mean(new_verts[list(f)], axis=0) for f in final_faces
    ])

    def region_density(center, radius):
        d = np.linalg.norm(centroids[:, :2] - center, axis=1)
        return (d < radius).sum() / (np.pi * radius ** 2)

    d_bump = region_density((0.5, 0.5), 0.35)
    d_dent = region_density((-0.5, -0.5), 0.35)
    d_corner = region_density((0.85, -0.85), 0.30)  # flat corner region
    print(f"density: bump={d_bump:.1f} dent={d_dent:.1f} "
          f"flat_corner={d_corner:.1f} faces/unit^2")
    assert d_bump > 3.0 * max(d_corner, 0.5), "bump not denser than flat area"
    assert d_dent > 3.0 * max(d_corner, 0.5), "dent not denser than flat area"

    # 5. output vertices close to the source surface
    diag = np.ptp(new_verts, axis=0).max()
    max_err = 0.0
    for chunk in range(0, len(new_verts), 256):
        p = new_verts[chunk:chunk + 256]
        d2 = ((source[None, :, :] - p[:, None, :]) ** 2).sum(axis=2).min(axis=1)
        max_err = max(max_err, float(np.sqrt(d2.max())))
    print(f"max vertex-to-source distance: {max_err:.5f} "
          f"(bbox diag {diag:.2f})")
    assert max_err < 0.02 * diag, f"vertices drift from surface: {max_err}"

    print("=== ADAPTIVE SUBDIVISION TEST PASSED ===")


if __name__ == "__main__":
    test_adaptive_subdivision()
