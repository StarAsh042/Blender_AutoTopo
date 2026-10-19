"""Shared engine result container and silhouette evaluation.

RetopoResult is the common return type of all remesh engines;
compute_silhouette_error measures how well the output follows the
source surface (used by every engine for its quality report).

All heavy paths are vectorized: the evaluation runs on meshes with
hundreds of thousands of faces, so per-face Python loops are not an
option here.
"""

import numpy as np
from typing import Optional

from ..utils.mesh_io import MeshData
from ..utils.math_utils import compute_bounding_box


class RetopoResult:
    """Container for retopology results and diagnostics."""

    def __init__(self):
        self.success: bool = False
        self.output_mesh: Optional[MeshData] = None
        self.error_message: str = ""

        # Timing
        self.time_total: float = 0.0

        # Statistics
        self.input_vert_count: int = 0
        self.input_face_count: int = 0
        self.output_vert_count: int = 0
        self.output_face_count: int = 0
        self.output_quad_count: int = 0
        self.output_tri_count: int = 0
        self.triangle_ratio: float = 0.0
        self.patch_count: int = 0
        self.silhouette_error: float = 0.0


def _triangles_of(mesh_data: MeshData) -> Optional[np.ndarray]:
    """(M, 3) int64 triangle array, or None if there are none."""
    faces = np.asarray(mesh_data.faces)
    if faces.size == 0:
        return None
    if faces.dtype == object:
        tris = [f for f in faces if len(f) == 3]
        if not tris:
            return None
        faces = np.array(tris, dtype=np.int64)
    return faces.astype(np.int64, copy=False)


def _max_nearest_distance(query: np.ndarray, ref: np.ndarray) -> float:
    """max over ``query`` points of the distance to the nearest ``ref`` point.

    Directed Hausdorff distance, computed by the best available backend:

    1. the optional C++ layer (kd-tree, ``bin/autotopo_native.dll``),
    2. ``scipy.spatial.cKDTree`` (bundled with Blender 3.4),
    3. ``mathutils.kdtree`` (always present inside Blender),
    4. a memory-bounded chunked numpy brute force.

    Replaces the previous O(len(query) * len(ref)) full-broadcast loop,
    which at 20k output vertices took ~28s and peaked near 500MB of
    temporaries. A kd-tree over the (smaller) reference set makes it
    O(len(ref) log len(ref) + len(query) log len(ref)).
    """
    query = np.ascontiguousarray(query, dtype=np.float64)
    ref = np.ascontiguousarray(ref, dtype=np.float64)
    if len(query) == 0 or len(ref) == 0:
        return 0.0

    # 1. C++ kd-tree
    try:
        from ..utils import native as _native
        d = _native.max_nearest_distance(query, ref)
        if d is not None:
            return d
    except Exception:
        pass

    # 2. scipy cKDTree (bundled with Blender; not a hard dependency)
    try:
        from scipy.spatial import cKDTree
        dist, _ = cKDTree(ref).query(query, k=1)
        return float(np.max(dist))
    except Exception:
        pass

    # 3. mathutils.kdtree (Blender built-in)
    try:
        from mathutils.kdtree import KDTree
        tree = KDTree(len(ref))
        for i, p in enumerate(ref):
            tree.insert((float(p[0]), float(p[1]), float(p[2])), i)
        tree.balance()
        best = 0.0
        for p in query:
            _, _, d = tree.find((float(p[0]), float(p[1]), float(p[2])))
            if d > best:
                best = d
        return best
    except Exception:
        pass

    # 4. Chunked numpy brute force with a bounded temporary footprint
    #    (~64MB) so large meshes cannot OOM.
    best = 0.0
    chunk = max(1, min(1024, int(64_000_000 // max(len(ref) * 24, 1))))
    for s in range(0, len(query), chunk):
        diff = query[s:s + chunk, np.newaxis, :] - ref[np.newaxis, :, :]
        d2 = np.einsum('ijk,ijk->ij', diff, diff)
        best = max(best, float(np.sqrt(d2.min(axis=1)).max()))
    return best


def compute_silhouette_error(
    mesh_data: MeshData,
    source_mesh: MeshData
) -> float:
    """Compute silhouette fidelity error (Hausdorff distance approximation).

    Args:
        mesh_data: Output mesh
        source_mesh: Source mesh

    Returns:
        Error metric (lower = better silhouette match)
    """
    _, bbox_diag = compute_bounding_box(source_mesh.vertices)

    # Sample silhouette edges of source
    # For MVP: use boundary edges of source as silhouette proxy
    source_silhouette = get_silhouette_points(source_mesh)

    if len(source_silhouette) == 0:
        return 0.0

    # For each silhouette point, find the nearest output vertex (the
    # smaller set), then take the maximum. A kd-tree over the output
    # vertices turns this into O(N_sil * log N_out).
    out_verts = np.asarray(mesh_data.vertices, dtype=np.float64)
    if len(out_verts) == 0:
        return 0.0
    max_dist = _max_nearest_distance(source_silhouette, out_verts)

    # Normalize by bounding box diagonal
    return max_dist / max(bbox_diag, 1e-8)


def get_silhouette_points(mesh_data: MeshData) -> np.ndarray:
    """Get approximate silhouette sample points.

    Uses vertices with high curvature as proxy for silhouette.
    Curvature is the Gaussian angle defect; per-vertex areas are
    barycentric thirds of the incident face areas. Fully vectorized.
    """
    verts = np.asarray(mesh_data.vertices, dtype=np.float64)
    faces = _triangles_of(mesh_data)

    if faces is None or len(verts) == 0:
        return np.zeros((0, 3))

    i0, i1, i2 = faces[:, 0], faces[:, 1], faces[:, 2]
    v0, v1, v2 = verts[i0], verts[i1], verts[i2]

    # Per-face areas (barycentric split to the three corners)
    cross = np.cross(v1 - v0, v2 - v0)
    face_area = 0.5 * np.linalg.norm(cross, axis=1)
    third = face_area / 3.0
    areas = np.zeros(len(verts), dtype=np.float64)
    np.add.at(areas, i0, third)
    np.add.at(areas, i1, third)
    np.add.at(areas, i2, third)

    # Per-corner angles -> angle defect per vertex
    def corner_angle(ea: np.ndarray, eb: np.ndarray) -> np.ndarray:
        na = np.linalg.norm(ea, axis=1)
        nb = np.linalg.norm(eb, axis=1)
        cos_a = np.einsum('ij,ij->i', ea, eb) / np.maximum(na * nb, 1e-24)
        return np.arccos(np.clip(cos_a, -1.0, 1.0))

    angle_sum = np.zeros(len(verts), dtype=np.float64)
    np.add.at(angle_sum, i0, corner_angle(v1 - v0, v2 - v0))
    np.add.at(angle_sum, i1, corner_angle(v0 - v1, v2 - v1))
    np.add.at(angle_sum, i2, corner_angle(v0 - v2, v1 - v2))

    K = np.abs(2.0 * np.pi - angle_sum) / np.maximum(areas, 1e-10)

    # Take top 10% curvature vertices as silhouette proxy
    threshold = np.percentile(K, 90)
    return verts[K >= threshold]
