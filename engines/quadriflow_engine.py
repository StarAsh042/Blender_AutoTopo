"""QuadriFlow engine — CLI wrapper around the QuadriFlow executable.

QuadriFlow (hjwdzh/QuadriFlow, MIT) is a scalable field-aligned
quadrangulation method. It ships as a standalone executable, so this
engine drives it as a subprocess:

    quadriflow -i in.obj -o out.obj -f <faces>
               [-sharp] [-boundary] [-adaptive] [-mcf] [-sat] [-seed N]

The recommended invocation documented in the README is
``quadriflow -i input.obj -o output.obj -f [resolution]``, with ``-mcf``
offered as an alternative mode. All other switches default to ``0`` in
``src/parametrizer.hpp``, which is what the UI shows by default.

Runs on a background worker thread (no ``bpy`` access) and never raises:
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

_ENGINE_BIN_SUBDIR = "quadriflow"
_EXE_NAMES = ("quadriflow.exe", "quadriflow")

_TIMEOUT_SECONDS = 1800


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
      directory ``bin/quadriflow/`` and the whole directory passes
      integrity verification. Any path outside it is ignored — an
      external copy could load its DLL dependencies from system ``PATH``,
      so it is never trusted. This removes both the "tamper the
      preference file -> arbitrary code execution" and the "external
      directory -> DLL hijack" vectors.
    * Otherwise the bundled ``bin/quadriflow/`` binary is used.
    * The system ``PATH`` is never searched.
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
            "QuadriFlow: 忽略内置目录之外的偏好路径：%s", candidate)

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


@register_engine
class QuadriFlowEngine(RemeshEngine):
    """QuadriFlow — scalable field-aligned quadrangulation."""

    id = "quadriflow"
    label = "QuadriFlow 场对齐"
    description = ("QuadriFlow (MIT, SIGGRAPH 2020)：方向场对齐 + 全局参数化，"
                   "布线均匀、可扩展到高面数")

    settings = (
        SettingSpec(
            key="qf_preserve_sharp",
            label="保留锐边",
            kind="bool",
            default=False,
            description="-sharp：保留输入网格的锐利特征边（上游默认关闭）",
            source="parametrizer.hpp flag_preserve_sharp=0",
        ),
        SettingSpec(
            key="qf_preserve_boundary",
            label="保留边界",
            kind="bool",
            default=False,
            description="-boundary：为开放边界添加约束（上游默认关闭）",
            source="parametrizer.hpp flag_preserve_boundary=0",
        ),
        SettingSpec(
            key="qf_adaptive_scale",
            label="自适应尺度",
            kind="bool",
            default=False,
            description="-adaptive：允许尺度随曲率自适应（上游默认关闭）",
            source="parametrizer.hpp flag_adaptive_scale=0",
        ),
        SettingSpec(
            key="qf_minimum_cost_flow",
            label="最小费用流模式",
            kind="bool",
            default=False,
            description="-mcf：改用最小费用流求解整数约束，README 推荐的替代模式",
            source="README 推荐用法 / parametrizer.hpp 默认 0",
        ),
        SettingSpec(
            key="qf_aggressive_sat",
            label="激进 SAT 求解",
            kind="bool",
            default=False,
            description="-sat：更激进的 SAT 求解（上游默认关闭）",
            source="parametrizer.hpp flag_aggresive_sat=0",
            advanced=True,
        ),
        SettingSpec(
            key="qf_seed",
            label="随机种子",
            kind="int",
            default=0,
            min=0,
            soft_max=100000,
            description="-seed：固定随机种子以获得可复现结果（0 表示由程序决定）",
            source="main.cpp -seed",
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
        return ("未找到 QuadriFlow。请将 quadriflow.exe 放入插件内置的 "
                "bin/quadriflow/ 目录后重试。")

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
                (settings or {}).get("exe_path"))
            if exe is None:
                result.error_message = (
                    resolve_err or QuadriFlowEngine.unavailable_hint()
                )
                logger.error(result.error_message)
                return result

            result.input_vert_count = input_mesh.n_verts
            result.input_face_count = input_mesh.n_faces

            report("导出网格...", 10.0)
            workdir = tempfile.mkdtemp(prefix="autotopo_quadriflow_")
            in_path = os.path.join(workdir, "input.obj")
            out_path = os.path.join(workdir, "output.obj")
            write_obj(in_path, input_mesh.vertices, input_mesh.faces)

            if cancelled():
                raise InterruptedError("用户取消")

            report("运行 QuadriFlow...", 40.0)
            cmd: List[str] = [
                exe,
                "-i", in_path,
                "-o", out_path,
                "-f", str(max(int(target_face_count), 1)),
            ]
            if bool(QuadriFlowEngine.resolve("qf_preserve_sharp", settings)):
                cmd.append("-sharp")
            if bool(QuadriFlowEngine.resolve("qf_preserve_boundary", settings)):
                cmd.append("-boundary")
            if bool(QuadriFlowEngine.resolve("qf_adaptive_scale", settings)):
                cmd.append("-adaptive")
            if bool(QuadriFlowEngine.resolve("qf_minimum_cost_flow", settings)):
                cmd.append("-mcf")
            if bool(QuadriFlowEngine.resolve("qf_aggressive_sat", settings)):
                cmd.append("-sat")
            seed = int(QuadriFlowEngine.resolve("qf_seed", settings) or 0)
            if seed:
                cmd += ["-seed", str(seed)]

            logger.info("QuadriFlow: %s", " ".join(cmd))
            t0 = time.time()
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=_TIMEOUT_SECONDS,
                check=False,
                cwd=workdir,
            )
            logger.info("QuadriFlow finished in %.2fs (rc=%d)",
                        time.time() - t0, proc.returncode)

            if proc.returncode != 0:
                tail = (proc.stdout or b"").decode("utf-8", "replace")[-800:]
                result.error_message = (
                    f"QuadriFlow 执行失败（退出码 {proc.returncode}）"
                )
                logger.error("%s\n%s", result.error_message, tail)
                return result

            if not os.path.isfile(out_path):
                result.error_message = "QuadriFlow 未生成输出文件"
                logger.error(result.error_message)
                return result

            if cancelled():
                raise InterruptedError("用户取消")

            report("读取结果...", 80.0)
            output_mesh = obj_to_mesh_data(out_path)
            if not output_mesh.validate():
                result.error_message = "QuadriFlow 输出网格无效"
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
                "QuadriFlow: %d faces (%d quads, %d tris)",
                result.output_face_count,
                result.output_quad_count,
                result.output_tri_count,
            )

        except InterruptedError as e:
            result.success = False
            result.error_message = str(e)
        except subprocess.TimeoutExpired:
            result.success = False
            result.error_message = f"QuadriFlow 超时（>{_TIMEOUT_SECONDS}s）"
            logger.error(result.error_message)
        except Exception as e:
            import traceback

            result.success = False
            result.error_message = f"{type(e).__name__}: {e}"
            logger.error("QuadriFlow engine failed:\n%s",
                         traceback.format_exc())
        finally:
            result.time_total = time.time() - started
            if workdir:
                shutil.rmtree(workdir, ignore_errors=True)

        return result
