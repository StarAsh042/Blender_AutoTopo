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
    // Skeleton: the kernel lands in the next commit. Any negative code
    // means "unavailable" to callers, which fall back to numpy.
    -5
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
    // Skeleton: the kernel lands in a follow-up commit.
    -3.0
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
}
