"""Native boundary guards for ``utils/native.py``.

Two properties are asserted here:

1. **Malformed input never reaches the native kernel.** The C side reads
   exactly ``2*K`` elements from the ``sharp_keys`` buffer, so a 1-D or
   ``(K,1)``/``(K,3)`` array would make the element count disagree with the
   allocation and produce an out-of-bounds read (CWE-125). Every such shape
   must be rejected in Python and yield ``None``.
2. **Silent degradation.** When the DLL is absent every wrapper returns
   ``None`` instead of raising, so callers fall back to numpy.

Pure ctypes + numpy — no ``bpy`` required, so this runs under plain pytest.
"""
import numpy as np
import pytest

import _pkgload

native = _pkgload.load_module("utils/native.py")


def _mesh():
    verts = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    faces = np.array([[0, 1, 2], [0, 1, 3]], dtype=np.int64)
    return verts, faces


@pytest.mark.parametrize(
    "bad",
    [
        np.array([0, 1, 0, 2], dtype=np.int64),              # 1-D
        np.array([[0], [1]], dtype=np.int64),                # (K, 1)
        np.array([[0, 1, 9], [0, 2, 9]], dtype=np.int64),    # (K, 3)
    ],
    ids=["1d", "k1", "k3"],
)
def test_sharp_features_rejects_malformed_sharp_keys(bad):
    """Non-(K,2) sharp_keys must be rejected before the native call."""
    verts, faces = _mesh()
    assert native.sharp_features(verts, faces, bad) is None


def test_sharp_features_rejects_malformed_mesh_shapes():
    verts, faces = _mesh()
    good = np.array([[0, 1]], dtype=np.int64)
    assert native.sharp_features(verts, faces.ravel(), good) is None
    assert native.sharp_features(verts[:, :2], faces, good) is None


def test_sharp_features_well_formed_returns_rows():
    verts, faces = _mesh()
    good = np.array([[0, 1], [0, 2]], dtype=np.int64)
    res = native.sharp_features(verts, faces, good)
    if not native.is_available():
        assert res is None
        pytest.skip("native DLL unavailable — numpy fallback path")
    assert res is not None and len(res[0]) == 2


def test_max_nearest_distance_contract():
    rng = np.random.default_rng(0)
    q = rng.random((50, 3))
    r = rng.random((200, 3))
    d = native.max_nearest_distance(q, r)
    if native.is_available():
        assert d is not None and d >= 0.0
    else:
        assert d is None


def test_max_nearest_distance_rejects_bad_shapes():
    rng = np.random.default_rng(0)
    assert native.max_nearest_distance(
        rng.random((50, 2)), rng.random((10, 3))) is None
    assert native.max_nearest_distance(
        rng.random((50, 3)), rng.random((10, 2))) is None


def test_impl_name_is_known():
    assert native.get_impl_name() in ("cpp", "numpy")
