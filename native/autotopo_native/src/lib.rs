//! autotopo_native — Rust acceleration core for the Blender AutoTopo addon.
//!
//! Replaces the former C++ implementation (`native/autotopo_native.cpp`,
//! MinGW build). Two default-hit Python hot paths are offloaded here:
//!
//! 1. [`autotopo_sharp_features`] — builds the edge → incident-face map
//!    required by the QuadWild `.sharp` feature export.
//! 2. [`autotopo_max_nearest_distance`] — directed Hausdorff distance
//!    used by silhouette evaluation (max over query points of the
//!    distance to the nearest reference point).
//!
//! ─────────────────────────────────────────────────────────────────────
//! ABI CONTRACT (mirrored by `utils/native.py` — keep the two in sync)
//! ─────────────────────────────────────────────────────────────────────
//!
//! * `extern "C"`, `#[no_mangle]`: no name mangling, no stack
//!   adjustment (x86_64 Microsoft x64 calling convention).
//! * **No panic may cross the DLL boundary.** Every entry point wraps
//!   its body in [`std::panic::catch_unwind`] and reports failures
//!   through a negative return code. Callers must treat any negative
//!   value as "unavailable, fall back to numpy".
//! * All pointer arguments are validated for NULL and every length
//!   argument for negativity before any dereference. Index inputs are
//!   range-checked against the corresponding vertex count.
//! * Input arrays are caller-owned, read-only, contiguous and are never
//!   retained past the call. Output arrays are caller-allocated with a
//!   documented capacity and only written.
//! * Integer ABI types: `i64` for indices/counts, `i32` for the
//!   convexity flag, `f64` for coordinates. This matches the numpy
//!   dtypes used by the loader (int64 / int32 / float64).
//! * The DLL is self-contained (static CRT, see `.cargo/config.toml`)
//!   and exports only the four functions below.
//!
//! Behavior is locked bit-for-bit against the golden master captured
//! from the C++ implementation — see `test/test_native_golden.py`.

use std::os::raw::c_char;
use std::panic::{catch_unwind, AssertUnwindSafe};

/// ABI revision implemented by this crate. Bump together with
/// `_EXPECTED_ABI` in `utils/native.py` whenever the signatures change.
const ABI_VERSION: i32 = 1;

/// Run `f`, containing any panic at the FFI boundary.
///
/// A panicking kernel must never unwind into the host process: the
/// failure is mapped to `on_panic` (the documented "internal error"
/// code for the respective entry point).
fn ffi_guard<T>(f: impl FnOnce() -> T, on_panic: T) -> T {
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(value) => value,
        Err(_) => on_panic,
    }
}

// ── 1. Sharp feature extraction ──

/*
 * autotopo_sharp_features
 *
 * Inputs
 *   verts       : &[f64] of length n_verts * 3   vertex positions
 *   n_verts     : number of vertices (> 0)
 *   faces       : &[i64] of length n_faces * 3   triangle indices, 0-based
 *   n_faces     : number of triangles (> 0)
 *   sharp_keys  : &[i64] of length n_sharp * 2   sharp edges as (v0, v1)
 *   n_sharp     : number of sharp edges (>= 0)
 *
 * Outputs (caller-allocated, capacity >= n_sharp; only the first
 * `return value` entries are written)
 *   out_convexity  : &mut [i32]   1 = convex / boundary, 0 = concave
 *   out_face_index : &mut [i64]   owning face index
 *   out_edge_pos   : &mut [i64]   edge position j within that face
 *
 * Returns
 *   >= 0 : number of feature lines produced (<= n_sharp)
 *   -1   : NULL pointer argument
 *   -2   : negative or zero count where a positive one is required
 *   -3   : face index out of [0, n_verts)
 *   -4   : n_verts does not fit the 32-bit key packing
 *   -5   : internal failure (allocation / panic contained at the FFI
 *          boundary / not yet implemented)
 */
