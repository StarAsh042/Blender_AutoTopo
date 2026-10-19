"""Blender operators for AutoTopo.

The retopologize operator is engine-agnostic: it looks the selected
engine up in the registry, builds a ``settings`` dict from the engine's
declared :class:`SettingSpec` keys (plus the shared ``sharp_angle_threshold``
and, for CLI engines, an ``exe_path`` read from the addon preferences),
then runs the engine on a background worker thread.
"""

import os
import bpy
import time
import threading
from bpy.types import Operator
from bpy.props import IntProperty

from ..utils.logger import logger
from ..utils.mesh_io import blender_to_mesh_data, mesh_data_to_blender
from ..engines.base import get_engine


# ── Thread-safe progress state (module-level, shared with worker thread) ──
_progress_lock = threading.Lock()
_progress_step = ""
_progress_pct = 0.0
# 显示层平滑：四边面化阶段最多重试 3 次，引擎每次上报同一百分比
# （quadwild_engine.py 的重试循环），会让最长阶段看起来「冻结」。
# 这里统计重复上报次数，把展示值逐步推进并标注「重试 n/3」，
# 使进度条持续前进、用户能看出仍在工作而非卡死。
_progress_last_raw = -1.0
_progress_repeat = 0
_RETRY_NUDGE = 4.0        # 每次重复上报推进的百分比
_RETRY_MAX_NUDGE = 12.0   # 单个阶段内最多推进的百分比
_RETRY_STAGE_HINT = "四边面化"  # 需要标注重试次数的阶段名


def _progress_callback(step_name: str, pct: float):
    """Called from pipeline worker thread to report progress."""
    global _progress_step, _progress_pct
    global _progress_last_raw, _progress_repeat

    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return

    with _progress_lock:
        if pct <= _progress_last_raw + 1e-6:
            # 百分比没有前进 → 引擎重复了同一阶段（四边面化重试）。
            _progress_repeat += 1
        else:
            _progress_repeat = 0
        _progress_last_raw = max(_progress_last_raw, pct)

        display = pct
        step = step_name
        if _progress_repeat > 0:
            display = min(
                pct + min(_progress_repeat * _RETRY_NUDGE, _RETRY_MAX_NUDGE),
                99.0,
            )
            if _RETRY_STAGE_HINT in (step_name or ""):
                step = f"{step_name}（重试 {_progress_repeat}/3）"

        _progress_step = step
        _progress_pct = display


# ── Shared run state (module-level, written by worker thread) ──
_pipeline_result = None
_pipeline_error = ""
_input_mesh = None
_obj_name = ""
_cancel_requested = False


def _to_friendly_error(err) -> str:
    """把内部异常映射为「中文说明 + 建议动作」。

    用户不应看到 `ValueError: ...` 这类英文栈信息；完整栈由调用方写入
    日志。未知错误只保留简短摘要（单行、截断），不暴露完整堆栈。
    """
    if err is None:
        return "处理失败：发生未知错误，详细信息见日志。"

    text = str(err).strip()
    low = text.lower()

    # 用户取消
    if "用户取消" in text or low in ("cancelled", "canceled") \
            or "interrupted" in low:
        return "已取消：本次拓扑重建被中止，可调整参数后重新执行。"

    # 内置二进制完整性校验失败（被篡改 / 版本不符）。必须早于
    # 「缺少可执行文件 / 库」分支，否则会被误判为文件缺失。
    if "完整性校验失败" in text or "integrity" in low:
        return ("内置二进制完整性校验失败：文件可能被篡改或版本不匹配。"
                "请重新安装插件，或更新 bin/integrity.json 后重试。")

    # QuadWild 原生库缺失
    if ("库缺失" in text or "引擎库缺失" in text
            or "lib_quadwild" in low or "lib_quadpatches" in low
            or ("quadwild" in low and "filenotfound" in low)):
        return ("缺少 QuadWild 算法库：请确认插件 bin/quadwild 目录下已放入 "
                "lib_quadwild.dll 与 lib_quadpatches.dll，然后重启 Blender 重试。")

    # 可执行文件缺失（AutoRemesher / QuadriFlow）
    if ("未找到" in text or "autoremesher" in low or "quadriflow" in low
            or "可执行" in text or "exe" in low):
        return ("缺少外部可执行文件：请确认对应引擎已内置或已在插件偏好设置中"
                "填写正确的可执行文件路径，然后重试。")

    # numpy 缺失
    if ("numpy" in low or "no module named" in low
            or "modulenotfounderror" in low or "importerror" in low):
        return ("缺少 Python 依赖 numpy：请为 Blender 自带 Python 安装 numpy "
                "（或改用官方 Blender 发行版）后重试。")

    # 创建输出网格失败
    if "创建网格失败" in text or "创建输出网格" in text:
        return "创建输出网格失败：请检查输入网格是否有效，详细信息见日志。"

    # 网格数据无效
    if ("无效的网格" in text or "validate" in low
            or ("invalid" in low and "mesh" in low)):
        return ("网格数据无效：请确认所选对象是有效网格（可在编辑模式下检查并"
                "移除零面积面）后重试。")

    # 未知引擎
    if "未知引擎" in text or "unknown engine" in low:
        return "未知算法引擎：请在上方面板重新选择引擎后重试。"

    # 引擎未生成有效输出
    if ("未生成输出" in text or "输出网格为空" in text
            or "输出网格无效" in text or "四边面过少" in text):
        return ("引擎未生成有效输出：请尝试降低目标面数、关闭自适应密度或"
                "放宽容差后重试。")

    # 未知错误：保留单行简短摘要，不暴露完整英文栈
    summary = " ".join(text.split())
    if not summary:
        summary = type(err).__name__
    elif len(summary) > 120:
        summary = summary[:117] + "..."
    return f"处理失败：{summary}（详细信息见日志）"


