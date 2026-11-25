"""Math utilities for vector computations on triangle meshes.

All functions are numpy-vectorized: they run on meshes with
hundreds of thousands of faces, so per-face Python loops are not an
option here.
"""

import numpy as np
from typing import Tuple, Optional


def compute_face_normals(
    vertices: np.ndarray,
    faces: np.ndarray
) -> np.ndarray:
    """Compute per-face normals.

    Args:
        vertices: (N, 3) vertex positions
        faces: (M, 3) triangle face indices

    Returns:
        normals: (M, 3) per-face unit normals
    """
    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    normals = np.cross(v1 - v0, v2 - v0)
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return normals / norms


def compute_vertex_normals(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_normals: Optional[np.ndarray] = None
) -> np.ndarray:
    """Compute per-vertex normals (area-weighted average of face normals).

    Args:
        vertices: (N, 3) vertex positions
        faces: (M, 3) triangle face indices
        face_normals: (M, 3) precomputed face normals (optional)

    Returns:
        normals: (N, 3) per-vertex unit normals
    """
    n_verts = len(vertices)
    if face_normals is None:
        face_normals = compute_face_normals(vertices, faces)

    # Area-weighted: weight by face area
    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    face_areas = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)

    vert_normals = np.zeros((n_verts, 3), dtype=np.float64)
    weighted_normals = face_normals * face_areas[:, np.newaxis]

    for j in range(3):
        np.add.at(vert_normals, faces[:, j], weighted_normals)

    norms = np.linalg.norm(vert_normals, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return vert_normals / norms


def compute_dihedral_angles(
    vertices: np.ndarray,
    faces: np.ndarray,
    face_normals: Optional[np.ndarray] = None
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute dihedral angles for all edges.

    Args:
        vertices: (N, 3) vertex positions
        faces: (M, 3) triangle face indices
        face_normals: (M, 3) precomputed face normals

    Returns:
        edge_keys: (E, 2) array of vertex index pairs for each edge
        angles: (E,) dihedral angles in radians
    """
    if face_normals is None:
        face_normals = compute_face_normals(vertices, faces)

    n_faces = len(faces)
    if n_faces == 0:
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0)

    f = np.asarray(faces)

    # All 3M half-edges as (min, max) pairs + owning face index
    edge_cols = []
    for j in range(3):
        a = f[:, j]
        b = f[:, (j + 1) % 3]
        edge_cols.append(
            np.stack((np.minimum(a, b), np.maximum(a, b)), axis=1)
        )
    half_edges = np.concatenate(edge_cols, axis=0)
    half_edge_faces = np.tile(np.arange(n_faces), 3)

    # Sort by vertex pair: interior edges become adjacent duplicates
    order = np.lexsort((half_edges[:, 1], half_edges[:, 0]))
    he_sorted = half_edges[order]
    hf_sorted = half_edge_faces[order]

    same = np.all(he_sorted[1:] == he_sorted[:-1], axis=1)
    second = np.nonzero(same)[0] + 1
    if len(second) == 0:
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0)
    first = second - 1

    n1 = face_normals[hf_sorted[first]]
    n2 = face_normals[hf_sorted[second]]
    cos_angle = np.clip(np.einsum('ij,ij->i', n1, n2), -1.0, 1.0)
    angles = np.arccos(cos_angle)

    return he_sorted[first], angles


def count_surface_shells(
    n_verts: int,
    edges: np.ndarray,
    max_iters: int = 256,
) -> int:
    """Count disconnected surface shells (connected components of the edge graph).

    QuadWild's cost tracks the number of disconnected shells, not the vertex
    count: on one scanned asset, 97k verts in 20 shells finished in 211s while
    16k verts in 746 shells was still running after 420s. The engine needs this
    number before committing to a solve that cannot be interrupted.

    Vertices that belong to no edge are not part of any surface and are not
    counted, matching the face components bmesh reports for the same mesh.

    Args:
        n_verts: vertex count of the mesh
        edges: (E, 2) vertex index pairs
        max_iters: hooking rounds before giving up on full convergence. Long
            thin shells need many rounds: a 535k-vert scan still had 843
            shells at 32 rounds and only reached 797 at 100.

    Returns:
        Number of disconnected surface shells.
    """
    if n_verts == 0 or len(edges) == 0:
        return 0

    edges = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    a = edges[:, 0]
    b = edges[:, 1]

    parent = np.arange(n_verts, dtype=np.int64)
    for _ in range(max_iters):
        pa = parent[a]
        pb = parent[b]
        new = parent.copy()
        # Hook each endpoint to the smaller of the two roots. ``minimum.at``
        # keeps the minimum across duplicate indices; plain ``parent[idx] = v``
        # would keep the last write and split components apart.
        np.minimum.at(new, a, pb)
        np.minimum.at(new, b, pa)
        # Pointer jumping halves every remaining chain per round.
        new = new[new]
        if np.array_equal(new, parent):
            break
        parent = new

    used = np.zeros(n_verts, dtype=bool)
    used[a] = True
    used[b] = True
    return int(len(np.unique(parent[used])))


def compute_bounding_box(vertices: np.ndarray) -> Tuple[np.ndarray, float]:
    """Compute bounding box and diagonal length.

    Returns:
        center: (3,) bounding box center
        diagonal: bounding box diagonal length
    """
    bbox_min = vertices.min(axis=0)
    bbox_max = vertices.max(axis=0)
    center = 0.5 * (bbox_min + bbox_max)
    diagonal = np.linalg.norm(bbox_max - bbox_min)
    return center, diagonal


def angle_between_vectors(v1: np.ndarray, v2: np.ndarray) -> float:
    """Compute angle between two vectors in radians."""
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-12 or n2 < 1e-12:
        return 0.0
    cos_angle = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    return np.arccos(cos_angle)
