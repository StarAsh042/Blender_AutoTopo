"""Error-driven adaptive quad subdivision.

QuadWild produces a uniform-density quad mesh. This module
redistributes the face budget towards detail: quads are greedily
subdivided (midpoint scheme, 1 -> 4) where the geometric deviation
to the high-poly source surface is largest, so damaged / high
curvature regions become dense while flat regions stay sparse.

Design constraints:
- Pure numpy (+ optional mathutils.kdtree), no bpy data access —
  safe to run on the background worker thread.
- Edge midpoints are shared via an ``edge_key -> vertex`` dict so
  adjacent subdivided quads stay watertight.
- Subdivision depth is capped (``max_depth``) and a balance rule
  keeps adjacent quads within one depth level for smooth density
  transitions.
- After the greedy phase a conforming repair pass absorbs leftover
  edge midpoints into the coarser neighbours: 0/2/4 midpoints stay
  all-quad, odd cases (1/3) emit one transition triangle. This keeps
  the final mesh manifold.
"""

import heapq
from typing import Callable, List, Optional, Tuple

import numpy as np

from ..utils.logger import logger

# Stop subdividing when the best face error drops below this fraction
# of the source bounding box diagonal
_ERROR_EPS_FRACTION = 0.001
# The conforming repair pass inflates the face count (transition faces
# split into 2-4), so the greedy phase only spends this share of the
# budget
_GREEDY_BUDGET_FACTOR = 0.8


# ── Nearest-point queries against the source surface ──

