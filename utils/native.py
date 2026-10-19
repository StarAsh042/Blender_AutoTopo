"""Optional C++ acceleration layer for Blender AutoTopo.

Loads ``bin/autotopo_native.dll`` (built from ``native/autotopo_native.cpp``)
through ctypes and exposes thin, numpy-friendly wrappers for the two
hot paths that are otherwise pure-Python:

* :func:`sharp_features`            — QuadWild ``.sharp`` edge incidence
* :func:`max_nearest_distance`      — silhouette directed Hausdorff distance

Design rules (deliberately defensive — a missing/broken DLL must never
break the addon):

* **Silent degradation.** Every loader failure (file absent, load error,
  missing symbol, ABI mismatch, wrong platform) leaves the module in
  "unavailable" state and the wrappers return ``None``. Callers then
  fall back to the numpy implementation. No exception ever escapes this
  module's public API.
* **Lazy, once.** The DLL is opened on first use and cached; a failed
  attempt is remembered so we do not retry on every call.
* **ABI check.** ``autotopo_native_abi()`` must return the version this
  loader was written against (see ``_EXPECTED_ABI``); anything else is
  treated as incompatible.
* **Argument marshalling.** Arrays are forced to contiguous C-order with
  the exact dtypes the C ABI declares (float64 / int64 / int32) and kept
  alive for the duration of the call.
* **Release.** :func:`release` frees the handle (Windows keeps a file
  lock on a ctypes-loaded DLL until then, which blocks the in-session
  "Remove addon" operator). It resets the cache so a later reload works.
"""

import ctypes
import os
from typing import Optional, Tuple

import numpy as np

from . import integrity
from .logger import logger

# ABI revision implemented by native/autotopo_native.cpp. Bump both
# together whenever the C signatures change.
_EXPECTED_ABI = 1

_LIB_BASENAME = 'autotopo_native'

# Module-level cache. ``_tried`` distinguishes "not yet attempted" from
# "attempted and unavailable".
_loaded = None          # type: Optional[ctypes.CDLL]
_tried = False
_impl_name = 'numpy'