// The 9-argument signature is fixed by the C ABI contract mirrored in
// utils/native.py; changing it would require changing the loader too.
#[allow(clippy::too_many_arguments)]
#[no_mangle]
pub extern "C" fn autotopo_sharp_features(
    verts: *const f64,
    n_verts: i64,
    faces: *const i64,
    n_faces: i64,
    sharp_keys: *const i64,
    n_sharp: i64,
    out_convexity: *mut i32,
    out_face_index: *mut i64,
    out_edge_pos: *mut i64,
) -> i64 {
    ffi_guard(
        || {
            sharp_features_impl(
                verts,
                n_verts,
                faces,
                n_faces,
                sharp_keys,
                n_sharp,
                out_convexity,
                out_face_index,
                out_edge_pos,
            )
        },
        -5,
    )
}

#[allow(clippy::too_many_arguments)]
fn sharp_features_impl(
    verts: *const f64,
    n_verts: i64,
    faces: *const i64,
    n_faces: i64,
    sharp_keys: *const i64,
    n_sharp: i64,
    out_convexity: *mut i32,
    out_face_index: *mut i64,
    out_edge_pos: *mut i64,
) -> i64 {
    if verts.is_null() || faces.is_null() {
        return -1;
    }
    if n_verts <= 0 || n_faces <= 0 {
        return -2;
    }
    if n_sharp < 0 {
        return -2;
    }
    if n_sharp > 0
        && (sharp_keys.is_null()
            || out_convexity.is_null()
            || out_face_index.is_null()
            || out_edge_pos.is_null())
    {
        return -1;
    }
    if n_verts >= (1i64 << 32) {
        return -4;
    }

    // SAFETY: all pointers were validated non-null above and every
    // length is positive; the caller guarantees the buffers hold
    // n_verts*3 / n_faces*3 / n_sharp*2 elements and that the outputs
    // have capacity >= n_sharp (see the ABI contract above).
    unsafe {
        sharp_features_kernel(
            verts,
            n_verts,
            faces,
            n_faces,
            sharp_keys,
            n_sharp,
            out_convexity,
            out_face_index,
            out_edge_pos,
        )
    }
}

/// Per-edge incidence slot. Only the first two incident half-edges are
/// kept, mirroring the C++ implementation (and the Python original,
/// which reads `locs[0]` / `locs[1]` and only checks whether a second
/// one exists).
#[derive(Clone, Copy, Default)]
struct EdgeSlot {
    fi0: i64,
    fi1: i64,
    j0: i32,
    j1: i32,
    count: u8,
}