class SurfaceQuery:
    """Nearest-point lookup on the high-poly source.

    Two backends are built when the data allows it:

    * a ``BVHTree`` over the source **surface** (vertices + triangles),
      queried through :meth:`nearest_on_surface`. It returns the closest
      point *on a triangle*, which is what projection must use: snapping
      to the nearest source *vertex* instead made many distinct
      subdivided vertices land on the same source vertex, collapsing the
      mesh into zero-area faces (measured: 1258/2034 faces at area ~0 and
      67.6% duplicated vertex positions).
    * a ``KDTree`` over the source **vertices**, kept for distance
      metrics and as a fallback.
    """

    def __init__(self, source_vertices: np.ndarray,
                 source_faces: Optional[np.ndarray] = None):
        self.verts = np.ascontiguousarray(source_vertices, dtype=np.float64)
        self._tree = None
        self._bvh = None
        self.faces = None
        self._vt_owner = None
        self._vt_starts = None

        tris = None
        if source_faces is not None and len(source_faces):
            f = np.asarray(source_faces)
            if f.ndim == 2 and f.shape[1] == 3:
                tris = f.astype(np.int64, copy=False)
                self.faces = tris

        if tris is not None:
            try:
                from mathutils.bvhtree import BVHTree
                self._bvh = BVHTree.FromPolygons(
                    self.verts.tolist(), tris.tolist(), all_triangles=True,
                )
            except Exception:
                self._bvh = None

            # vertex -> incident triangle adjacency, backing the numpy
            # closest-point-on-surface fallback used when mathutils is
            # unavailable (e.g. running the engine under system Python).
            flat = tris.ravel()
            owner = np.repeat(np.arange(len(tris)), 3)
            order = np.argsort(flat, kind='stable')
            self._vt_owner = owner[order]
            self._vt_starts = np.searchsorted(
                flat[order], np.arange(len(self.verts) + 1))

        try:
            from mathutils.kdtree import KDTree
            tree = KDTree(len(self.verts))
            for i, p in enumerate(self.verts):
                tree.insert((float(p[0]), float(p[1]), float(p[2])), i)
            tree.balance()
            self._tree = tree
        except Exception:
            self._tree = None  # numpy fallback

    @property
    def has_surface(self) -> bool:
        """True when closest-point-on-surface queries are available."""
        return self._bvh is not None or self._vt_starts is not None

    def _nearest_vertex_idx(self, points: np.ndarray) -> np.ndarray:
        """(K, 3) -> (K,) index of the closest source vertex (chunked)."""
        pts = np.asarray(points, dtype=np.float64)
        out = np.empty(len(pts), dtype=np.int64)
        chunk = 256
        for s in range(0, len(pts), chunk):
            b = pts[s:s + chunk]
            d2 = ((self.verts[None, :, :] - b[:, None, :]) ** 2).sum(axis=2)
            out[s:s + chunk] = np.argmin(d2, axis=1)
        return out

    def _closest_on_tris(self, p: np.ndarray, tris: np.ndarray) -> np.ndarray:
        """Closest point to ``p`` among ``tris`` (vectorized).

        Ericson, *Real-Time Collision Detection*, section 5.1.5.
        """
        A = self.verts[tris[:, 0]]
        B = self.verts[tris[:, 1]]
        C = self.verts[tris[:, 2]]
        ab, ac = B - A, C - A
        ap = p - A
        d1 = np.einsum('ij,ij->i', ab, ap)
        d2 = np.einsum('ij,ij->i', ac, ap)
        bp, cp = p - B, p - C
        d3 = np.einsum('ij,ij->i', ab, bp)
        d4 = np.einsum('ij,ij->i', ac, bp)
        d5 = np.einsum('ij,ij->i', ab, cp)
        d6 = np.einsum('ij,ij->i', ac, cp)

        vc = d1 * d4 - d3 * d2
        vb = d5 * d2 - d1 * d6
        va = d3 * d6 - d5 * d4

        res = A.copy()
        m = (d3 >= 0) & (d4 <= d3)
        res[m] = B[m]
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        if m.any():
            v = d1[m] / np.maximum(d1[m] - d3[m], 1e-30)
            res[m] = A[m] + v[:, None] * ab[m]
        m = (d6 >= 0) & (d5 <= d6)
        res[m] = C[m]
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        if m.any():
            w = d2[m] / np.maximum(d2[m] - d6[m], 1e-30)
            res[m] = A[m] + w[:, None] * ac[m]
        m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        if m.any():
            w = (d4[m] - d3[m]) / np.maximum(
                (d4[m] - d3[m]) + (d5[m] - d6[m]), 1e-30)
            res[m] = B[m] + w[:, None] * (C[m] - B[m])
        denom = va + vb + vc
        m = denom > 0
        if m.any():
            d = np.maximum(denom[m], 1e-30)
            res[m] = (A[m] + (vb[m] / d)[:, None] * ab[m]
                      + (vc[m] / d)[:, None] * ac[m])
        return res

    def nearest_on_surface(
        self, points: np.ndarray
    ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """(K, 3) points -> closest point on the source *surface*.

        Returns ``(coords (K, 3), distances (K,))``, or ``None`` when no
        surface backend is available.
        """
        points = np.asarray(points, dtype=np.float64)
        if len(points) == 0:
            return np.zeros((0, 3)), np.zeros(0)

        if self._bvh is not None:
            coords = np.empty((len(points), 3))
            dists = np.empty(len(points))
            for i, p in enumerate(points):
                loc, _n, _i, d = self._bvh.find_nearest(
                    (float(p[0]), float(p[1]), float(p[2]))
                )
                if loc is None:
                    return None
                coords[i] = (loc[0], loc[1], loc[2])
                dists[i] = d
            return coords, dists

        if self._vt_starts is None:
            return None

        # numpy fallback: nearest source vertex, then the exact closest
        # point over that vertex's incident triangles.
        idx = self._nearest_vertex_idx(points)
        coords = np.empty((len(points), 3))
        dists = np.empty(len(points))
        for i, (p, vi) in enumerate(zip(points, idx)):
            s, e = self._vt_starts[vi], self._vt_starts[vi + 1]
            tri_ids = self._vt_owner[s:e]
            if len(tri_ids) == 0:
                coords[i] = p
                dists[i] = float(np.linalg.norm(p - self.verts[vi]))
                continue
            cp = self._closest_on_tris(p, self.faces[tri_ids])
            j = int(np.argmin(((cp - p) ** 2).sum(axis=1)))
            coords[i] = cp[j]
            dists[i] = float(np.linalg.norm(cp[j] - p))
        return coords, dists

    def nearest_batch(
        self, points: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """(K, 3) points -> (nearest coords (K, 3), distances (K,))."""
        points = np.asarray(points, dtype=np.float64)
        if self._tree is not None:
            coords = np.empty((len(points), 3))
            dists = np.empty(len(points))
            for i, p in enumerate(points):
                co, _, d = self._tree.find(
                    (float(p[0]), float(p[1]), float(p[2]))
                )
                coords[i] = (co[0], co[1], co[2])
                dists[i] = d
            return coords, dists

        # Chunked numpy brute force (bounded memory)
        coords = np.empty((len(points), 3))
        dists = np.empty(len(points))
        chunk = 256
        for s in range(0, len(points), chunk):
            batch = points[s:s + chunk]
            d2 = np.sum(
                (self.verts[np.newaxis, :, :] - batch[:, np.newaxis, :]) ** 2,
                axis=2,
            )
            idx = np.argmin(d2, axis=1)
            rows = np.arange(len(idx))
            coords[s:s + chunk] = self.verts[idx]
            dists[s:s + chunk] = np.sqrt(d2[rows, idx])
        return coords, dists


# ── Main entry ──

def adaptive_subdivide(
    vertices: np.ndarray,
    quad_faces: List[Tuple[int, ...]],
    source_vertices: np.ndarray,
    target_face_count: int,
    max_depth: int = 3,
    progress_callback: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    source_faces: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, List[tuple], int]:
    """Adaptively subdivide a quad mesh towards detail regions.

    Args:
        vertices: (N, 3) base mesh vertices
        quad_faces: Base quad faces (index tuples, len == 4)
        source_vertices: High-poly vertices for error / reprojection
        target_face_count: Face budget for the output
        max_depth: Max subdivision depth per quad lineage
        progress_callback: (percent 0..100) progress reporting
        cancel_check: Returns True if the user cancelled
        source_faces: Source triangle indices, enabling closest-point-on-
            *surface* projection. When omitted, new vertices keep their
            geometric position instead of snapping to the nearest source
            vertex (which collapses the mesh into zero-area faces).

    Returns:
        (new_vertices, faces, tri_count) where faces are index tuples
        (quads + a few transition triangles) and tri_count is the
        number of triangles in the list.
    """
    verts = [np.asarray(v, dtype=np.float64) for v in vertices]
    query = SurfaceQuery(source_vertices, source_faces)

    def _snap_batch(points: np.ndarray) -> np.ndarray:
        """Closest point on the source *surface*; input unchanged if absent."""
        res = query.nearest_on_surface(points)
        if res is None:
            return np.asarray(points, dtype=np.float64)
        return res[0]

    # Snap base vertices onto the source surface so the coarse mesh hugs
    # the high-poly shape before subdivision starts. This must use the
    # closest point on the surface — snapping to the closest source
    # *vertex* collapses distinct vertices onto one another.
    if len(verts):
        snapped = _snap_batch(np.asarray(verts))
        verts = [snapped[i] for i in range(len(verts))]

    bbox_diag = float(np.ptp(np.asarray(verts), axis=0).max()) \
        if len(verts) > 1 else 1.0
    eps_stop = max(bbox_diag * _ERROR_EPS_FRACTION, 1e-12)
    # Minimum separation a projected vertex must keep from the parents it
    # was derived from; anything closer yields a (near) zero-area face.
    _MIN_SEP = max(bbox_diag * 1e-4, 1e-12)

    # Face records (flat lists for speed)
    faces = [list(f) for f in quad_faces if len(f) == 4]
    alive = [True] * len(faces)
    depths = [0] * len(faces)
    errors = [0.0] * len(faces)
    versions = [0] * len(faces)

    edge_mid = {}      # (min, max) -> midpoint vertex index
    edge_owner = {}    # (min, max) -> set of live face ids
    mid_parent = {}    # midpoint vertex index -> parent edge endpoints

    def edge_key(a: int, b: int) -> Tuple[int, int]:
        return (a, b) if a < b else (b, a)

    for fi, face in enumerate(faces):
        for j in range(4):
            key = edge_key(face[j], face[(j + 1) % 4])
            edge_owner.setdefault(key, set()).add(fi)

    def project(point: np.ndarray, parents: Tuple[int, ...] = ()) -> np.ndarray:
        """Snap a new vertex onto the source surface.

        Never collapses onto a parent vertex: if the projection lands
        within ``_MIN_SEP`` of one of the parents that generated this
        point, the un-projected (geometric) position is kept instead.
        Projecting unconditionally is what produced zero-area faces.
        """
        snapped = _snap_batch(point.reshape(1, 3))[0]
        for g in parents:
            if float(np.linalg.norm(snapped - verts[g])) < _MIN_SEP:
                return point
        return snapped

    def get_edge_mid(a: int, b: int) -> int:
        key = edge_key(a, b)
        idx = edge_mid.get(key)
        if idx is None:
            mid = 0.5 * (verts[a] + verts[b])
            verts.append(project(mid, (a, b)))
            idx = len(verts) - 1
            edge_mid[key] = idx
            mid_parent[idx] = (a, b)
        return idx

    def face_error(face: List[int]) -> float:
        """Max distance of 9 sample points to the source surface."""
        a, b, c, d = (verts[v] for v in face)
        samples = np.array([
            a, b, c, d,
            0.5 * (a + b), 0.5 * (b + c), 0.5 * (c + d), 0.5 * (d + a),
            0.25 * (a + b + c + d),
        ])
        # Distance to the source *surface* (falling back to the nearest
        # source vertex when no surface backend exists). Measuring to the
        # nearest source *vertex* instead mostly reports the source grid
        # spacing, not the geometric deviation, which made the greedy
        # order effectively noise-driven.
        res = query.nearest_on_surface(samples)
        if res is not None:
            return float(res[1].max())
        _, dists = query.nearest_batch(samples)
        return float(dists.max())

    def _top_ancestor(a: int, b: int) -> Tuple[int, int]:
        """Walk up the midpoint hierarchy to the topmost edge
        containing (a, b)."""
        while True:
            up = None
            if a in mid_parent:
                pa, pb = mid_parent[a]
                if b in (pa, pb):
                    up = (pa, pb)
            if up is None and b in mid_parent:
                pa, pb = mid_parent[b]
                if a in (pa, pb):
                    up = (pa, pb)
            if up is None:
                return a, b
            a, b = up

    def _collect_edge_owners(a: int, b: int, out: set):
        """Owners registered anywhere along the (a, b) edge hierarchy.

        A coarse face keeps the parent edge while a subdivided
        neighbour holds its child edges, so adjacency must be
        resolved across all levels of the midpoint hierarchy.
        """
        key = edge_key(a, b)
        owners = edge_owner.get(key)
        if owners:
            out.update(owners)
        m = edge_mid.get(key)
        if m is not None:
            _collect_edge_owners(a, m, out)
            _collect_edge_owners(m, b, out)

    def live_neighbors(fi: int) -> List[int]:
        result = []
        seen = set()
        face = faces[fi]
        for j in range(4):
            a, b = face[j], face[(j + 1) % 4]
            ta, tb = _top_ancestor(a, b)
            owners = set()
            _collect_edge_owners(ta, tb, owners)
            for other in owners:
                if other != fi and alive[other] and other not in seen:
                    seen.add(other)
                    result.append(other)
        return result

    def can_subdivide(fi: int) -> bool:
        """Balance rule: neighbours must be at least as deep."""
        d = depths[fi]
        for nb in live_neighbors(fi):
            if depths[nb] < d:
                return False
        return True

    heap = []

    def push(fi: int):
        versions[fi] += 1
        heapq.heappush(heap, (-errors[fi], fi, versions[fi]))

    # Initial errors + heap
    for fi in range(len(faces)):
        errors[fi] = face_error(faces[fi])
        push(fi)
    if progress_callback:
        progress_callback(5.0)

    n_faces = len(faces)
    target = int(target_face_count)
    greedy_target = int(target * _GREEDY_BUDGET_FACTOR)
    iters = 0

    def subdivide(fi: int):
        """Midpoint subdivision: 1 quad -> 4 quads (shared midpoints)."""
        nonlocal n_faces
        a, b, c, d = faces[fi]
        m_ab = get_edge_mid(a, b)
        m_bc = get_edge_mid(b, c)
        m_cd = get_edge_mid(c, d)
        m_da = get_edge_mid(d, a)
        center = 0.25 * (verts[a] + verts[b] + verts[c] + verts[d])
        verts.append(project(center, (a, b, c, d)))
        ctr = len(verts) - 1

        child_defs = [
            (a, m_ab, ctr, m_da),
            (m_ab, b, m_bc, ctr),
            (ctr, m_bc, c, m_cd),
            (m_da, ctr, m_cd, d),
        ]

        # Unregister parent
        alive[fi] = False
        for j in range(4):
            v0, v1 = faces[fi][j], faces[fi][(j + 1) % 4]
            owners = edge_owner.get(edge_key(v0, v1))
            if owners:
                owners.discard(fi)

        child_ids = []
        for cd in child_defs:
            fid = len(faces)
            faces.append(list(cd))
            alive.append(True)
            depths.append(depths[fi] + 1)
            errors.append(face_error(list(cd)))
            versions.append(0)
            for j in range(4):
                key = edge_key(cd[j], cd[(j + 1) % 4])
                edge_owner.setdefault(key, set()).add(fid)
            child_ids.append(fid)

        n_faces += 3
        for fid in child_ids:
            push(fid)
        for fid in child_ids:
            for nb in live_neighbors(fid):
                push(nb)

    # ── Greedy subdivision loop ──
    # The heap is ordered by geometric error, so once the top face is
    # below the error threshold all remaining faces are flat as well.
    # The balance rule keeps adjacent quads within one depth level;
    # faces blocked by it force their shallower neighbours to
    # subdivide ONLY when those neighbours' own error warrants it —
    # otherwise the density jump is left to the conforming repair
    # pass, so flat regions do not fill up with forced subdivisions
    # and transition triangles.
    while n_faces + 3 <= greedy_target and heap:
        if cancel_check and cancel_check():
            raise InterruptedError("用户取消")

        _, fi, ver = heapq.heappop(heap)
        if not alive[fi] or ver != versions[fi]:
            continue
        if depths[fi] >= max_depth:
            continue

        # NOTE: there is deliberately no early exit when the worst face
        # drops below ``eps_stop``. The heap is ordered by geometric
        # error, so any remaining budget is always spent on the faces
        # that deviate most — which is exactly what adaptive density
        # means. Stopping early under-used the budget badly (measured
        # 140 faces for a budget of 800), because a surface-accurate mesh
        # reaches a low error long before it reaches the requested
        # density.

        if not can_subdivide(fi):
            # Blocked by the balance rule: force the shallower
            # neighbours that are themselves allowed to subdivide AND
            # have enough geometric error of their own, then retry
            # this face later.
            forced = False
            for nb in live_neighbors(fi):
                if alive[nb] and depths[nb] < depths[fi] \
                        and depths[nb] < max_depth and can_subdivide(nb) \
                        and errors[nb] >= eps_stop:
                    subdivide(nb)
                    forced = True
            if forced:
                push(fi)
            continue

        subdivide(fi)

        iters += 1
        if progress_callback and iters % 32 == 0:
            pct = 5.0 + 85.0 * min(1.0, n_faces / max(target, 1))
            progress_callback(pct)

    # ── Conforming repair pass ──
    # Absorb leftover edge midpoints into live faces so the result is
    # manifold. Odd midpoint counts emit one transition triangle.
    final_faces = []
    tri_count = 0

    def split_k4(face: List[int]) -> None:
        """Standard 4-split with shared edge midpoints + new center."""
        nonlocal tri_count
        a, b, c, d = face
        m_ab = get_edge_mid(a, b)
        m_bc = get_edge_mid(b, c)
        m_cd = get_edge_mid(c, d)
        m_da = get_edge_mid(d, a)
        center = 0.25 * (verts[a] + verts[b] + verts[c] + verts[d])
        verts.append(project(center, (a, b, c, d)))
        ctr = len(verts) - 1
        final_faces.extend([
            (a, m_ab, ctr, m_da),
            (m_ab, b, m_bc, ctr),
            (ctr, m_bc, c, m_cd),
            (m_da, ctr, m_cd, d),
        ])

    for fi, face in enumerate(faces):
        if not alive[fi]:
            continue
        mids = []
        for j in range(4):
            key = edge_key(face[j], face[(j + 1) % 4])
            mids.append(edge_mid.get(key))
        k = sum(1 for m in mids if m is not None)

        if k == 0:
            final_faces.append(tuple(face))
        elif k == 4:
            split_k4(face)
        elif k == 2:
            i0, i1 = [i for i, m in enumerate(mids) if m is not None]
            if (i0 + 2) % 4 == i1 or (i1 + 2) % 4 == i0:
                # Opposite edges: split between the two midpoints
                i = i0
                m_i, m_o = mids[i], mids[(i + 2) % 4]
                final_faces.append(
                    (m_i, face[(i + 1) % 4], face[(i + 2) % 4], m_o))
                final_faces.append((m_o, face[(i + 3) % 4], face[i], m_i))
            else:
                # Adjacent edges: corner quad + remainder quad
                i = i0 if mids[(i0 + 1) % 4] is not None else i1
                m_i, m_n = mids[i], mids[(i + 1) % 4]
                final_faces.append(
                    (face[i], m_i, face[(i + 1) % 4], m_n))
                final_faces.append(
                    (face[i], m_n, face[(i + 2) % 4], face[(i + 3) % 4]))
        elif k == 1:
            # Pentagon -> 1 quad + 1 transition triangle
            i = next(j for j, m in enumerate(mids) if m is not None)
            m_i = mids[i]
            final_faces.append(
                (m_i, face[(i + 1) % 4], face[(i + 2) % 4],
                 face[(i + 3) % 4]))
            final_faces.append((face[i], m_i, face[(i + 3) % 4]))
            tri_count += 1
        else:  # k == 3 -> heptagon -> 2 quads + 1 transition triangle
            miss = next(j for j, m in enumerate(mids) if m is None)
            # Rotate so the missing edge is the last one (index 3)
            order = [(miss + 1 + j) % 4 for j in range(4)]
            p = [face[o] for o in order]
            m0, m1, m2 = (
                mids[order[0]], mids[order[1]], mids[order[2]])
            final_faces.append((p[0], m0, p[1], m1))
            final_faces.append((m1, p[2], m2, p[3]))
            final_faces.append((m1, p[3], p[0]))
            tri_count += 1

    if progress_callback:
        progress_callback(100.0)

    out_verts = np.asarray(verts, dtype=np.float64)
    logger.info(
        f"Adaptive subdivision: {len(quad_faces)} -> {len(final_faces)} "
        f"faces ({tri_count} transition tris), {iters} subdivisions"
    )
    return out_verts, final_faces, tri_count