def _bin_dir() -> str:
    """Directory holding the optional native DLL."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'bin',
    )


def _lib_filenames():
    """Candidate DLL file names for the current platform."""
    import platform
    system = platform.system()
    if system == 'Windows':
        return ('autotopo_native.dll',)
    if system == 'Darwin':
        return ('libautotopo_native.dylib',)
    return ('libautotopo_native.so',)


def _configure(lib: ctypes.CDLL) -> None:
    """Bind prototypes. Raises if a required symbol is missing."""
    lib.autotopo_native_abi.argtypes = []
    lib.autotopo_native_abi.restype = ctypes.c_int32

    lib.autotopo_native_version.argtypes = []
    lib.autotopo_native_version.restype = ctypes.c_char_p

    dptr = ctypes.POINTER(ctypes.c_double)
    i64ptr = ctypes.POINTER(ctypes.c_int64)
    i32ptr = ctypes.POINTER(ctypes.c_int32)

    lib.autotopo_sharp_features.argtypes = [
        dptr, ctypes.c_int64,   # verts, n_verts
        i64ptr, ctypes.c_int64,  # faces, n_faces
        i64ptr, ctypes.c_int64,  # sharp_keys, n_sharp
        i32ptr, i64ptr, i64ptr,  # out_convexity, out_face_index, out_edge_pos
    ]
    lib.autotopo_sharp_features.restype = ctypes.c_int64

    lib.autotopo_max_nearest_distance.argtypes = [
        dptr, ctypes.c_int64,   # query, n_query
        dptr, ctypes.c_int64,   # ref, n_ref
    ]
    lib.autotopo_max_nearest_distance.restype = ctypes.c_double

    if int(lib.autotopo_native_abi()) != _EXPECTED_ABI:
        raise RuntimeError('autotopo_native ABI mismatch')


def _load():
    """Load (once) and return the DLL, or None when unavailable."""
    global _loaded, _tried, _impl_name
    if _tried:
        return _loaded
    _tried = True

    bin_dir = _bin_dir()
    for name in _lib_filenames():
        path = os.path.join(bin_dir, name)
        if not os.path.isfile(path):
            continue
        if not integrity.verify_file(path):
            logger.error(
                "内置二进制完整性校验失败，已拒绝加载：%s", name)
            continue
        try:
            lib = ctypes.CDLL(path)
        except Exception:
            continue
        try:
            _configure(lib)
        except Exception:
            continue
        _loaded = lib
        _impl_name = 'cpp'
        break
    return _loaded


def is_available() -> bool:
    """True when the C++ acceleration DLL is loaded and ABI-compatible."""
    return _load() is not None


def get_impl_name() -> str:
    """Active implementation for the two hot paths: 'cpp' or 'numpy'."""
    _load()
    return _impl_name


def get_version() -> str:
    """Human-readable version string of the loaded DLL ('' if absent)."""
    lib = _load()
    if lib is None:
        return ''
    try:
        raw = lib.autotopo_native_version()
        return raw.decode('ascii', 'replace') if raw else ''
    except Exception:
        return ''


def release() -> None:
    """Free the DLL handle so the plugin folder can be removed.

    Windows keeps a ctypes-loaded DLL file-locked until the handle is
    freed; without this, Blender's in-session "Remove" addon operator
    fails with PermissionError. Must not be called while a remesh that
    uses the DLL is running. Safe to call repeatedly.
    """
    global _loaded, _tried, _impl_name
    lib = _loaded
    _loaded = None
    _tried = False
    _impl_name = 'numpy'

    import platform
    if platform.system() != 'Windows' or lib is None:
        return
    handle = getattr(lib, '_handle', None)
    if not handle:
        return
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
        kernel32.FreeLibrary.restype = ctypes.c_int
        kernel32.FreeLibrary(handle)
    except Exception:
        pass


def _as_f64(a: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(a, dtype=np.float64)


def _as_i64(a: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(a, dtype=np.int64)


def sharp_features(
    verts: np.ndarray,
    faces: np.ndarray,
    sharp_keys: np.ndarray,
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """C++ edge-incidence pass for the QuadWild ``.sharp`` export.

    Args:
        verts: (N, 3) vertex positions
        faces: (M, 3) triangle indices
        sharp_keys: (K, 2) sharp edges as (v0, v1) pairs

    Returns:
        ``(convexity int32[L], face_index int64[L], edge_pos int64[L])``
        or ``None`` when the native layer is unavailable / errored.
        L <= K (edges not present in any face are dropped).
    """
    lib = _load()
    if lib is None:
        return None
    try:
        v = _as_f64(verts)
        f = _as_i64(faces)
        k = _as_i64(sharp_keys)
        # ``k`` must be (K, 2): the native side reads exactly 2*K elements
        # starting at sharp_keys[0]. Without this check a 1-D array or a
        # (K, 1) / (K, 3) array makes the element count disagree with the
        # buffer, and the kernel reads past the end of the allocation
        # (CWE-125 out-of-bounds read). Guard all three shapes.
        if (v.ndim != 2 or v.shape[1] != 3
                or f.ndim != 2 or f.shape[1] != 3
                or k.ndim != 2 or k.shape[1] != 2):
            return None
        n_sharp = int(k.shape[0])
        if n_sharp == 0:
            return (np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.int64),
                    np.empty(0, dtype=np.int64))

        out_conv = np.empty(n_sharp, dtype=np.int32)
        out_fi = np.empty(n_sharp, dtype=np.int64)
        out_j = np.empty(n_sharp, dtype=np.int64)

        dptr = ctypes.POINTER(ctypes.c_double)
        i64ptr = ctypes.POINTER(ctypes.c_int64)
        i32ptr = ctypes.POINTER(ctypes.c_int32)

        res = lib.autotopo_sharp_features(
            v.ctypes.data_as(dptr), ctypes.c_int64(v.shape[0]),
            f.ctypes.data_as(i64ptr), ctypes.c_int64(f.shape[0]),
            k.ctypes.data_as(i64ptr), ctypes.c_int64(n_sharp),
            out_conv.ctypes.data_as(i32ptr),
            out_fi.ctypes.data_as(i64ptr),
            out_j.ctypes.data_as(i64ptr),
        )
        if res < 0:
            return None
        n = int(res)
        return out_conv[:n], out_fi[:n], out_j[:n]
    except Exception:
        return None


def max_nearest_distance(
    query: np.ndarray,
    ref: np.ndarray,
) -> Optional[float]:
    """C++ max over ``query`` points of the distance to the nearest ``ref``.

    Args:
        query: (Q, 3) query points (e.g. source silhouette samples)
        ref: (R, 3) reference points (e.g. output vertices)

    Returns:
        The maximum nearest-neighbour distance as a float, or ``None``
        when the native layer is unavailable / errored.
    """
    lib = _load()
    if lib is None:
        return None
    try:
        q = _as_f64(query)
        r = _as_f64(ref)
        if q.ndim != 2 or q.shape[1] != 3 or r.ndim != 2 or r.shape[1] != 3:
            return None
        n_q = int(q.shape[0])
        n_r = int(r.shape[0])
        if n_q == 0 or n_r == 0:
            return 0.0
        dptr = ctypes.POINTER(ctypes.c_double)
        res = float(lib.autotopo_max_nearest_distance(
            q.ctypes.data_as(dptr), ctypes.c_int64(n_q),
            r.ctypes.data_as(dptr), ctypes.c_int64(n_r),
        ))
        if res < 0.0:
            return None
        return res
    except Exception:
        return None