/// The sharp-feature kernel. Inputs must have been validated by
/// `sharp_features_impl`; this function is `unsafe` because it
/// dereferences the raw ABI buffers.
#[allow(clippy::too_many_arguments)]
unsafe fn sharp_features_kernel(
    verts: *const f64,
    n_verts: i64,
    faces: *const i64,
    n_faces: i64,
    sharp_keys: *const i64,
    n_sharp: i64,
    out_convexity: *mut i32,
    out_face_index: *mut i64,
    out_edge_pos: *mut i64,
) -> i64 {
    use std::collections::hash_map::Entry;
    use std::collections::HashMap;

    // Degenerate-face normal clamp, matching the C++ kNormEps.
    const NORM_EPS: f64 = 1e-12;

    let nf = n_faces as usize;
    let verts = std::slice::from_raw_parts(verts, n_verts as usize * 3);
    let faces = std::slice::from_raw_parts(faces, nf * 3);

    // Per-face unit normals (matches compute_face_normals) and
    // centroids (matches verts[faces].mean(axis=1)). try_reserve keeps
    // the documented -5 contract on allocation failure (the C++ side
    // caught std::bad_alloc).
    let mut fnorm: Vec<f64> = Vec::new();
    let mut cen: Vec<f64> = Vec::new();
    if fnorm.try_reserve_exact(nf * 3).is_err() || cen.try_reserve_exact(nf * 3).is_err() {
        return -5;
    }
    fnorm.resize(nf * 3, 0.0);
    cen.resize(nf * 3, 0.0);

    for m in 0..nf {
        let i0 = faces[m * 3];
        let i1 = faces[m * 3 + 1];
        let i2 = faces[m * 3 + 2];
        if i0 < 0 || i1 < 0 || i2 < 0 || i0 >= n_verts || i1 >= n_verts || i2 >= n_verts {
            return -3;
        }
        let (i0, i1, i2) = (i0 as usize, i1 as usize, i2 as usize);
        let v0 = &verts[i0 * 3..i0 * 3 + 3];
        let v1 = &verts[i1 * 3..i1 * 3 + 3];
        let v2 = &verts[i2 * 3..i2 * 3 + 3];
        let e1x = v1[0] - v0[0];
        let e1y = v1[1] - v0[1];
        let e1z = v1[2] - v0[2];
        let e2x = v2[0] - v0[0];
        let e2y = v2[1] - v0[1];
        let e2z = v2[2] - v0[2];
        let nx = e1y * e2z - e1z * e2y;
        let ny = e1z * e2x - e1x * e2z;
        let nz = e1x * e2y - e1y * e2x;
        let mut nrm = (nx * nx + ny * ny + nz * nz).sqrt();
        if nrm < NORM_EPS {
            nrm = NORM_EPS;
        }
        fnorm[m * 3] = nx / nrm;
        fnorm[m * 3 + 1] = ny / nrm;
        fnorm[m * 3 + 2] = nz / nrm;
        cen[m * 3] = (v0[0] + v1[0] + v2[0]) / 3.0;
        cen[m * 3 + 1] = (v0[1] + v1[1] + v2[1]) / 3.0;
        cen[m * 3 + 2] = (v0[2] + v1[2] + v2[2]) / 3.0;
    }

    // edge -> first two incident half-edges, in (face, j) order.
    let mut incidence: HashMap<u64, EdgeSlot> = HashMap::new();
    if incidence.try_reserve(nf * 3).is_err() {
        return -5;
    }
    for m in 0..nf {
        for j in 0..3usize {
            let a = faces[m * 3 + j];
            let b = faces[m * 3 + (j + 1) % 3];
            let (u, v) = if a < b { (a, b) } else { (b, a) };
            let key = ((u as u64) << 32) | v as u64;
            match incidence.entry(key) {
                Entry::Occupied(mut e) => {
                    let slot = e.get_mut();
                    if slot.count == 1 {
                        slot.fi1 = m as i64;
                        slot.j1 = j as i32;
                        slot.count = 2;
                    }
                }
                Entry::Vacant(e) => {
                    e.insert(EdgeSlot {
                        fi0: m as i64,
                        fi1: -1,
                        j0: j as i32,
                        j1: 0,
                        count: 1,
                    });
                }
            }
        }
    }

    let keys: &[i64] = if n_sharp > 0 {
        std::slice::from_raw_parts(sharp_keys, n_sharp as usize * 2)
    } else {
        &[]
    };

    let mut out: i64 = 0;
    for k in 0..n_sharp as usize {
        let mut u = keys[k * 2];
        let mut v = keys[k * 2 + 1];
        if u < 0 || v < 0 {
            continue;
        }
        if u > v {
            std::mem::swap(&mut u, &mut v);
        }
        let key = ((u as u64) << 32) | v as u64;
        let slot = match incidence.get(&key) {
            Some(s) => s,
            None => continue,
        };
        let fi = slot.fi0;
        let j = slot.j0;
        let convexity: i32 = if slot.count < 2 {
            1 // boundary edge: treat as convex
        } else {
            let a = faces[fi as usize * 3 + j as usize] as usize;
            let dx = cen[slot.fi1 as usize * 3] - verts[a * 3];
            let dy = cen[slot.fi1 as usize * 3 + 1] - verts[a * 3 + 1];
            let dz = cen[slot.fi1 as usize * 3 + 2] - verts[a * 3 + 2];
            let signed_v = fnorm[fi as usize * 3] * dx
                + fnorm[fi as usize * 3 + 1] * dy
                + fnorm[fi as usize * 3 + 2] * dz;
            if signed_v < 0.0 {
                1
            } else {
                0
            }
        };
        *out_convexity.add(out as usize) = convexity;
        *out_face_index.add(out as usize) = fi;
        *out_edge_pos.add(out as usize) = j as i64;
        out += 1;
    }
    out
}

