"""QuadWild engine — high-quality quad remeshing via precompiled DLLs.

Integrates the QuadWild algorithm (SIGGRAPH Asia 2019) through the
precompiled native libraries shipped with the QRemeshify release
(lib_quadwild.dll / lib_quadpatches.dll), called via ctypes.

The engine runs on a background worker thread (ctypes calls release
the GIL, keeping Blender's UI responsive). Mesh data is exchanged
through temporary OBJ files.

Pipeline stages (mirroring QuadWild's own flow):
1. Export input mesh + sharp features to OBJ / .sharp files
2. remeshAndField — isotropic remesh + cross field computation
3. trace — field line tracing (produces a quad-dominant base mesh)
4. quadrangulate — ILP-based final quadrangulation (QuadPatches)

Target face count is reached with an adaptive scale factor:
quadrangulate runs with scaleFact=1 first; if the result deviates
from the target, only the quadrangulation stage is re-run with
scaleFact *= sqrt(actual / target) (stages 2-3 are cached on disk).

When ``adaptive_density`` is enabled the QuadWild stage produces a
coarse uniform base (~25% of the budget) which is then refined by
error-driven adaptive quad subdivision (see adaptive_subdivision.py),
concentrating faces in damaged / high-detail regions.
"""

import os
import math
import shutil
import tempfile
import time
from ctypes import (
    Structure, POINTER, byref, cdll,
    c_bool, c_int, c_float, c_double, c_char_p,
)
from typing import Optional, Callable, Tuple

import numpy as np

from ..utils import integrity
from ..utils.logger import logger
from ..utils.mesh_io import MeshData, obj_to_mesh_data
from ..utils.math_utils import (
    compute_dihedral_angles,
    compute_face_normals,
    compute_vertex_normals,
)
from .evaluation import RetopoResult, compute_silhouette_error
from .adaptive_subdivision import adaptive_subdivide
from .obj_io import write_obj, read_obj
from .base import RemeshEngine, SettingSpec, register_engine


# ── ctypes structure definitions (match QuadWild native headers) ──

class Parameters(Structure):
    _fields_ = [
        ('remesh', c_bool),
        ('sharpAngle', c_float),
        ('alpha', c_float),       # Unused by remeshAndField2
        ('scaleFact', c_float),   # Unused by remeshAndField2
        ('hasFeature', c_bool),
        ('hasField', c_bool),
    ]


class QRParameters(Structure):
    _fields_ = [
        ("useFlowSolver", c_bool),
        ("flow_config_filename", c_char_p),
        ("satsuma_config_filename", c_char_p),
        ("initialRemeshing", c_bool),
        ("initialRemeshingEdgeFactor", c_double),
        ("reproject", c_bool),
        ("splitConcaves", c_bool),
        ("finalSmoothing", c_bool),

        ("ilpMethod", c_int),
        ("alpha", c_double),
        ("isometry", c_bool),
        ("regularityQuadrilaterals", c_bool),
        ("regularityNonQuadrilaterals", c_bool),
        ("regularityNonQuadrilateralsWeight", c_double),
        ("alignSingularities", c_bool),
        ("alignSingularitiesWeight", c_double),
        ("repeatLosingConstraintsIterations", c_bool),
        ("repeatLosingConstraintsQuads", c_bool),
        ("repeatLosingConstraintsNonQuads", c_bool),
        ("repeatLosingConstraintsAlign", c_bool),
        ("feasibilityFix", c_bool),
        ("hardParityConstraint", c_bool),

        ("timeLimit", c_double),
        ("gapLimit", c_double),
        ("minimumGap", c_double),
        ("callbackTimeLimit", POINTER(c_float)),
        ("callbackGapLimit", POINTER(c_float)),

        ("chartSmoothingIterations", c_int),
        ("quadrangulationFixedSmoothingIterations", c_int),
        ("quadrangulationNonFixedSmoothingIterations", c_int),
        ("doubletRemoval", c_bool),

        ("resultSmoothingIterations", c_int),
        ("resultSmoothingNRing", c_double),
        ("resultSmoothingLaplacianIterations", c_int),
        ("resultSmoothingLaplacianNRing", c_double),
    ]


