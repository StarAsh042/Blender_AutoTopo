/*
 * autotopo_native.cpp — optional C++ acceleration for Blender AutoTopo.
 *
 * Two default-hit Python hot paths are offloaded here:
 *
 *   1. autotopo_sharp_features()
 *      Builds the edge -> incident-face map required by the QuadWild
 *      ".sharp" feature export. The pure-Python version iterates all
 *      3*n_faces half-edges (1.8M at 600k faces, ~8.3 s) to fill a dict.
 *      Here it is a single open-addressing hash pass.
 *
 *   2. autotopo_max_nearest_distance()
 *      Directed Hausdorff distance used by silhouette evaluation:
 *      max over query points of the distance to the nearest reference
 *      point. The Python version was O(n_query * n_ref) brute force
 *      (tens of seconds, hundreds of MB of temporaries); here a kd-tree
 *      over the reference points gives O(n_ref log n_ref + n_query log n_ref).
 *
 * ─────────────────────────────────────────────────────────────────────
 * ABI CONTRACT (mirrored by utils/native.py — keep the two in sync)
 * ─────────────────────────────────────────────────────────────────────
 *  * extern "C", default __cdecl (x86_64: System V / Microsoft x64
 *    calling convention — no name mangling, no stack adjustment).
 *  * No C++ exception may cross the DLL boundary. Every entry point
 *    wraps its body in try/catch(...) and reports failures through a
 *    negative return code. Callers must treat any negative value as
 *    "unavailable, fall back to numpy".
 *  * All pointer arguments are validated for NULL and every length
 *    argument for negativity before any dereference. Index inputs are
 *    range-checked against the corresponding vertex count.
 *  * Input arrays are caller-owned, read-only, contiguous and are never
 *    retained past the call. Output arrays are caller-allocated with a
 *    documented capacity and only written.
 *  * Integer ABI types: int64_t for indices/counts, int32_t for the
 *    convexity flag, double for coordinates. This matches the numpy
 *    dtypes used by the loader (int64 / int32 / float64).
 *  * The DLL is self-contained (-static -static-libgcc -static-libstdc++)
 *    and exports only the four functions below.
 */

#include <cstdint>
#include <cstddef>
#include <cmath>
#include <vector>
#include <algorithm>
#include <limits>
#include <unordered_map>

#if defined(_WIN32)
#  define AUTOTOPO_EXPORT extern "C" __declspec(dllexport)
#else
#  define AUTOTOPO_EXPORT extern "C" __attribute__((visibility("default")))
#endif

namespace {

constexpr double kNormEps = 1e-12;

// ── kd-tree over a 3-D point cloud (median split, 3 axes) ──

struct KdNode {
    int64_t point;   // index into the reference array
    int32_t left;    // child node index or -1
    int32_t right;   // child node index or -1
    int32_t axis;    // splitting axis of this node
};

int32_t kd_build(int64_t lo, int64_t hi, int axis,
                 std::vector<int64_t>& idx, const double* pts,
                 std::vector<KdNode>& nodes) {
    if (lo >= hi) {
        return -1;
    }
    const int64_t mid = lo + (hi - lo) / 2;
    std::nth_element(
        idx.begin() + lo, idx.begin() + mid, idx.begin() + hi,
        [pts, axis](int64_t a, int64_t b) {
            return pts[a * 3 + axis] < pts[b * 3 + axis];
        });
    const int32_t node = static_cast<int32_t>(nodes.size());
    nodes.push_back(KdNode{idx[mid], -1, -1, axis});
    const int32_t l = kd_build(lo, mid, (axis + 1) % 3, idx, pts, nodes);
    const int32_t r = kd_build(mid + 1, hi, (axis + 1) % 3, idx, pts, nodes);
    nodes[node].left = l;
    nodes[node].right = r;
    return node;
}

void kd_nearest(int32_t node, const double* q, const double* pts,
                const std::vector<KdNode>& nodes, double& best2) {
    if (node < 0) {
        return;
    }
    const KdNode& nd = nodes[node];
    const double* p = pts + nd.point * 3;
    const double dx = q[0] - p[0];
    const double dy = q[1] - p[1];
    const double dz = q[2] - p[2];
    const double d2 = dx * dx + dy * dy + dz * dz;
    if (d2 < best2) {
        best2 = d2;
    }
    const int32_t axis = nd.axis;
    const double delta = q[axis] - p[axis];
    const int32_t near_child = (delta < 0.0) ? nd.left : nd.right;
    const int32_t far_child = (delta < 0.0) ? nd.right : nd.left;
    kd_nearest(near_child, q, pts, nodes, best2);
    if (delta * delta < best2) {
        kd_nearest(far_child, q, pts, nodes, best2);
    }
}

// Per-edge incidence slot. Only the first two incident half-edges are
// kept: the Python original reads locs[0] / locs[1] and only checks
// whether a second one exists (len(locs) < 2).
struct EdgeSlot {
    int64_t fi0 = -1;
    int64_t fi1 = -1;
    int32_t j0 = 0;
    int32_t j1 = 0;
    uint8_t count = 0;
};

inline uint64_t edge_key(int64_t u, int64_t v) {
    // u < v guaranteed by caller; both fit in 32 bits (checked up front).
    return (static_cast<uint64_t>(u) << 32) | static_cast<uint64_t>(v);
}

}  // namespace

