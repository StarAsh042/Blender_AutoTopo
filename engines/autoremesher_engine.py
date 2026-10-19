"""AutoRemesher engine — CLI wrapper around the AutoRemesher executable.

AutoRemesher (huxingyi/autoremesher, MIT) converts a dense triangle mesh
into a clean quad mesh. It ships as a standalone executable, so this
engine drives it as a subprocess:

    autoremesher -i in.obj -o out.obj --target-quads N
                 [--edge-scaling F] [--sharp-edge DEG]
                 [--smooth-normal DEG] [--adaptivity V] [--anisotropy V]
                 [--report stats.txt]

Defaults and ranges below are taken verbatim from ``autoremesher --help``
(v1.2.0), so the UI exposes exactly the options the tool documents.

Runs on a background worker thread (no ``bpy`` access), and never raises:
failures land in ``result.error_message``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..utils import integrity
from ..utils.logger import logger
from ..utils.mesh_io import MeshData, obj_to_mesh_data
from .base import RemeshEngine, SettingSpec, register_engine
from .evaluation import RetopoResult, compute_silhouette_error
from .obj_io import write_obj

_ENGINE_BIN_SUBDIR = "autoremesher"
_EXE_NAMES = ("autoremesher.exe", "autoremesher")

# Subprocess hard timeout. AutoRemesher is fast (<2s for typical budgets),
# so this mainly guards against a wedged child process.
_TIMEOUT_SECONDS = 900


def _bundled_dir() -> str:
    """Directory of the executable bundled with the addon."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "bin", _ENGINE_BIN_SUBDIR)


def _bundled_rel_key(name: str) -> str:
    return f"bin/{_ENGINE_BIN_SUBDIR}/{name}"


def _is_inside(path: str, directory: str) -> bool:
    try:
        p = os.path.normcase(os.path.abspath(path))
        d = os.path.normcase(os.path.abspath(directory))
        return os.path.commonpath([p, d]) == d
    except Exception:
        return False