def _bin_dir() -> str:
    """Directory containing the QuadWild native libraries."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'bin', 'quadwild',
    )


def _lib_filenames():
    import platform
    system = platform.system()
    if system == "Windows":
        return 'lib_quadwild.dll', 'lib_quadpatches.dll'
    elif system == "Darwin":
        return 'lib_quadwild.dylib', 'lib_quadpatches.dylib'
    return 'lib_quadwild.so', 'lib_quadpatches.so'


def is_quadwild_available() -> bool:
    """Check whether the QuadWild native libraries are present."""
    qw_name, qp_name = _lib_filenames()
    bin_dir = _bin_dir()
    return (
        os.path.isfile(os.path.join(bin_dir, qw_name))
        and os.path.isfile(os.path.join(bin_dir, qp_name))
    )


# path -> CDLL; loaded lazily once per process, freed by
# release_native_libs() when the addon is removed.
_loaded_libs = {}


def _load_native_lib(path: str):
    """Load a native library once and register its handle.

    Verifies the bundled binary's SHA-256 (see :mod:`utils.integrity`)
    before loading; a mismatch raises ``RuntimeError`` so the caller
    surfaces a Chinese error instead of executing tampered code.
    """
    key = os.path.normcase(os.path.abspath(path))
    lib = _loaded_libs.get(key)
    if lib is None:
        if not integrity.verify_file(path):
            raise RuntimeError(
                "内置二进制完整性校验失败，已拒绝加载："
                f"{os.path.basename(path)}"
            )
        lib = cdll.LoadLibrary(path)
        _loaded_libs[key] = lib
    return lib


def release_native_libs() -> None:
    """Unload the QuadWild DLLs so the plugin folder can be deleted.

    On Windows a DLL loaded via ctypes keeps its file locked until the
    process exits, which makes Blender's in-session "Remove" addon
    operator fail with PermissionError. Freeing every handle recorded
    in ``_loaded_libs`` lifts the lock. Must not be called while a
    remesh is running.
    """
    import platform
    if platform.system() != "Windows":
        return  # no file locking on POSIX; dlclose risks dangling refs
    import ctypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
    kernel32.FreeLibrary.restype = ctypes.c_int

    for path, lib in list(_loaded_libs.items()):
        _loaded_libs.pop(path, None)
        handle = getattr(lib, '_handle', None)
        if handle:
            try:
                kernel32.FreeLibrary(handle)
            except Exception:
                pass

    # Belt and braces: release any extra reference loaded elsewhere
    # (e.g. a previous plugin version in the same session).
    qw_name, qp_name = _lib_filenames()
    for path in (os.path.join(_bin_dir(), qw_name),
                 os.path.join(_bin_dir(), qp_name)):
        try:
            while True:
                mod = kernel32.GetModuleHandleW(path)
                if not mod or not kernel32.FreeLibrary(mod):
                    break
        except Exception:
            pass


# Setting key -> QRParameters field name. Only these are user-tunable;
# everything else keeps its recommended value.
_TUNABLE_FIELDS = {
    "qw_ilp_method": "ilpMethod",
    "qw_time_limit": "timeLimit",
    "qw_alpha": "alpha",
    "qw_minimum_gap": "minimumGap",
    "qw_gap_limit": "gapLimit",
    "qw_isometry": "isometry",
    "qw_hard_parity": "hardParityConstraint",
    "qw_use_flow_solver": "useFlowSolver",
    "qw_align_sing_weight": "alignSingularitiesWeight",
    "qw_regularity_weight": "regularityNonQuadrilateralsWeight",
    "qw_result_smooth_iters": "resultSmoothingIterations",
    "qw_result_smooth_laplacian": "resultSmoothingLaplacianIterations",
    "qw_chart_smooth_iters": "chartSmoothingIterations",
    "qw_quad_smooth_fixed": "quadrangulationFixedSmoothingIterations",
    "qw_quad_smooth_nonfixed": "quadrangulationNonFixedSmoothingIterations",
    "qw_split_concaves": "splitConcaves",
    "qw_final_smoothing": "finalSmoothing",
    "qw_doublet_removal": "doubletRemoval",
    "qw_feasibility_fix": "feasibilityFix",
}


def _create_default_qr_params(
    overrides: Optional[dict] = None,
) -> QRParameters:
    """Build QRParameters with the recommended defaults.

    The baseline values are those shipped by QRemeshify, which bundles the
    QuadWild + QuadPatches reference implementations. ``overrides`` maps a
    setting key (see :data:`_TUNABLE_FIELDS`) to a value and is applied on
    top, so the UI can expose individual knobs without changing the
    recommended baseline.
    """
    callback_time_limit = [3.0, 5.0, 10.0, 20.0, 30.0, 60.0, 90.0, 120.0]
    callback_gap_limit = [0.005, 0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.3]

    params = QRParameters()

    params.initialRemeshing = True
    params.initialRemeshingEdgeFactor = 1
    params.reproject = True
    params.splitConcaves = False
    params.finalSmoothing = True
    params.doubletRemoval = True
    params.resultSmoothingIterations = 5
    params.resultSmoothingNRing = 3
    params.resultSmoothingLaplacianIterations = 2
    params.resultSmoothingLaplacianNRing = 3

    params.alpha = 0.005
    params.ilpMethod = 1  # LEASTSQUARES
    params.timeLimit = 60
    params.gapLimit = 0.0
    params.minimumGap = 0.4
    params.isometry = True
    params.regularityQuadrilaterals = True
    params.regularityNonQuadrilaterals = True
    params.regularityNonQuadrilateralsWeight = 0.9
    params.alignSingularities = True
    params.alignSingularitiesWeight = 0.1
    params.repeatLosingConstraintsIterations = True
    params.repeatLosingConstraintsQuads = False
    params.repeatLosingConstraintsNonQuads = False
    params.repeatLosingConstraintsAlign = True
    params.hardParityConstraint = True
    params.useFlowSolver = True

    params.chartSmoothingIterations = 0
    params.quadrangulationFixedSmoothingIterations = 0
    params.quadrangulationNonFixedSmoothingIterations = 0
    params.feasibilityFix = False

    # Apply user overrides for the exposed knobs only.
    if overrides:
        for key, field in _TUNABLE_FIELDS.items():
            if key not in overrides:
                continue
            value = overrides[key]
            if value is None:
                continue
            try:
                setattr(params, field, value)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(
                    "QuadWild: cannot set %s (%s): %s", field, key, e)

    # Keep array references alive with the struct
    params._cb_time = (c_float * len(callback_time_limit))(*callback_time_limit)
    params._cb_gap = (c_float * len(callback_gap_limit))(*callback_gap_limit)
    params.callbackTimeLimit = params._cb_time
    params.callbackGapLimit = params._cb_gap

    return params


class QuadwildLib:
    """Thin ctypes wrapper around the QuadWild native libraries."""

    def __init__(self, mesh_path: str):
        self._bin_dir = _bin_dir()
        qw_name, qp_name = _lib_filenames()
        qw_path = os.path.join(self._bin_dir, qw_name)
        qp_path = os.path.join(self._bin_dir, qp_name)
        if not (os.path.isfile(qw_path) and os.path.isfile(qp_path)):
            raise FileNotFoundError(
                f"QuadWild 库缺失: {qw_path} / {qp_path}\n"
                "请将 lib_quadwild.dll 与 lib_quadpatches.dll "
                "放入插件的 bin/quadwild 目录"
                "（当前发行版仅含 Windows 二进制）"
            )

        ok, failed = integrity.verify_tree(self._bin_dir)
        if not ok:
            raise RuntimeError(
                "内置二进制完整性校验失败，已拒绝加载："
                f"{os.path.basename(failed)}"
            )

        self._quadwild = _load_native_lib(qw_path)
        self._quadpatches = _load_native_lib(qp_path)

        self._quadwild.remeshAndField2.argtypes = [
            POINTER(Parameters), c_char_p, c_char_p, c_char_p,
        ]
        self._quadwild.remeshAndField2.restype = None
        self._quadwild.trace2.argtypes = [c_char_p]
        self._quadwild.trace2.restype = c_bool
        self._quadpatches.quadPatches.argtypes = [
            c_char_p, POINTER(QRParameters), c_float, c_int, c_bool,
        ]
        self._quadpatches.quadPatches.restype = c_int

        self.mesh_path = mesh_path
        base, _ = os.path.splitext(mesh_path)
        self.sharp_path = f'{base}_rem.sharp'
        self.field_path = f'{base}_rem.rosy'
        self.remeshed_path = f'{base}_rem.obj'
        self.traced_path = f'{base}_rem_p0.obj'
        self.output_path = f'{base}_rem_p0_0_quadrangulation.obj'
        self.output_smoothed_path = (
            f'{base}_rem_p0_0_quadrangulation_smooth.obj'
        )

    def remesh_and_field(self, enable_sharp: bool, sharp_angle: float):
        params = Parameters(
            remesh=True,
            sharpAngle=sharp_angle if enable_sharp else -1,
            alpha=0.01,
            scaleFact=1,
            hasFeature=enable_sharp,
            hasField=False,
        )
        self._quadwild.remeshAndField2(
            byref(params),
            self.mesh_path.encode('utf-8'),
            self.sharp_path.encode('utf-8'),
            self.field_path.encode('utf-8'),
        )

    def trace(self) -> bool:
        base, _ = os.path.splitext(self.remeshed_path)
        return self._quadwild.trace2(base.encode('utf-8'))

    def quadrangulate(
        self, scale_fact: float, qr_overrides: Optional[dict] = None
    ) -> int:
        params = _create_default_qr_params(qr_overrides)
        params.flow_config_filename = os.path.join(
            self._bin_dir, 'config', 'main_config',
            'flow_virtual_simple.json',
        ).encode('utf-8')
        params.satsuma_config_filename = os.path.join(
            self._bin_dir, 'config', 'satsuma', 'default.json',
        ).encode('utf-8')

        return self._quadpatches.quadPatches(
            self.traced_path.encode('utf-8'),
            byref(params),
            c_float(scale_fact),
            0,      # fixedChartClusters (0 = automatic)
            True,   # enableSmoothing
        )


# ── Sharp feature export ──

def _write_sharp_file(sharp_filepath: str, lines) -> int:
    """Write the .sharp file (feature count + one line per feature)."""
    if not lines:
        with open(sharp_filepath, 'w') as f:
            f.write("0\n")
        return 0
    with open(sharp_filepath, 'w') as f:
        f.write(f"{len(lines)}\n")
        f.write("\n".join(lines))
        f.write("\n")
    return len(lines)


def _sharp_features_numpy(
    verts: np.ndarray,
    faces: np.ndarray,
    sharp_arr: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized edge-incidence pass (numpy fallback for the C++ path).

    Replaces the per-face Python loop that built ``edge_faces`` (1.8M
    iterations at 600k faces, ~8.3s). All half-edges are sorted once
    with a stable ``argsort`` so that, for a given edge, the first two
    occurrences are its two lowest ``(face, j)`` half-edges — exactly
    the order the old dict produced, which keeps the convexity sign
    identical.

    Returns ``(convexity int32[L], face_index int64[L], edge_pos int64[L])``
    for the sharp edges that actually occur in a face (L <= len(sharp_arr)).
    """
    n_verts = int(verts.shape[0])
    n_faces = int(faces.shape[0])
    if n_faces == 0 or sharp_arr.shape[0] == 0:
        empty = np.empty(0, dtype=np.int64)
        return np.empty(0, dtype=np.int32), empty, empty

    # All 3M half-edges in (face-major, j-minor) order, so the stable
    # sort below preserves the historical insertion order per edge.
    nxt = np.roll(faces, -1, axis=1)
    u = np.minimum(faces, nxt).reshape(-1)
    v = np.maximum(faces, nxt).reshape(-1)
    fi_flat = np.repeat(np.arange(n_faces, dtype=np.int64), 3)
    j_flat = np.tile(np.arange(3, dtype=np.int64), n_faces)

    he_key = u * np.int64(n_verts) + v
    order = np.argsort(he_key, kind='stable')
    key_sorted = he_key[order]

    skey = sharp_arr[:, 0] * np.int64(n_verts) + sharp_arr[:, 1]
    lo = np.searchsorted(key_sorted, skey, side='left')
    hi = np.searchsorted(key_sorted, skey, side='right')
    cnt = hi - lo
    found = cnt > 0
    if not np.any(found):
        empty = np.empty(0, dtype=np.int64)
        return np.empty(0, dtype=np.int32), empty, empty

    last = key_sorted.shape[0] - 1
    first = order[np.clip(lo, 0, last)]
    second = order[np.clip(lo + 1, 0, last)]
    has_second = cnt >= 2

    fi0 = fi_flat[first][found]
    j0 = j_flat[first][found]
    fi1 = fi_flat[second][found]
    has_second = has_second[found]

    # Convexity: the neighbouring face centroid lies below this face's
    # plane for a convex edge; boundary edges are treated as convex.
    face_normals = compute_face_normals(verts, faces)
    centroids = verts[faces].mean(axis=1)
    a_vert = faces[fi0, j0]
    signed = np.einsum(
        'ij,ij->i', face_normals[fi0], centroids[fi1] - verts[a_vert]
    )
    convexity = np.where(has_second, (signed < 0).astype(np.int32), 1)
    return (
        convexity.astype(np.int32),
        fi0.astype(np.int64),
        j0.astype(np.int64),
    )


