"""Golden-master test: bit-exact behavior lock for autotopo_native.

The golden arrays were generated from the C++ DLL shipped with v1.0.0
(``native/autotopo_native.cpp``, MinGW build) *before* the Rust port.
Any native implementation — C++, Rust, or a future one — must reproduce
them exactly. This is a 特征测试 (behavior lock): it records current
behavior, including edge cases; it does not judge whether that behavior
is "correct".

The DLL under test is bound directly through ctypes (mirroring the ABI
contract in ``utils/native.py`` — keep the two in sync), so the test can
target any DLL path, not just ``bin/``:

    AUTOTOPO_NATIVE_DLL=<path-to-dll> python -m pytest -q test/test_native_golden.py

Regenerate the golden data from a trusted DLL (requires explicit intent):

    python test/test_native_golden.py --regen [--dll <path>]

Covered contract surface (grows with each ported kernel):
* ``autotopo_native_abi`` == 1
* ``autotopo_native_version`` non-empty
* ``autotopo_sharp_features``: interior/boundary edges, edges absent from
  the mesh (dropped), reversed key order, duplicate keys, negative
  indices (skipped), degenerate (zero-area) faces, n_sharp == 0 with
  NULL pointers, and the documented error codes (-2 / -3 / -4)
* ``autotopo_max_nearest_distance``: random clouds, single reference
  point, duplicate/coincident points, and the documented error code (-2)
"""

import os
import sys

import numpy as np
import pytest

# 项目根本身是插件包（含 import bpy 的 __init__.py），pytest 会把它收集为
# <Package Blender_AutoTopo> 并在 setup 时导入。按仓库约定（见
# test/test_package_artifact.py），先用 _pkgload 把包桩进 sys.modules，
# 使该导入成为空操作——否则纯 Python 环境下会因缺 bpy 而 CollectError。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pkgload  # noqa: E402
_pkgload._ensure_packages()

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_GOLDEN = os.path.join(_HERE, "golden", "native_golden.npz")

# Deterministic fixture seed — changing it invalidates the golden data.
SEED = 20261020


# ── fixtures (deterministic) ──────────────────────────────────────────

def _grid_mesh(n_side=12):
    """Triangulated height-field grid plus one degenerate face.

    Returns (verts (V,3) float64, faces (F,3) int64).
    """
    rng = np.random.default_rng(SEED)
    xs = np.linspace(0.0, 1.0, n_side + 1)
    ys = np.linspace(0.0, 1.0, n_side + 1)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    h = rng.uniform(-0.05, 0.05, size=gx.size)
    verts = np.stack([gx.ravel(), gy.ravel(), h], axis=1)

    faces = []
    for i in range(n_side):
        for j in range(n_side):
            a = i * (n_side + 1) + j
            b = (i + 1) * (n_side + 1) + j
            c = (i + 1) * (n_side + 1) + (j + 1)
            d = i * (n_side + 1) + (j + 1)
            faces.append((a, b, c))
            faces.append((a, c, d))
    faces.append((0, 0, 0))  # degenerate zero-area face
    return np.ascontiguousarray(verts, dtype=np.float64), \
        np.ascontiguousarray(np.asarray(faces, dtype=np.int64))


def _sharp_keys(verts, faces):
    """Sharp-edge key set exercising every documented branch."""
    keys = []
    # interior edges (two incident faces) — first cell's diagonal
    keys.append((0, n_side_plus1()))
    # boundary edges of the grid
    keys.append((0, 1))
    # an edge that does not exist in any face -> dropped
    keys.append((0, int(verts.shape[0]) - 1))
    # reversed order (v0 > v1) -> normalized
    keys.append((n_side_plus1(), 0))
    # duplicate of the first key -> emitted twice
    keys.append((0, n_side_plus1()))
    # negative indices -> skipped, not an error
    keys.append((-1, 5))
    keys.append((7, -3))
    # an edge of the degenerate face
    keys.append((1, 2))
    return np.ascontiguousarray(np.asarray(keys, dtype=np.int64).reshape(-1, 2))


def n_side_plus1():
    return 13  # n_side + 1 for the default grid


def _clouds():
    rng = np.random.default_rng(SEED + 1)
    query = rng.uniform(-0.2, 1.2, size=(400, 3))
    ref = rng.uniform(0.0, 1.0, size=(600, 3))
    # coincident points -> zero distances present
    ref[100:200] = query[100:200]
    single_ref = np.array([[0.5, 0.5, 0.5]])
    query2 = rng.uniform(0.0, 1.0, size=(50, 3))
    return (np.ascontiguousarray(query, dtype=np.float64),
            np.ascontiguousarray(ref, dtype=np.float64),
            np.ascontiguousarray(single_ref, dtype=np.float64),
            np.ascontiguousarray(query2, dtype=np.float64))