// ── 2. Directed Hausdorff distance (max nearest-neighbour) ──

/*
 * autotopo_max_nearest_distance
 *
 * For every query point, find the distance to its nearest reference
 * point; return the maximum of those distances.
 *
 * Inputs
 *   query   : &[f64] of length n_query * 3
 *   n_query : number of query points (>= 0)
 *   ref_    : &[f64] of length n_ref * 3
 *   n_ref   : number of reference points (>= 0)
 *
 * Returns
 *   >= 0.0 : the maximum nearest-neighbour distance
 *            (0.0 when either set is empty)
 *   -1.0   : NULL pointer argument
 *   -2.0   : negative count
 *   -3.0   : internal failure (allocation / panic / not yet implemented)
 */
#[no_mangle]
pub extern "C" fn autotopo_max_nearest_distance(
    query: *const f64,
    n_query: i64,
    ref_: *const f64,
    n_ref: i64,
) -> f64 {
    ffi_guard(
        || max_nearest_distance_impl(query, n_query, ref_, n_ref),
        -3.0,
    )
}

fn max_nearest_distance_impl(query: *const f64, n_query: i64, ref_: *const f64, n_ref: i64) -> f64 {
    if n_query < 0 || n_ref < 0 {
        return -2.0;
    }
    if n_query == 0 || n_ref == 0 {
        return 0.0;
    }
    if query.is_null() || ref_.is_null() {
        return -1.0;
    }

    // SAFETY: pointers validated non-null above, counts positive; the
    // caller guarantees n_query*3 / n_ref*3 readable doubles.
    unsafe { max_nearest_distance_kernel(query, n_query, ref_, n_ref) }
}

/// kd-tree node over a 3-D point cloud (median split, 3 axes).
struct KdNode {
    point: i64, // index into the reference array
    left: i32,  // child node index or -1
    right: i32, // child node index or -1
    axis: i32,  // splitting axis of this node
}