def _resolve_exe_path(engine_id: str, context) -> str:
    """Read the optional manual executable path for a CLI engine.

    The operator runs on the main thread, so it may safely touch
    ``bpy.context.preferences``. Returns an absolute path or ``""``.
    """
    try:
        addon = context.preferences.addons.get("Blender_AutoTopo")
        prefs = getattr(addon, "preferences", None) if addon else None
        if prefs is None:
            return ""
        if engine_id == "autoremesher":
            path = getattr(prefs, "autoremesher_path", "") or ""
        elif engine_id == "quadriflow":
            path = getattr(prefs, "quadriflow_path", "") or ""
        else:
            path = ""
        path = (path or "").strip()
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return ""


def _poll_timer():
    """Timer callback on Blender main thread — does NOT block UI interaction."""
    global _pipeline_result, _pipeline_error, _progress_step, _progress_pct

    # Read thread-safe progress
    with _progress_lock:
        step = _progress_step
        pct = _progress_pct

    # Only update UI if progress changed (avoid unnecessary redraws)
    ui_changed = False
    for scene in bpy.data.scenes:
        if hasattr(scene, 'auto_topo'):
            props = scene.auto_topo
            if props.step_name != step or abs(props.progress - pct) > 0.5:
                props.step_name = step
                props.progress = pct
                ui_changed = True

    # Only redraw if something changed
    if ui_changed:
        try:
            wm = bpy.context.window_manager
            if wm:
                for window in wm.windows:
                    for area in window.screen.areas:
                        if area.type == 'VIEW_3D':
                            area.tag_redraw()
        except Exception:
            pass

    # Check if pipeline finished
    if _pipeline_result is not None:
        result = _pipeline_result
        _pipeline_result = None
        _handle_pipeline_done(result)
        return None  # Stop timer

    # Check for thread error
    if _pipeline_error:
        err = _pipeline_error
        _pipeline_error = ""
        is_cancel = err in ("用户取消", "Cancelled")
        for scene in bpy.data.scenes:
            if hasattr(scene, 'auto_topo'):
                if is_cancel:
                    scene.auto_topo.status_message = "已取消"
                else:
                    scene.auto_topo.status_message = _to_friendly_error(err)
                scene.auto_topo.step_name = ""
                scene.auto_topo.is_processing = False
        if not is_cancel:
            logger.error(f"Pipeline error: {err}")
        return None  # Stop timer

    return 0.5  # Continue polling every 0.5s (reduced frequency for less UI lag)


def _handle_pipeline_done(result):
    """Handle pipeline completion on main thread."""
    global _obj_name

    for scene in bpy.data.scenes:
        if not hasattr(scene, 'auto_topo'):
            continue
        props = scene.auto_topo
        props.is_processing = False

        if result.success and result.output_mesh is not None:
            try:
                output_obj = mesh_data_to_blender(
                    result.output_mesh,
                    name=f"{_obj_name}_retopo",
                )
                _fill_result_info(props, result, output_obj)
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                # 面板只显示中文说明；完整栈写入日志，不暴露给用户。
                props.status_message = _to_friendly_error(f"创建网格失败: {e}")
                props.step_name = ""
                logger.error(f"创建输出网格失败:\n{tb}")
        elif result.success:
            props.status_message = "错误: 引擎完成但未生成输出网格"
            props.step_name = ""
            logger.error("Engine succeeded but produced no output mesh")
        else:
            props.status_message = _to_friendly_error(result.error_message)
            props.step_name = ""
            logger.error(f"拓扑重建失败: {result.error_message}")


def _fill_result_info(props, result, output_obj):
    """Update UI with result statistics and select the output object."""
    info_lines = [
        f"输出: {result.output_vert_count} 顶点 / {result.output_face_count} 面",
        f"四边面: {getattr(result, 'output_quad_count', 0)} / "
        f"三角面: {getattr(result, 'triangle_ratio', 0.0) * 100:.1f}%",
        f"耗时: {result.time_total:.2f} 秒",
        f"剪影误差: {getattr(result, 'silhouette_error', 0.0):.4f}",
        f"分片数: {getattr(result, 'patch_count', 1)}",
    ]
    props.last_result_info = '\n'.join(info_lines)
    props.status_message = "完成!"
    props.progress = 100.0
    props.step_name = ""

    # Select the new object
    bpy.ops.object.select_all(action='DESELECT')
    output_obj.select_set(True)
    bpy.context.view_layer.objects.active = output_obj

    logger.info(
        f"拓扑重建完成: {result.output_face_count} 面 "
        f"({result.time_total:.2f}秒)"
    )