# ── raw ctypes binding (mirrors utils/native.py _configure) ───────────

def _bind(dll_path):
    import ctypes
    lib = ctypes.CDLL(dll_path)
    lib.autotopo_native_abi.argtypes = []
    lib.autotopo_native_abi.restype = ctypes.c_int32
    lib.autotopo_native_version.argtypes = []
    lib.autotopo_native_version.restype = ctypes.c_char_p

    dptr = ctypes.POINTER(ctypes.c_double)
    i64ptr = ctypes.POINTER(ctypes.c_int64)
    i32ptr = ctypes.POINTER(ctypes.c_int32)

    lib.autotopo_sharp_features.argtypes = [
        dptr, ctypes.c_int64,
        i64ptr, ctypes.c_int64,
        i64ptr, ctypes.c_int64,
        i32ptr, i64ptr, i64ptr,
    ]
    lib.autotopo_sharp_features.restype = ctypes.c_int64

    lib.autotopo_max_nearest_distance.argtypes = [
        dptr, ctypes.c_int64,
        dptr, ctypes.c_int64,
    ]
    lib.autotopo_max_nearest_distance.restype = ctypes.c_double
    return lib, ctypes


def _call_sharp(lib, ct, verts, faces, keys, n_sharp=None):
    if n_sharp is None:
        n_sharp = keys.shape[0]
    out_conv = np.empty(max(n_sharp, 1), dtype=np.int32)
    out_fi = np.empty(max(n_sharp, 1), dtype=np.int64)
    out_pos = np.empty(max(n_sharp, 1), dtype=np.int64)
    res = lib.autotopo_sharp_features(
        verts.ctypes.data_as(ct.POINTER(ct.c_double)), ct.c_int64(verts.shape[0]),
        faces.ctypes.data_as(ct.POINTER(ct.c_int64)), ct.c_int64(faces.shape[0]),
        keys.ctypes.data_as(ct.POINTER(ct.c_int64)) if n_sharp else None,
        ct.c_int64(n_sharp),
        out_conv.ctypes.data_as(ct.POINTER(ct.c_int32)),
        out_fi.ctypes.data_as(ct.POINTER(ct.c_int64)),
        out_pos.ctypes.data_as(ct.POINTER(ct.c_int64)),
    )
    return res, out_conv, out_fi, out_pos


def _dll_path():
    return os.environ.get(
        "AUTOTOPO_NATIVE_DLL",
        os.path.join(_PROJECT_ROOT, "bin", "autotopo_native.dll"),
    )


def _dll_loadable():
    """True when the DLL under test can actually be loaded here.

    The shipped library is Windows-only; on other platforms the
    committed DLL fails with "invalid ELF header". Mirrors the
    graceful-degradation philosophy of ``utils/native.py``: the suite
    stays green, and the golden comparison runs where the native
    library exists (Windows CI runners, developer machines).
    """
    if not os.path.isfile(_dll_path()):
        return False
    try:
        import ctypes
        ctypes.CDLL(_dll_path())
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _dll_loadable(),
    reason="当前平台无可加载的原生库（发行版仅提供 Windows autotopo_native.dll）",
)


# ── golden generation / comparison ────────────────────────────────────

def _generate():
    lib, ct = _bind(_dll_path())
    verts, faces = _grid_mesh()
    keys = _sharp_keys(verts, faces)
    query, ref, single_ref, query2 = _clouds()

    res, conv, fi, pos = _call_sharp(lib, ct, verts, faces, keys)
    assert res >= 0, f"sharp_features failed: {res}"
    n = int(res)

    d = lib.autotopo_max_nearest_distance(
        query.ctypes.data_as(ct.POINTER(ct.c_double)), ct.c_int64(query.shape[0]),
        ref.ctypes.data_as(ct.POINTER(ct.c_double)), ct.c_int64(ref.shape[0]))
    d2 = lib.autotopo_max_nearest_distance(
        query2.ctypes.data_as(ct.POINTER(ct.c_double)), ct.c_int64(query2.shape[0]),
        single_ref.ctypes.data_as(ct.POINTER(ct.c_double)), ct.c_int64(single_ref.shape[0]))

    data = {
        "s_verts": verts, "s_faces": faces, "s_keys": keys,
        "s_conv": conv[:n].copy(), "s_fi": fi[:n].copy(), "s_pos": pos[:n].copy(),
        "h_query": query, "h_ref": ref, "h_dist": np.float64(d),
        "h_query2": query2, "h_ref2": single_ref, "h_dist2": np.float64(d2),
        "abi": np.int32(lib.autotopo_native_abi()),
        "version": np.bytes_(lib.autotopo_native_version() or b""),
    }
    os.makedirs(os.path.dirname(_GOLDEN), exist_ok=True)
    np.savez(_GOLDEN, **data)
    print(f"golden written: {_GOLDEN} ({n} sharp lines, "
          f"dist={d!r}, dist2={d2!r}, version={data['version']!r})")