// ── 1. Sharp feature extraction ──

/*
 * autotopo_sharp_features
 *
 * Inputs
 *   verts       : double[n_verts * 3]  vertex positions (contiguous)
 *   n_verts     : number of vertices (> 0)
 *   faces       : int64[n_faces * 3]   triangle indices, 0-based
 *   n_faces     : number of triangles (> 0)
 *   sharp_keys  : int64[n_sharp * 2]   sharp edges as (v0, v1) pairs
 *   n_sharp     : number of sharp edges (>= 0)
 *
 * Outputs (caller-allocated, capacity >= n_sharp; only the first
 * `return value` entries are written)
 *   out_convexity  : int32[n_sharp]   1 = convex / boundary, 0 = concave
 *   out_face_index : int64[n_sharp]   owning face index
 *   out_edge_pos   : int64[n_sharp]   edge position j within that face
 *
 * Returns
 *   >= 0 : number of feature lines produced (<= n_sharp)
 *   -1   : NULL pointer argument
 *   -2   : negative or zero count where a positive one is required
 *   -3   : face index out of [0, n_verts)
 *   -4   : n_verts does not fit the 32-bit key packing
 *   -5   : internal allocation failure (std::bad_alloc)
 */
AUTOTOPO_EXPORT int64_t autotopo_sharp_features(
    const double* verts, int64_t n_verts,
    const int64_t* faces, int64_t n_faces,
    const int64_t* sharp_keys, int64_t n_sharp,
    int32_t* out_convexity,
    int64_t* out_face_index,
    int64_t* out_edge_pos) {
    if (verts == nullptr || faces == nullptr) {
        return -1;
    }
    if (n_verts <= 0 || n_faces <= 0) {
        return -2;
    }
    if (n_sharp < 0) {
        return -2;
    }
    if (n_sharp > 0 &&
        (sharp_keys == nullptr || out_convexity == nullptr ||
         out_face_index == nullptr || out_edge_pos == nullptr)) {
        return -1;
    }
    if (n_verts >= (static_cast<int64_t>(1) << 32)) {
        return -4;
    }

    try {
        const size_t nf = static_cast<size_t>(n_faces);

        // Per-face unit normals (matches compute_face_normals) and
        // centroids (matches verts[faces].mean(axis=1)).
        std::vector<double> fn(nf * 3);
        std::vector<double> cen(nf * 3);
        for (size_t m = 0; m < nf; ++m) {
            const int64_t i0 = faces[m * 3 + 0];
            const int64_t i1 = faces[m * 3 + 1];
            const int64_t i2 = faces[m * 3 + 2];
            if (i0 < 0 || i1 < 0 || i2 < 0 ||
                i0 >= n_verts || i1 >= n_verts || i2 >= n_verts) {
                return -3;
            }
            const double* v0 = verts + i0 * 3;
            const double* v1 = verts + i1 * 3;
            const double* v2 = verts + i2 * 3;
            const double e1x = v1[0] - v0[0];
            const double e1y = v1[1] - v0[1];
            const double e1z = v1[2] - v0[2];
            const double e2x = v2[0] - v0[0];
            const double e2y = v2[1] - v0[1];
            const double e2z = v2[2] - v0[2];
            double nx = e1y * e2z - e1z * e2y;
            double ny = e1z * e2x - e1x * e2z;
            double nz = e1x * e2y - e1y * e2x;
            double nrm = std::sqrt(nx * nx + ny * ny + nz * nz);
            if (nrm < kNormEps) {
                nrm = kNormEps;
            }
            fn[m * 3 + 0] = nx / nrm;
            fn[m * 3 + 1] = ny / nrm;
            fn[m * 3 + 2] = nz / nrm;
            cen[m * 3 + 0] = (v0[0] + v1[0] + v2[0]) / 3.0;
            cen[m * 3 + 1] = (v0[1] + v1[1] + v2[1]) / 3.0;
            cen[m * 3 + 2] = (v0[2] + v1[2] + v2[2]) / 3.0;
        }

        // edge -> first two incident half-edges, in (face, j) order.
        std::unordered_map<uint64_t, EdgeSlot> incidence;
        incidence.reserve(nf * 3);
        for (size_t m = 0; m < nf; ++m) {
            for (int j = 0; j < 3; ++j) {
                const int64_t a = faces[m * 3 + j];
                const int64_t b = faces[m * 3 + (j + 1) % 3];
                const int64_t u = a < b ? a : b;
                const int64_t v = a < b ? b : a;
                const uint64_t key = edge_key(u, v);
                auto it = incidence.find(key);
                if (it == incidence.end()) {
                    EdgeSlot slot;
                    slot.fi0 = static_cast<int64_t>(m);
                    slot.j0 = j;
                    slot.count = 1;
                    incidence.emplace(key, slot);
                } else if (it->second.count == 1) {
                    it->second.fi1 = static_cast<int64_t>(m);
                    it->second.j1 = j;
                    it->second.count = 2;
                }
            }
        }

        int64_t out = 0;
        for (int64_t k = 0; k < n_sharp; ++k) {
            int64_t u = sharp_keys[k * 2 + 0];
            int64_t v = sharp_keys[k * 2 + 1];
            if (u < 0 || v < 0) {
                continue;
            }
            if (u > v) {
                const int64_t t = u;
                u = v;
                v = t;
            }
            const auto it = incidence.find(edge_key(u, v));
            if (it == incidence.end()) {
                continue;
            }
            const EdgeSlot& slot = it->second;
            const int64_t fi = slot.fi0;
            const int32_t j = slot.j0;
            int32_t convexity;
            if (slot.count < 2) {
                convexity = 1;  // boundary edge: treat as convex
            } else {
                const int64_t a = faces[fi * 3 + j];
                const double dx = cen[slot.fi1 * 3 + 0] - verts[a * 3 + 0];
                const double dy = cen[slot.fi1 * 3 + 1] - verts[a * 3 + 1];
                const double dz = cen[slot.fi1 * 3 + 2] - verts[a * 3 + 2];
                const double signed_v = fn[fi * 3 + 0] * dx +
                                        fn[fi * 3 + 1] * dy +
                                        fn[fi * 3 + 2] * dz;
                convexity = (signed_v < 0.0) ? 1 : 0;
            }
            out_convexity[out] = convexity;
            out_face_index[out] = fi;
            out_edge_pos[out] = static_cast<int64_t>(j);
            ++out;
        }
        return out;
    } catch (const std::bad_alloc&) {
        return -5;
    } catch (...) {
        return -5;
    }
}