def _export_sharp_features(
    mesh_data: MeshData,
    sharp_angle: float,
    sharp_filepath: str,
) -> int:
    """Write the .sharp feature file expected by QuadWild.

    Format: first line = feature count, then one line per feature:
    ``convexity,face_index,edge_index_in_face``.

    Uses edges marked sharp in Blender if any; otherwise detects
    feature edges automatically from the dihedral angle threshold.

    The edge-incidence map is built by the optional C++ layer when it
    is available, otherwise by a vectorized numpy pass; both replace
    the former per-face Python loop (8.3s at 600k faces).
    """
    verts = np.asarray(mesh_data.vertices, dtype=np.float64)
    faces = np.asarray(mesh_data.faces, dtype=np.int64)
    if faces.ndim != 2 or faces.shape[1] != 3:
        # Non-triangulated input (QuadWild input is always triangles).
        return _write_sharp_file(sharp_filepath, None)

    # Determine which edges are features
    sharp_edges = set(mesh_data.sharp_edges) if mesh_data.sharp_edges else set()
    if not sharp_edges:
        edge_keys, angles = compute_dihedral_angles(verts, faces)
        threshold = math.radians(sharp_angle)
        for key, ang in zip(edge_keys, angles):
            if ang > threshold:
                sharp_edges.add((int(key[0]), int(key[1])))

    if not sharp_edges:
        return _write_sharp_file(sharp_filepath, None)

    sharp_arr = np.fromiter(
        (x for key in sharp_edges for x in key),
        dtype=np.int64,
        count=len(sharp_edges) * 2,
    ).reshape(-1, 2)

    from ..utils import native as _native
    res = _native.sharp_features(verts, faces, sharp_arr)
    if res is not None:
        conv, fi, jpos = res
    else:
        conv, fi, jpos = _sharp_features_numpy(verts, faces, sharp_arr)

    if conv.size == 0:
        return _write_sharp_file(sharp_filepath, None)

    lines = [
        f"{int(c)},{int(f_)},{int(j_)}"
        for c, f_, j_ in zip(conv, fi, jpos)
    ]
    return _write_sharp_file(sharp_filepath, lines)