def _load_golden():
    if not os.path.isfile(_GOLDEN):
        pytest.fail(f"golden data missing: {_GOLDEN}（见文件头 --regen 说明）")
    with np.load(_GOLDEN, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def test_abi_and_version():
    lib, ct = _bind(_dll_path())
    assert int(lib.autotopo_native_abi()) == 1
    assert lib.autotopo_native_version()


def test_sharp_features_bit_exact():
    lib, ct = _bind(_dll_path())
    g = _load_golden()
    res, conv, fi, pos = _call_sharp(
        lib, ct, g["s_verts"], g["s_faces"], g["s_keys"])
    assert res >= 0, f"sharp_features failed: {res}"
    n = int(res)
    assert n == g["s_conv"].shape[0], f"line count {n} != {g['s_conv'].shape[0]}"
    assert np.array_equal(conv[:n], g["s_conv"]), "convexity mismatch"
    assert np.array_equal(fi[:n], g["s_fi"]), "face_index mismatch"
    assert np.array_equal(pos[:n], g["s_pos"]), "edge_pos mismatch"


def test_max_nearest_distance_bit_exact():
    lib, ct = _bind(_dll_path())
    g = _load_golden()
    d = lib.autotopo_max_nearest_distance(
        g["h_query"].ctypes.data_as(ct.POINTER(ct.c_double)),
        ct.c_int64(g["h_query"].shape[0]),
        g["h_ref"].ctypes.data_as(ct.POINTER(ct.c_double)),
        ct.c_int64(g["h_ref"].shape[0]))
    assert float(d) == float(g["h_dist"]), f"{d!r} != {float(g['h_dist'])!r}"

    d2 = lib.autotopo_max_nearest_distance(
        g["h_query2"].ctypes.data_as(ct.POINTER(ct.c_double)),
        ct.c_int64(g["h_query2"].shape[0]),
        g["h_ref2"].ctypes.data_as(ct.POINTER(ct.c_double)),
        ct.c_int64(g["h_ref2"].shape[0]))
    assert float(d2) == float(g["h_dist2"]), f"{d2!r} != {float(g['h_dist2'])!r}"


def test_error_codes():
    lib, ct = _bind(_dll_path())
    verts, faces = _grid_mesh()

    # n_verts = 0 -> -2
    res, _, _, _ = _call_sharp(
        lib, ct, verts[:0], faces[:1], np.zeros((1, 2), dtype=np.int64))
    assert res == -2, res
    # n_faces = 0 -> -2
    res, _, _, _ = _call_sharp(
        lib, ct, verts, faces[:0], np.zeros((1, 2), dtype=np.int64))
    assert res == -2, res
    # face index out of range -> -3
    bad = faces.copy()
    bad[0, 0] = verts.shape[0]
    res, _, _, _ = _call_sharp(lib, ct, verts, bad, np.zeros((1, 2), dtype=np.int64))
    assert res == -3, res
    # n_sharp = 0 with NULL pointers -> 0 (documented no-op)
    res, _, _, _ = _call_sharp(
        lib, ct, verts, faces, np.zeros((0, 2), dtype=np.int64), n_sharp=0)
    assert res == 0, res

    # negative counts -> -2.0
    d = lib.autotopo_max_nearest_distance(None, ct.c_int64(-1), None, ct.c_int64(1))
    assert d == -2.0, d


if __name__ == "__main__":
    if "--regen" in sys.argv:
        args = sys.argv[1:]
        dll = args[args.index("--dll") + 1] if "--dll" in args else None
        if dll:
            os.environ["AUTOTOPO_NATIVE_DLL"] = dll
        _generate()
    else:
        sys.exit(pytest.main([__file__, "-q"]))