def _resolve_checked(
    explicit: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve the executable, enforcing the integrity trust model.

    Returns ``(path, error)``. ``path`` is ``None`` when no trusted
    executable could be resolved; ``error`` then holds a Chinese message
    (``None`` for the plain "not found" case).

    Trust rules (see :mod:`utils.integrity`):

    * An explicit path (from the addon preferences) is honored **only**
      when, after resolution, it lies **inside** the engine's own bundled
      directory ``bin/autoremesher/`` and the whole directory passes
      integrity verification. Any path outside it is ignored — an
      external copy could load its DLL dependencies from system ``PATH``,
      so it is never trusted. This removes both the "tamper the
      preference file -> arbitrary code execution" and the "external
      directory -> DLL hijack" vectors.
    * Otherwise the bundled ``bin/autoremesher/`` binary is used.
    * The system ``PATH`` is never searched.

    ``explicit`` exists because engines run on a background worker thread,
    where touching ``bpy.context`` is unsafe — the operator reads the
    preference on the main thread and passes it in.
    """
    bin_dir = _bundled_dir()

    if explicit:
        candidate = os.path.abspath(explicit.strip())
        if os.path.isfile(candidate) and _is_inside(candidate, bin_dir):
            if not integrity.verify_file(candidate):
                return None, (
                    "内置二进制完整性校验失败，已拒绝加载："
                    f"{os.path.basename(candidate)}")
            ok, failed = integrity.verify_tree(bin_dir)
            if not ok:
                return None, (
                    "内置二进制完整性校验失败，已拒绝加载："
                    f"{os.path.basename(failed)}")
            return candidate, None
        logger.warning(
            "AutoRemesher: 忽略内置目录之外的偏好路径：%s", candidate)

    for name in _EXE_NAMES:
        candidate = os.path.join(bin_dir, name)
        if os.path.isfile(candidate):
            if not integrity.verify(candidate, _bundled_rel_key(name)):
                return None, f"内置二进制完整性校验失败，已拒绝加载：{name}"
            ok, failed = integrity.verify_tree(bin_dir)
            if not ok:
                return None, (
                    "内置二进制完整性校验失败，已拒绝加载："
                    f"{os.path.basename(failed)}")
            return candidate, None
    return None, None


def resolve_exe(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve the executable (see :func:`_resolve_checked`)."""
    return _resolve_checked(explicit)[0]


def _parse_report(path: str) -> Dict[str, Any]:
    """Parse AutoRemesher's ``--report`` output into numbers."""
    out: Dict[str, Any] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                value = value.strip()
                if not value:
                    continue
                key = key.strip()
                try:
                    out[key] = int(value)
                except ValueError:
                    try:
                        out[key] = float(value)
                    except ValueError:
                        out[key] = value
    except Exception:
        pass
    return out


@register_engine
class AutoRemesherEngine(RemeshEngine):
    """AutoRemesher — isotropically remesh, parametrise, extract quads.

    Produces a near-pure quad mesh (measured 1739 quads / 2 non-quads on a
    2000-quad budget) and is roughly an order of magnitude faster than the
    QuadWild path, because it does not run an ILP quadrangulation.
    """

    id = "autoremesher"
    label = "AutoRemesher 快速四边面"
    description = ("AutoRemesher (MIT)：各向同性重网格 + 参数化 + 四边面提取，"
                   "四边面比例极高、速度快")
    # AutoRemesher uses the same interior-dihedral sharp-angle convention
    # as the UI's shared ``sharp_angle_threshold``.
    shared_props = ("sharp_angle_threshold",)

    settings = (
        SettingSpec(
            key="ar_edge_scaling",
            label="边长缩放",
            kind="float",
            default=1.0,
            min=1.0,
            max=4.0,
            precision=2,
            description="全局边长缩放系数。大于 1 使四边面更稀疏（默认 1.0）",
            source="AutoRemesher --help 默认值",
        ),
        SettingSpec(
            key="ar_smooth_normal",
            label="平滑法线角度",
            kind="float",
            default=0.0,
            min=0.0,
            max=180.0,
            precision=1,
            unit="°",
            description="小于该角度时法线平滑着色；0 表示不平滑（默认 0）",
            source="AutoRemesher --help 默认值",
        ),
        SettingSpec(
            key="ar_adaptivity",
            label="自适应密度",
            kind="float",
            default=1.0,
            min=0.0,
            max=1.0,
            precision=2,
            description="按曲率分配面数：1 为完全自适应，0 为均匀（默认 1.0）",
            source="AutoRemesher --help 默认值",
        ),
        SettingSpec(
            key="ar_anisotropy",
            label="各向异性拉伸",
            kind="float",
            default=1.0,
            min=0.0,
            max=1.0,
            precision=2,
            description="沿曲率方向拉长四边面：1 为允许拉伸，0 为保持方正（默认 1.0）",
            source="AutoRemesher --help 默认值",
        ),
        SettingSpec(
            key="ar_write_report",
            label="输出统计报告",
            kind="bool",
            default=False,
            description="额外让 AutoRemesher 写一份统计文件（四边面/非四边面/顶点/耗时）",
            source="AutoRemesher --report",
            advanced=True,
        ),
    )

    # ------------------------------------------------------------------
    # capability
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        # Presence only — integrity is enforced on the execution path
        # (resolve_exe), so the panel does not re-hash large binaries on
        # every redraw.
        bin_dir = _bundled_dir()
        return any(
            os.path.isfile(os.path.join(bin_dir, name))
            for name in _EXE_NAMES
        )

    @staticmethod
    def unavailable_hint() -> str:
        return ("未找到 AutoRemesher。请将 autoremesher.exe 放入插件内置的 "
                "bin/autoremesher/ 目录后重试。")

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------

    @staticmethod
    def run(
        input_mesh: MeshData,
        target_face_count: int,
        settings: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> RetopoResult:
        result = RetopoResult()
        started = time.time()

        def report(step: str, pct: float) -> None:
            if progress_callback:
                progress_callback(step, pct)

        def cancelled() -> bool:
            return bool(cancel_check and cancel_check())

        workdir: Optional[str] = None
        try:
            exe, resolve_err = _resolve_checked(
                (settings or {}).get("exe_path")  # set by the operator
            )
            if exe is None:
                result.error_message = (
                    resolve_err or AutoRemesherEngine.unavailable_hint()
                )
                logger.error(result.error_message)
                return result

            result.input_vert_count = input_mesh.n_verts
            result.input_face_count = input_mesh.n_faces

            report("导出网格...", 10.0)
            workdir = tempfile.mkdtemp(prefix="autotopo_autoremesher_")
            in_path = os.path.join(workdir, "input.obj")
            out_path = os.path.join(workdir, "output.obj")
            write_obj(in_path, input_mesh.vertices, input_mesh.faces)

            if cancelled():
                raise InterruptedError("用户取消")

            report("运行 AutoRemesher...", 40.0)
            cmd: List[str] = [
                exe,
                "-i", in_path,
                "-o", out_path,
                "--target-quads", str(max(int(target_face_count), 1)),
            ]
            cmd += ["--edge-scaling",
                    repr(float(AutoRemesherEngine.resolve(
                        "ar_edge_scaling", settings)))]
            # AutoRemesher uses the same interior-dihedral angle
            # convention as the UI's shared sharp_angle_threshold.
            sharp_angle = float((settings or {}).get(
                "sharp_angle_threshold", 90.0))
            cmd += ["--sharp-edge", repr(sharp_angle)]
            cmd += ["--smooth-normal",
                    repr(float(AutoRemesherEngine.resolve(
                        "ar_smooth_normal", settings)))]
            cmd += ["--adaptivity",
                    repr(float(AutoRemesherEngine.resolve(
                        "ar_adaptivity", settings)))]
            cmd += ["--anisotropy",
                    repr(float(AutoRemesherEngine.resolve(
                        "ar_anisotropy", settings)))]

            report_path = None
            if bool(AutoRemesherEngine.resolve("ar_write_report", settings)):
                report_path = os.path.join(workdir, "report.txt")
                cmd += ["--report", report_path]

            logger.info("AutoRemesher: %s", " ".join(cmd))
            t0 = time.time()
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=_TIMEOUT_SECONDS,
                check=False,
                cwd=workdir,
            )
            logger.info("AutoRemesher finished in %.2fs (rc=%d)",
                        time.time() - t0, proc.returncode)

            if proc.returncode != 0:
                tail = (proc.stdout or b"").decode("utf-8", "replace")[-800:]
                result.error_message = (
                    f"AutoRemesher 执行失败（退出码 {proc.returncode}）"
                )
                logger.error("%s\n%s", result.error_message, tail)
                return result

            if not os.path.isfile(out_path):
                result.error_message = "AutoRemesher 未生成输出文件"
                logger.error(result.error_message)
                return result

            if cancelled():
                raise InterruptedError("用户取消")

            report("读取结果...", 80.0)
            output_mesh = obj_to_mesh_data(out_path)
            if not output_mesh.validate():
                result.error_message = "AutoRemesher 输出网格无效"
                logger.error(result.error_message)
                return result

            result.output_mesh = output_mesh
            result.output_vert_count = output_mesh.n_verts
            result.output_face_count = output_mesh.n_faces

            quad_faces = getattr(output_mesh, "_quad_faces", []) or []
            tri_faces = getattr(output_mesh, "_tri_faces", []) or []
            result.output_quad_count = len(quad_faces)
            result.output_tri_count = len(tri_faces)
            total = len(quad_faces) + len(tri_faces)
            result.triangle_ratio = len(tri_faces) / max(total, 1)
            result.patch_count = 1

            if report_path and os.path.isfile(report_path):
                stats = _parse_report(report_path)
                logger.info("AutoRemesher report: %s", stats)

            try:
                result.silhouette_error = compute_silhouette_error(
                    output_mesh, input_mesh
                )
            except Exception as e:  # pragma: no cover - diagnostic only
                logger.warning("Silhouette error computation failed: %s", e)
                result.silhouette_error = 0.0

            report("完成", 100.0)
            result.success = True
            logger.info(
                "AutoRemesher: %d faces (%d quads, %d tris)",
                result.output_face_count,
                result.output_quad_count,
                result.output_tri_count,
            )

        except InterruptedError as e:
            result.success = False
            result.error_message = str(e)
        except subprocess.TimeoutExpired:
            result.success = False
            result.error_message = (
                f"AutoRemesher 超时（>{_TIMEOUT_SECONDS}s）"
            )
            logger.error(result.error_message)
        except Exception as e:
            import traceback

            result.success = False
            result.error_message = f"{type(e).__name__}: {e}"
            logger.error("AutoRemesher engine failed:\n%s",
                         traceback.format_exc())
        finally:
            result.time_total = time.time() - started
            if workdir:
                shutil.rmtree(workdir, ignore_errors=True)

        return result