def _build_mesh_data(
    vertices: np.ndarray,
    faces: list,
) -> MeshData:
    """Assemble a MeshData from raw verts/faces (mixed tri/quad)."""
    quad_faces = [tuple(f) for f in faces if len(f) == 4]
    tri_faces = [tuple(f) for f in faces if len(f) == 3]

    mesh = MeshData()
    mesh.vertices = np.asarray(vertices, dtype=np.float64)
    all_faces = quad_faces + tri_faces
    mesh.faces = (
        np.array(all_faces, dtype=object) if all_faces
        else np.array([], dtype=object)
    )
    mesh._quad_faces = quad_faces
    mesh._tri_faces = tri_faces

    tri_for_normals = []
    for f in quad_faces:
        tri_for_normals.append((f[0], f[1], f[2]))
        tri_for_normals.append((f[0], f[2], f[3]))
    tri_for_normals.extend(tri_faces)
    if tri_for_normals:
        tri_arr = np.array(tri_for_normals, dtype=np.int64)
        mesh.normals = compute_vertex_normals(mesh.vertices, tri_arr)
    return mesh


# ── Main entry point ──

def run_quadwild(
    input_mesh: MeshData,
    target_face_count: int,
    tolerance_percent: float = 10.0,
    sharp_angle: float = 30.0,
    keep_sharp: bool = True,
    adaptive_density: bool = False,
    settings: Optional[dict] = None,
    progress_callback: Optional[Callable[[str, float], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> RetopoResult:
    """Run the full QuadWild remeshing pipeline.

    Safe to call from a background thread (no bpy usage).

    Args:
        input_mesh: Triangulated input mesh
        target_face_count: Desired output face count
        tolerance_percent: Acceptable deviation before retry
        sharp_angle: Feature edge angle threshold (degrees, internal
            convention: angle between face normals, flat = 0)
        keep_sharp: Preserve sharp/feature edges
        adaptive_density: Run a coarse QuadWild base (~25% of budget)
            then adaptively subdivide towards detail regions
        progress_callback: (step_name, percent) progress reporting
        cancel_check: Returns True if the user cancelled

    Returns:
        RetopoResult with output_mesh populated
    """
    result = RetopoResult()
    time_start = time.time()

    # Apply engine settings (registry-driven UI) on top of the explicit
    # defaults. Keeps the legacy direct-call signature working — the
    # Blender-background tests still call with explicit kwargs and no
    # ``settings`` dict.
    if settings:
        tolerance_percent = float(
            settings.get("qw_tolerance", tolerance_percent))
        keep_sharp = bool(settings.get("qw_keep_sharp", keep_sharp))
        adaptive_density = bool(
            settings.get("qw_adaptive_density", adaptive_density))
        ui_angle = settings.get("sharp_angle_threshold", None)
        if ui_angle is not None:
            # UI follows the interior-dihedral convention (flat = 180);
            # the native QuadWild stage wants the angle between face
            # normals (flat = 0).
            sharp_angle = max(180.0 - float(ui_angle), 0.0)

    qr_overrides = (
        {k: settings[k] for k in _TUNABLE_FIELDS if k in settings}
        if settings else None
    )

    def report(step: str, pct: float):
        if progress_callback:
            progress_callback(step, pct)

    def cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    workdir = None
    try:
        if not is_quadwild_available():
            raise FileNotFoundError(
                "QuadWild 引擎库缺失：请将 lib_quadwild.dll 与 "
                "lib_quadpatches.dll 放入插件的 bin/quadwild 目录"
                "（当前发行版仅含 Windows 二进制）"
            )

        if cancelled():
            raise InterruptedError("用户取消")

        result.input_vert_count = input_mesh.n_verts
        result.input_face_count = input_mesh.n_faces

        # Stage 0: export input mesh to OBJ
        report("Exporting mesh...", 5.0)
        t0 = time.time()
        workdir = tempfile.mkdtemp(prefix="autotopo_quadwild_")
        mesh_path = os.path.join(workdir, "input.obj")
        write_obj(mesh_path, input_mesh.vertices, input_mesh.faces)
        logger.info(f"Stage timing: OBJ export {time.time() - t0:.2f}s")

        qw = QuadwildLib(mesh_path)

        if cancelled():
            raise InterruptedError("用户取消")

        # Sharp feature file (must exist before remeshAndField when
        # hasFeature is enabled)
        n_sharp = 0
        if keep_sharp:
            report("Detecting sharp features...", 8.0)
            t0 = time.time()
            n_sharp = _export_sharp_features(
                input_mesh, sharp_angle, qw.sharp_path,
            )
            logger.info(
                f"QuadWild: {n_sharp} sharp feature edges "
                f"({time.time() - t0:.2f}s)"
            )

        # Stage 1: remesh + cross field
        # With adaptive density the QuadWild stage only produces a
        # coarse base (~25% of the budget); the rest is filled in by
        # error-driven subdivision afterwards.
        qw_target = target_face_count
        if adaptive_density:
            qw_target = max(int(target_face_count * 0.25), 50)

        report("Remeshing and computing the direction field...", 15.0)
        t0 = time.time()
        qw.remesh_and_field(enable_sharp=keep_sharp, sharp_angle=sharp_angle)
        logger.info(f"Stage timing: remesh+field {time.time() - t0:.2f}s")
        if cancelled():
            raise InterruptedError("用户取消")

        # Stage 2: field tracing
        report("Tracing streamlines...", 40.0 if adaptive_density else 45.0)
        t0 = time.time()
        qw.trace()
        logger.info(f"Stage timing: trace {time.time() - t0:.2f}s")
        if not os.path.isfile(qw.traced_path):
            raise RuntimeError("QuadWild 流线追踪未生成输出")
        if cancelled():
            raise InterruptedError("用户取消")

        # Stage 3: quadrangulation with adaptive scale factor
        scale_fact = 1.0
        tol = max(tolerance_percent, 5.0) / 100.0
        output_path = qw.output_smoothed_path
        n_faces_out = 0

        # Each retry reports a higher percentage so the longest stage
        # no longer appears frozen at a constant 55/60% (audit #5).
        quad_base_pct = 55.0 if adaptive_density else 60.0
        for attempt in range(3):
            report(
                "Quadrangulation...",
                quad_base_pct + attempt * 5.0,
            )
            t0 = time.time()
            qw.quadrangulate(scale_fact, qr_overrides)
            if not os.path.isfile(output_path):
                output_path = qw.output_path
            if not os.path.isfile(output_path):
                raise RuntimeError("QuadWild 四边面化未生成输出")

            _, out_faces = read_obj(output_path)
            n_faces_out = len(out_faces)
            if n_faces_out == 0:
                raise RuntimeError("QuadWild 输出网格为空")

            deviation = abs(n_faces_out - qw_target) / max(qw_target, 1)
            logger.info(
                f"QuadWild attempt {attempt + 1}: {n_faces_out} faces "
                f"(target {qw_target}, scaleFact={scale_fact:.3f}) "
                f"[{time.time() - t0:.2f}s]"
            )
            if deviation <= tol or attempt == 2:
                break
            if cancelled():
                raise InterruptedError("用户取消")

            # Face count scales ~ 1/scaleFact^2
            scale_fact *= math.sqrt(n_faces_out / max(qw_target, 1))
            scale_fact = min(max(scale_fact, 0.05), 20.0)

        if adaptive_density:
            # Stage 4: error-driven adaptive quad subdivision
            report("Adaptive detail subdivision...", 70.0)
            base_verts, base_faces = read_obj(output_path)
            base_quads = [tuple(f) for f in base_faces if len(f) == 4]
            kept_tris = [tuple(f) for f in base_faces if len(f) == 3]
            if len(base_quads) < 4:
                raise RuntimeError("QuadWild 基底网格四边面过少，无法细分")
            if cancelled():
                raise InterruptedError("用户取消")

            def subd_progress(pct: float):
                report("Adaptive detail subdivision...", 70.0 + pct * 0.22)

            t0 = time.time()
            new_verts, subd_faces, _ = adaptive_subdivide(
                base_verts,
                base_quads,
                input_mesh.vertices,
                target_face_count,
                max_depth=3,
                progress_callback=subd_progress,
                cancel_check=cancel_check,
                source_faces=input_mesh.faces,
            )
            logger.info(
                f"QuadWild adaptive: base {len(base_faces)} -> "
                f"{len(subd_faces) + len(kept_tris)} faces "
                f"(budget {target_face_count}) "
                f"[{time.time() - t0:.2f}s]"
            )
            report("Reading result...", 94.0)
            output_mesh = _build_mesh_data(
                new_verts, subd_faces + kept_tris
            )
        else:
            report("Reading result...", 92.0)
            output_mesh = obj_to_mesh_data(output_path)

        if not output_mesh.validate():
            raise RuntimeError("QuadWild 输出网格无效")

        result.output_mesh = output_mesh
        result.output_vert_count = output_mesh.n_verts
        result.output_face_count = output_mesh.n_faces

        quad_faces = getattr(output_mesh, '_quad_faces', [])
        tri_faces = getattr(output_mesh, '_tri_faces', [])
        result.output_quad_count = len(quad_faces)
        result.output_tri_count = len(tri_faces)
        total = len(quad_faces) + len(tri_faces)
        result.triangle_ratio = len(tri_faces) / max(total, 1)

        try:
            t0 = time.time()
            result.silhouette_error = compute_silhouette_error(
                output_mesh, input_mesh
            )
            logger.info(
                f"Stage timing: silhouette evaluation "
                f"{time.time() - t0:.2f}s"
            )
        except Exception as e:
            logger.warning(f"Silhouette error computation failed: {e}")
            result.silhouette_error = 0.0
        result.patch_count = 1

        report("Done", 100.0)
        result.success = True
        logger.info(
            f"QuadWild engine finished: {result.output_face_count} faces "
            f"({result.output_quad_count} quads, {result.output_tri_count} tris)"
        )

    except InterruptedError:
        result.success = False
        result.error_message = "用户取消"
    except Exception as e:
        import traceback
        result.success = False
        result.error_message = str(e)
        logger.error(f"QuadWild engine failed:\n{traceback.format_exc()}")
    finally:
        result.time_total = time.time() - time_start
        if workdir:
            try:
                shutil.rmtree(workdir, ignore_errors=True)
            except Exception:
                pass

    return result


# ── Engine registration ──────────────────────────────────────────────

@register_engine
class QuadWildEngine(RemeshEngine):
    """QuadWild (SIGGRAPH Asia 2019) — cross-field + ILP quadrangulation.

    Field-aligned cross-field quantization followed by an ILP-based
    final quadrangulation (QuadPatches). Produces clean quads in the
    interior but carries a handful of transition triangles along
    singularity boundaries — which is why very dense meshes can look
    busier than field-parametrisation methods (QuadriFlow / AutoRemesher).

    Defaults are the QRemeshify / paper-recommended values shipped with
    the reference implementation; only the knobs in :data:`_TUNABLE_FIELDS`
    are user-tunable.
    """

    id = "quadwild"
    label = "QuadWild 高质量"
    description = ("QuadWild (SIGGRAPH Asia 2019)：交叉场量化 + ILP 最终四边面化，"
                   "内部四边面干净、奇点处带少量过渡三角面")
    shared_props = ("sharp_angle_threshold",)

    settings = (
        SettingSpec(
            key="qw_keep_sharp",
            label="保留锐边",
            kind="bool",
            default=True,
            description="重拓扑时检测并保留锐利边缘特征（关闭则视为纯平滑曲面）",
            source="QuadWild 默认 hasFeature=true",
        ),
        SettingSpec(
            key="qw_tolerance",
            label="面数容差",
            kind="float",
            default=10.0,
            min=1.0,
            max=20.0,
            precision=1,
            unit="%",
            description="允许输出面数相对目标的偏差（百分比），超出则重跑四边面化",
            source="AutoTopo 工程取值",
        ),
        SettingSpec(
            key="qw_adaptive_density",
            label="自适应密度",
            kind="bool",
            default=True,
            description="按细节分布面数：破损/高曲率区域更密、平面更疏"
                        "（先跑粗 QuadWild 基底再误差驱动细分）",
            source="AutoTopo 工程默认开启",
        ),
        SettingSpec(
            key="qw_isometry",
            label="等距约束",
            kind="bool",
            default=True,
            description="保持局部等距，减少拉伸变形（论文默认开启）",
            source="QuadWild 默认 isometry=true",
        ),
        SettingSpec(
            key="qw_hard_parity",
            label="硬奇偶性约束",
            kind="bool",
            default=True,
            description="强制四边形奇偶性约束，减少非四边面（论文默认开启）",
            source="QuadWild 默认 hardParityConstraint=true",
        ),
        SettingSpec(
            key="qw_use_flow_solver",
            label="流求解器",
            kind="bool",
            default=True,
            description="使用流求解器求解整数约束（论文默认开启）",
            source="QuadWild 默认 useFlowSolver=true",
        ),
        SettingSpec(
            key="qw_final_smoothing",
            label="最终平滑",
            kind="bool",
            default=True,
            description="四边面化完成后做一次整体平滑（论文默认开启）",
            source="QuadWild 默认 finalSmoothing=true",
        ),
        SettingSpec(
            key="qw_doublet_removal",
            label="双元移除",
            kind="bool",
            default=True,
            description="移除 doublet（相邻重复四边形），改善网格质量（默认开启）",
            source="QuadWild 默认 doubletRemoval=true",
        ),
        SettingSpec(
            key="qw_split_concaves",
            label="拆分凹面",
            kind="bool",
            default=False,
            description="拆分凹四边形以避免退化（默认关闭，可能改变面数）",
            source="QuadWild 默认 splitConcaves=false",
        ),
        # ── 高级参数（论文/参考实现默认值）──
        SettingSpec(
            key="qw_ilp_method",
            label="ILP 方法",
            kind="int",
            default=1,
            min=0,
            max=3,
            description="整数规划求解方法：0=高斯、1=最小二乘(默认)、2/3=其它",
            source="QuadWild 默认 ilpMethod=1 (LEASTSQUARES)",
            advanced=True,
        ),
        SettingSpec(
            key="qw_time_limit",
            label="求解时间上限",
            kind="float",
            default=60.0,
            min=1.0,
            max=600.0,
            precision=0,
            unit="s",
            description="四边面化 ILP 求解的时间上限（秒）",
            source="QuadWild 默认 timeLimit=60",
            advanced=True,
        ),
        SettingSpec(
            key="qw_alpha",
            label="对齐权重 α",
            kind="float",
            default=0.005,
            min=0.0,
            max=1.0,
            precision=3,
            description="奇点对齐的能量权重（越小越弱）",
            source="QuadWild 默认 alpha=0.005",
            advanced=True,
        ),
        SettingSpec(
            key="qw_minimum_gap",
            label="最小间隙",
            kind="float",
            default=0.4,
            min=0.0,
            max=1.0,
            precision=2,
            description="ILP 求解的最小间隙阈值",
            source="QuadWild 默认 minimumGap=0.4",
            advanced=True,
        ),
        SettingSpec(
            key="qw_gap_limit",
            label="间隙上限",
            kind="float",
            default=0.0,
            min=0.0,
            max=1.0,
            precision=2,
            description="ILP 求解的间隙停止阈值",
            source="QuadWild 默认 gapLimit=0.0",
            advanced=True,
        ),
        SettingSpec(
            key="qw_align_sing_weight",
            label="奇点对齐权重",
            kind="float",
            default=0.1,
            min=0.0,
            max=1.0,
            precision=2,
            description="奇点对齐项权重（与 α 协同）",
            source="QuadWild 默认 alignSingularitiesWeight=0.1",
            advanced=True,
        ),
        SettingSpec(
            key="qw_regularity_weight",
            label="规则性权重",
            kind="float",
            default=0.9,
            min=0.0,
            max=1.0,
            precision=2,
            description="非四边形规则性惩罚权重",
            source="QuadWild 默认 regularityNonQuadrilateralsWeight=0.9",
            advanced=True,
        ),
        SettingSpec(
            key="qw_result_smooth_iters",
            label="结果平滑迭代",
            kind="int",
            default=5,
            min=0,
            max=50,
            description="最终结果整体平滑迭代次数",
            source="QuadWild 默认 resultSmoothingIterations=5",
            advanced=True,
        ),
        SettingSpec(
            key="qw_result_smooth_laplacian",
            label="拉普拉斯平滑迭代",
            kind="int",
            default=2,
            min=0,
            max=50,
            description="最终结果拉普拉斯平滑迭代次数",
            source="QuadWild 默认 resultSmoothingLaplacianIterations=2",
            advanced=True,
        ),
        SettingSpec(
            key="qw_chart_smooth_iters",
            label="图表平滑迭代",
            kind="int",
            default=0,
            min=0,
            max=50,
            description="图表平滑迭代次数",
            source="QuadWild 默认 chartSmoothingIterations=0",
            advanced=True,
        ),
        SettingSpec(
            key="qw_quad_smooth_fixed",
            label="固定点平滑迭代",
            kind="int",
            default=0,
            min=0,
            max=50,
            description="四边面化固定点平滑迭代次数",
            source="QuadWild 默认 quadrangulationFixedSmoothingIterations=0",
            advanced=True,
        ),
        SettingSpec(
            key="qw_quad_smooth_nonfixed",
            label="非固定点平滑迭代",
            kind="int",
            default=0,
            min=0,
            max=50,
            description="四边面化非固定点平滑迭代次数",
            source="QuadWild 默认 quadrangulationNonFixedSmoothingIterations=0",
            advanced=True,
        ),
        SettingSpec(
            key="qw_feasibility_fix",
            label="可行性修复",
            kind="bool",
            default=False,
            description="启用可行性修复后处理（默认关闭）",
            source="QuadWild 默认 feasibilityFix=false",
            advanced=True,
        ),
    )

    # ------------------------------------------------------------------
    # capability
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        return is_quadwild_available()

    @staticmethod
    def unavailable_hint() -> str:
        return ("QuadWild libraries not found. Place lib_quadwild.dll and "
                "lib_quadpatches.dll in the addon's bin/quadwild/ directory "
                "(the current release ships Windows binaries only), then "
                "restart Blender and try again.")

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------

    @staticmethod
    def run(
        input_mesh: MeshData,
        target_face_count: int,
        settings: Optional[dict] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> RetopoResult:
        return run_quadwild(
            input_mesh,
            target_face_count=target_face_count,
            settings=settings,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