/// Median-split build over `idx[lo..hi)`, mirroring the C++
/// `std::nth_element` partition. The resulting tree shape may differ
/// from the C++ build for equal axis coordinates, but nearest-neighbour
/// queries are exact (the minimum does not depend on traversal order),
/// so the returned distance is bit-identical.
unsafe fn kd_build(
    lo: i64,
    hi: i64,
    axis: i32,
    idx: &mut [i64],
    pts: &[f64],
    nodes: &mut Vec<KdNode>,
) -> i32 {
    if lo >= hi {
        return -1;
    }
    let mid = lo + (hi - lo) / 2;
    let (lo_u, hi_u) = (lo as usize, hi as usize);
    idx[lo_u..hi_u].select_nth_unstable_by((mid as usize) - lo_u, |a, b| {
        // NaN coordinates compare as Equal (defined behavior; the C++
        // side left this unspecified). Inputs with NaN never reach the
        // shipped golden fixtures.
        pts[*a as usize * 3 + axis as usize]
            .partial_cmp(&pts[*b as usize * 3 + axis as usize])
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let node = nodes.len() as i32;
    nodes.push(KdNode {
        point: idx[mid as usize],
        left: -1,
        right: -1,
        axis,
    });
    let l = kd_build(lo, mid, (axis + 1) % 3, idx, pts, nodes);
    let r = kd_build(mid + 1, hi, (axis + 1) % 3, idx, pts, nodes);
    nodes[node as usize].left = l;
    nodes[node as usize].right = r;
    node
}

/// Exact nearest-neighbour search for `q`, updating `best2` (squared
/// distance) in place. Mirrors the C++ traversal: near child first,
/// far child only when the splitting-plane distance can still beat
/// `best2`.
unsafe fn kd_nearest(node: i32, q: &[f64], pts: &[f64], nodes: &[KdNode], best2: &mut f64) {
    if node < 0 {
        return;
    }
    let nd = &nodes[node as usize];
    let p = &pts[nd.point as usize * 3..nd.point as usize * 3 + 3];
    let dx = q[0] - p[0];
    let dy = q[1] - p[1];
    let dz = q[2] - p[2];
    let d2 = dx * dx + dy * dy + dz * dz;
    if d2 < *best2 {
        *best2 = d2;
    }
    let axis = nd.axis as usize;
    let delta = q[axis] - p[axis];
    let (near_child, far_child) = if delta < 0.0 {
        (nd.left, nd.right)
    } else {
        (nd.right, nd.left)
    };
    kd_nearest(near_child, q, pts, nodes, best2);
    if delta * delta < *best2 {
        kd_nearest(far_child, q, pts, nodes, best2);
    }
}

unsafe fn max_nearest_distance_kernel(
    query: *const f64,
    n_query: i64,
    ref_: *const f64,
    n_ref: i64,
) -> f64 {
    let (n_query, n_ref) = (n_query as usize, n_ref as usize);
    let query = std::slice::from_raw_parts(query, n_query * 3);
    let ref_pts = std::slice::from_raw_parts(ref_, n_ref * 3);

    let mut idx: Vec<i64> = Vec::new();
    let mut nodes: Vec<KdNode> = Vec::new();
    if idx.try_reserve_exact(n_ref).is_err() || nodes.try_reserve(n_ref).is_err() {
        return -3.0;
    }
    idx.extend(0..n_ref as i64);
    let root = kd_build(0, n_ref as i64, 0, &mut idx, ref_pts, &mut nodes);

    let mut max_dist = 0.0f64;
    for q in 0..n_query {
        let mut best2 = f64::MAX;
        kd_nearest(root, &query[q * 3..q * 3 + 3], ref_pts, &nodes, &mut best2);
        let d = best2.sqrt();
        if d > max_dist {
            max_dist = d;
        }
    }
    max_dist
}

// ── 3. Capability / version probe ──

#[no_mangle]
pub extern "C" fn autotopo_native_abi() -> i32 {
    ABI_VERSION
}

#[no_mangle]
pub extern "C" fn autotopo_native_version() -> *const c_char {
    concat!("autotopo_native/", env!("CARGO_PKG_VERSION"), "\0").as_ptr() as *const c_char
}

// ── tests ──

#[cfg(test)]
mod tests {
    use super::*;

    // Static fixtures for tests that must reach validation branches
    // without dereferencing real data.
    static DUMMY_F64: f64 = 0.0;
    static DUMMY_I64: i64 = 0;

    #[test]
    fn abi_is_one() {
        assert_eq!(autotopo_native_abi(), 1);
    }

    #[test]
    fn version_string_is_nul_terminated() {
        let ptr = autotopo_native_version();
        assert!(!ptr.is_null());
        let bytes = unsafe { std::ffi::CStr::from_ptr(ptr) }.to_bytes();
        let text = std::str::from_utf8(bytes).expect("ascii version");
        assert_eq!(text, concat!("autotopo_native/", env!("CARGO_PKG_VERSION")));
    }

    #[test]
    fn sharp_features_validation_codes() {
        let null_f64 = std::ptr::null::<f64>();
        let null_i64 = std::ptr::null::<i64>();
        let null_i32 = std::ptr::null_mut::<i32>();
        let null_mut_i64 = std::ptr::null_mut::<i64>();

        // NULL verts -> -1
        assert_eq!(
            sharp_features_impl(
                null_f64,
                4,
                &DUMMY_I64,
                1,
                null_i64,
                0,
                null_i32,
                null_mut_i64,
                null_mut_i64,
            ),
            -1
        );
        // n_verts = 0 -> -2
        assert_eq!(
            sharp_features_impl(
                &DUMMY_F64,
                0,
                &DUMMY_I64,
                1,
                null_i64,
                0,
                null_i32,
                null_mut_i64,
                null_mut_i64,
            ),
            -2
        );
        // n_faces = 0 -> -2
        assert_eq!(
            sharp_features_impl(
                &DUMMY_F64,
                4,
                &DUMMY_I64,
                0,
                null_i64,
                0,
                null_i32,
                null_mut_i64,
                null_mut_i64,
            ),
            -2
        );
        // n_sharp < 0 -> -2
        assert_eq!(
            sharp_features_impl(
                &DUMMY_F64,
                4,
                &DUMMY_I64,
                1,
                null_i64,
                -1,
                null_i32,
                null_mut_i64,
                null_mut_i64,
            ),
            -2
        );
        // n_sharp > 0 with NULL outputs -> -1
        assert_eq!(
            sharp_features_impl(
                &DUMMY_F64,
                4,
                &DUMMY_I64,
                1,
                &DUMMY_I64,
                1,
                null_i32,
                null_mut_i64,
                null_mut_i64,
            ),
            -1
        );
        // n_verts >= 2^32 -> -4
        assert_eq!(
            sharp_features_impl(
                &DUMMY_F64,
                1i64 << 32,
                &DUMMY_I64,
                1,
                null_i64,
                0,
                null_i32,
                null_mut_i64,
                null_mut_i64,
            ),
            -4
        );
    }

    #[test]
    fn max_nearest_distance_validation_codes() {
        let null_f64 = std::ptr::null::<f64>();
        // negative count -> -2.0
        assert_eq!(max_nearest_distance_impl(null_f64, -1, null_f64, 1), -2.0);
        // either side empty -> 0.0 (even with NULL pointers)
        assert_eq!(max_nearest_distance_impl(null_f64, 0, null_f64, 1), 0.0);
        // NULL pointers with positive counts -> -1.0
        assert_eq!(max_nearest_distance_impl(null_f64, 1, null_f64, 1), -1.0);
    }

    #[test]
    fn ffi_guard_contains_panic() {
        // Silence the default panic hook for this intentional panic.
        let previous = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let code = ffi_guard(
            || -> i64 {
                panic!("intentional test panic");
            },
            -5,
        );
        std::panic::set_hook(previous);
        assert_eq!(code, -5);
    }

    // ── sharp_features kernel tests ──

    /// Two triangles forming a planar quad (deterministic fixture).
    fn quad_mesh() -> (Vec<f64>, Vec<i64>) {
        let verts = vec![
            0.0, 0.0, 0.0, // 0
            1.0, 0.0, 0.0, // 1
            1.0, 1.0, 0.0, // 2
            0.0, 1.0, 0.0, // 3
        ];
        let faces = vec![0i64, 1, 2, 0, 2, 3];
        (verts, faces)
    }

    /// Naive O(F) per key reference: independent re-derivation of the
    /// documented behavior (incidence selection + convexity rule).
    /// The normal formula is deliberately duplicated rather than shared
    /// with the kernel, so a typo on either side fails the comparison.
    fn naive_sharp(verts: &[f64], faces: &[i64], keys: &[i64]) -> Vec<(i32, i64, i64)> {
        let nf = faces.len() / 3;
        let mut out = Vec::new();
        for k in 0..keys.len() / 2 {
            let (mut u, mut v) = (keys[k * 2], keys[k * 2 + 1]);
            if u < 0 || v < 0 {
                continue;
            }
            if u > v {
                std::mem::swap(&mut u, &mut v);
            }
            let mut first: Option<(usize, usize)> = None;
            let mut second: Option<(usize, usize)> = None;
            for m in 0..nf {
                for j in 0..3 {
                    let a = faces[m * 3 + j];
                    let b = faces[m * 3 + (j + 1) % 3];
                    let (eu, ev) = if a < b { (a, b) } else { (b, a) };
                    if eu == u && ev == v {
                        if first.is_none() {
                            first = Some((m, j));
                        } else if second.is_none() {
                            second = Some((m, j));
                        }
                    }
                }
            }
            let (fi, j) = match first {
                Some(x) => x,
                None => continue,
            };
            let convexity = match second {
                None => 1,
                Some((fi1, _)) => {
                    let tri = |m: usize| -> (&[f64], &[f64], &[f64]) {
                        (
                            &verts[faces[m * 3] as usize * 3..],
                            &verts[faces[m * 3 + 1] as usize * 3..],
                            &verts[faces[m * 3 + 2] as usize * 3..],
                        )
                    };
                    let (v0, v1, v2) = tri(fi);
                    let e1 = [v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]];
                    let e2 = [v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]];
                    let n = [
                        e1[1] * e2[2] - e1[2] * e2[1],
                        e1[2] * e2[0] - e1[0] * e2[2],
                        e1[0] * e2[1] - e1[1] * e2[0],
                    ];
                    let (c0, c1, c2) = tri(fi1);
                    let cen = [
                        (c0[0] + c1[0] + c2[0]) / 3.0,
                        (c0[1] + c1[1] + c2[1]) / 3.0,
                        (c0[2] + c1[2] + c2[2]) / 3.0,
                    ];
                    let a = faces[fi * 3 + j] as usize;
                    let d = [
                        cen[0] - verts[a * 3],
                        cen[1] - verts[a * 3 + 1],
                        cen[2] - verts[a * 3 + 2],
                    ];
                    let signed_v = n[0] * d[0] + n[1] * d[1] + n[2] * d[2];
                    if signed_v < 0.0 {
                        1
                    } else {
                        0
                    }
                }
            };
            out.push((convexity, fi as i64, j as i64));
        }
        out
    }

    #[test]
    fn sharp_features_matches_naive_reference() {
        let (verts, faces) = quad_mesh();
        // interior edge (0,2); boundary edge (0,1); absent edge (1,3);
        // reversed order (2,0); duplicate (0,2); negative pair (-1,2).
        let keys: Vec<i64> = vec![0, 2, 0, 1, 1, 3, 2, 0, 0, 2, -1, 2];
        let n_keys = keys.len() / 2;
        let mut conv = vec![0i32; n_keys];
        let mut fi = vec![0i64; n_keys];
        let mut pos = vec![0i64; n_keys];
        let n = autotopo_sharp_features(
            verts.as_ptr(),
            verts.len() as i64 / 3,
            faces.as_ptr(),
            faces.len() as i64 / 3,
            keys.as_ptr(),
            keys.len() as i64 / 2,
            conv.as_mut_ptr(),
            fi.as_mut_ptr(),
            pos.as_mut_ptr(),
        );
        assert!(n >= 0, "unexpected error code {n}");
        let got: Vec<(i32, i64, i64)> = (0..n as usize).map(|i| (conv[i], fi[i], pos[i])).collect();
        assert_eq!(got, naive_sharp(&verts, &faces, &keys));
        // Hand-computed expectations for the planar quad:
        // (0,2) interior -> convexity 0 (face 0, position 2);
        // (0,1) boundary -> convexity 1 (face 0, position 0);
        // (2,0) normalizes to (0,2); duplicate (0,2) repeats it.
        assert_eq!(got, vec![(0, 0, 2), (1, 0, 0), (0, 0, 2), (0, 0, 2)]);
    }

    #[test]
    fn sharp_features_handles_degenerate_face() {
        // Second face is zero-area: its normal is clamped, and its
        // self-loop edges must not panic or produce NaN.
        let verts: [f64; 12] = [
            0.0, 0.0, 0.0, // 0
            1.0, 0.0, 0.0, // 1
            1.0, 1.0, 0.0, // 2
            0.5, 0.5, 0.5, // 3
        ];
        let faces: [i64; 6] = [0, 1, 2, 3, 3, 3];
        let keys: [i64; 4] = [0, 1, 3, 3];
        let n_keys = keys.len() / 2;
        let mut conv = vec![0i32; n_keys];
        let mut fi = vec![0i64; n_keys];
        let mut pos = vec![0i64; n_keys];
        let n = autotopo_sharp_features(
            verts.as_ptr(),
            verts.len() as i64 / 3,
            faces.as_ptr(),
            faces.len() as i64 / 3,
            keys.as_ptr(),
            keys.len() as i64 / 2,
            conv.as_mut_ptr(),
            fi.as_mut_ptr(),
            pos.as_mut_ptr(),
        );
        assert!(n >= 0, "unexpected error code {n}");
        let got: Vec<(i32, i64, i64)> = (0..n as usize).map(|i| (conv[i], fi[i], pos[i])).collect();
        // (0,1): single incident face -> boundary -> convex, face 0, j 0.
        // (3,3): the degenerate face's self-loop edge is hit at both
        // j = 0 and j = 1, so it has TWO incident half-edges and the
        // signed-volume branch runs: centroid == vertex -> signed_v
        // == 0 -> concave (0), face 1, j 0.
        assert_eq!(got, vec![(1, 0, 0), (0, 1, 0)]);
    }

    // ── max_nearest_distance kernel tests ──

    /// Naive O(n_query * n_ref) reference: max over query points of the
    /// distance to the nearest reference point.
    fn naive_max_nearest(query: &[f64], ref_: &[f64]) -> f64 {
        let mut max_dist = 0.0f64;
        for i in 0..query.len() / 3 {
            let q = &query[i * 3..i * 3 + 3];
            let mut best2 = f64::MAX;
            for j in 0..ref_.len() / 3 {
                let p = &ref_[j * 3..j * 3 + 3];
                let dx = q[0] - p[0];
                let dy = q[1] - p[1];
                let dz = q[2] - p[2];
                let d2 = dx * dx + dy * dy + dz * dz;
                if d2 < best2 {
                    best2 = d2;
                }
            }
            let d = best2.sqrt();
            if d > max_dist {
                max_dist = d;
            }
        }
        max_dist
    }

    #[test]
    fn max_nearest_matches_naive_reference() {
        // Deterministic pseudo-random clouds (LCG — no rng dependency).
        let mut state: u64 = 0x2545_F491_4F6C_DD1D;
        let mut next = || {
            state = state
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        let (n_query, n_ref) = (200usize, 350usize);
        let query: Vec<f64> = (0..n_query * 3).map(|_| next()).collect();
        let ref_: Vec<f64> = (0..n_ref * 3).map(|_| next()).collect();
        let got = autotopo_max_nearest_distance(
            query.as_ptr(),
            n_query as i64,
            ref_.as_ptr(),
            n_ref as i64,
        );
        assert!(got >= 0.0, "unexpected error code {got}");
        assert_eq!(got, naive_max_nearest(&query, &ref_));
    }

    #[test]
    fn max_nearest_single_reference() {
        let query = [0.1f64, 0.2, 0.3, 0.9, 0.9, 0.9];
        let ref_ = [0.5f64, 0.5, 0.5];
        let d = autotopo_max_nearest_distance(query.as_ptr(), 2, ref_.as_ptr(), 1);
        // Farthest query point: (0.4, 0.4, 0.4) -> sqrt(3 * 0.16).
        assert_eq!(d, (3.0f64 * 0.4 * 0.4).sqrt());
    }

    #[test]
    fn max_nearest_coincident_points() {
        let query = [0.5f64, 0.5, 0.5, 2.0, 2.0, 2.0];
        let ref_ = [0.5f64, 0.5, 0.5];
        let d = autotopo_max_nearest_distance(query.as_ptr(), 2, ref_.as_ptr(), 1);
        // The coincident query point contributes 0; the far one drives
        // the max: (1.5, 1.5, 1.5) -> sqrt(3 * 2.25).
        assert_eq!(d, (3.0f64 * 1.5 * 1.5).sqrt());
    }

    #[test]
    fn max_nearest_empty_sets() {
        let q = [0.0f64; 3];
        let r = [0.0f64; 3];
        assert_eq!(
            autotopo_max_nearest_distance(q.as_ptr(), 0, r.as_ptr(), 1),
            0.0
        );
        assert_eq!(
            autotopo_max_nearest_distance(q.as_ptr(), 1, r.as_ptr(), 0),
            0.0
        );
    }
}