// ── 2. Directed Hausdorff distance (max nearest-neighbour) ──

/*
 * autotopo_max_nearest_distance
 *
 * For every query point, find the distance to its nearest reference
 * point; return the maximum of those distances.
 *
 * Inputs
 *   query : double[n_query * 3]
 *   n_query : number of query points (>= 0)
 *   ref   : double[n_ref * 3]
 *   n_ref : number of reference points (>= 0)
 *
 * Returns
 *   >= 0.0 : the maximum nearest-neighbour distance
 *             (0.0 when either set is empty)
 *   -1.0   : NULL pointer argument
 *   -2.0   : negative count
 *   -3.0   : internal allocation failure
 */
AUTOTOPO_EXPORT double autotopo_max_nearest_distance(
    const double* query, int64_t n_query,
    const double* ref, int64_t n_ref) {
    if (n_query < 0 || n_ref < 0) {
        return -2.0;
    }
    if (n_query == 0 || n_ref == 0) {
        return 0.0;
    }
    if (query == nullptr || ref == nullptr) {
        return -1.0;
    }

    try {
        std::vector<int64_t> idx(static_cast<size_t>(n_ref));
        for (int64_t i = 0; i < n_ref; ++i) {
            idx[static_cast<size_t>(i)] = i;
        }
        std::vector<KdNode> nodes;
        nodes.reserve(static_cast<size_t>(n_ref));
        const int32_t root = kd_build(0, n_ref, 0, idx, ref, nodes);

        double max_dist = 0.0;
        for (int64_t q = 0; q < n_query; ++q) {
            double best2 = std::numeric_limits<double>::max();
            kd_nearest(root, query + q * 3, ref, nodes, best2);
            const double d = std::sqrt(best2);
            if (d > max_dist) {
                max_dist = d;
            }
        }
        return max_dist;
    } catch (...) {
        return -3.0;
    }
}

// ── 3. Capability / version probe ──

AUTOTOPO_EXPORT int32_t autotopo_native_abi(void) {
    return 1;
}

AUTOTOPO_EXPORT const char* autotopo_native_version(void) {
    return "autotopo_native/1.0.0";
}