class AUTOTOPO_OT_Retopologize(Operator):
    """在选中的网格上运行自动拓扑重建。"""

    bl_idname = "autotopo.retopologize"
    bl_label = "执行拓扑重建"
    bl_description = "对当前活动网格对象执行自动拓扑重建"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None
            and context.active_object.type == 'MESH'
            and not context.scene.auto_topo.is_processing
        )

    def execute(self, context):
        global _progress_step, _progress_pct, _pipeline_result, _pipeline_error
        global _input_mesh, _obj_name, _progress_last_raw, _progress_repeat

        # Defense check: ensure a mesh object is selected
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "请先选择一个网格对象")
            return {'CANCELLED'}

        props = context.scene.auto_topo
        engine_id = props.engine

        engine_cls = get_engine(engine_id)
        if engine_cls is None:
            self.report({'ERROR'}, f"未知引擎 '{engine_id}'")
            props.is_processing = False
            props.status_message = _to_friendly_error(f"未知引擎 '{engine_id}'")
            return {'CANCELLED'}

        # Reset progress state (including display-layer smoothing)
        with _progress_lock:
            _progress_step = ""
            _progress_pct = 0.0
            _progress_last_raw = -1.0
            _progress_repeat = 0
        _pipeline_result = None
        _pipeline_error = ""
        _obj_name = obj.name

        # ── Build the engine settings dict (registry-driven) ──
        settings = {}
        for spec in engine_cls.settings:
            settings[spec.key] = getattr(props, spec.key, spec.default)
        # Shared sharp-angle control (interior-dihedral convention).
        settings["sharp_angle_threshold"] = props.sharp_angle_threshold
        # Optional manual executable override for CLI engines.
        exe_path = _resolve_exe_path(engine_id, context)
        if exe_path:
            settings["exe_path"] = exe_path

        # ── Extract input mesh on the main thread ──
        try:
            _input_mesh = blender_to_mesh_data(obj)
        except Exception as e:
            import traceback
            logger.error(f"网格数据提取失败:\n{traceback.format_exc()}")
            self.report({'ERROR'}, _to_friendly_error(f"网格数据提取失败: {e}"))
            return {'CANCELLED'}

        if not _input_mesh.validate():
            self.report({'ERROR'}, _to_friendly_error("无效的网格数据"))
            return {'CANCELLED'}

        # Mark processing
        props.is_processing = True
        props.progress = 0.0
        props.step_name = "启动中..."
        props.status_message = "正在处理..."

        thread = threading.Thread(
            target=_run_engine_thread,
            args=(engine_cls, _input_mesh, props.target_face_count, settings),
            daemon=True,
        )
        thread.start()

        # Register non-blocking timer (does NOT block UI interaction)
        bpy.app.timers.register(_poll_timer, first_interval=0.1)

        self.report({'INFO'}, "拓扑重建已启动，可在后台继续操作...")
        return {'FINISHED'}


def _run_engine_thread(engine_cls, input_mesh, target_face_count, settings):
    """Engine execution in background thread (engine-agnostic)."""
    global _pipeline_result, _pipeline_error, _cancel_requested
    try:
        if _cancel_requested:
            _pipeline_error = "用户取消"
            _cancel_requested = False
            return
        result = engine_cls.run(
            input_mesh,
            target_face_count=target_face_count,
            settings=settings,
            progress_callback=_progress_callback,
            cancel_check=lambda: _cancel_requested,
        )
        if not result.success and result.error_message == "用户取消":
            _pipeline_error = "用户取消"
        else:
            _pipeline_result = result
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        _pipeline_error = f"{type(e).__name__}: {e}"
        logger.error(f"Engine thread error:\n{tb}")
    finally:
        _cancel_requested = False
        time.sleep(0.05)


class AUTOTOPO_OT_Cancel(Operator):
    """取消正在进行的拓扑重建。"""

    bl_idname = "autotopo.cancel"
    bl_label = "取消拓扑重建"
    bl_description = "取消正在进行的拓扑重建"

    def execute(self, context):
        global _cancel_requested
        _cancel_requested = True
        context.scene.auto_topo.status_message = "正在取消（当前阶段结束后生效）..."
        self.report({'WARNING'}, "已请求取消拓扑重建")
        return {'FINISHED'}


class AUTOTOPO_OT_SetFaceCount(Operator):
    """快捷设置目标面数。"""

    bl_idname = "autotopo.set_face_count"
    bl_label = "设置面数"
    bl_description = "快捷设置目标面数"

    count: IntProperty(default=2000)

    def execute(self, context):
        context.scene.auto_topo.target_face_count = self.count
        return {'FINISHED'}
