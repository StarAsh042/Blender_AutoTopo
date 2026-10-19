"""Blender UI panels for AutoTopo.

The panel is engine-driven: it looks the selected engine up in the
registry and draws whatever :class:`SettingSpec` that engine declares —
plus the shared ``target_face_count`` and (when the engine opts in via
``shared_props``) ``sharp_angle_threshold``. No per-engine branching, so
adding an engine needs no panel changes.
"""

import bpy
from bpy.types import Panel

from ..engines.base import get_engine


# Blender < 4.0 没有 layout.progress()，回退用的文本进度条宽度
_PROGRESS_BAR_WIDTH = 20


def _draw_progress(layout, props):
    """只读进度显示（用户无法拖动）。

    Blender 4.0+ 提供 layout.progress()；3.4 没有该 API，退回纯展示的
    文本进度条。两条路径都不使用可编辑的 box.prop()——旧实现会把
    FloatProperty 渲染成可拖动的滑块。
    """
    factor = max(0.0, min(props.progress, 100.0)) / 100.0
    pct = props.progress

    progress_fn = getattr(layout, "progress", None)
    if callable(progress_fn):
        progress_fn(factor=factor, text=f"进度 {pct:.0f}%")
        return

    filled = int(round(factor * _PROGRESS_BAR_WIDTH))
    bar = "█" * filled + "░" * (_PROGRESS_BAR_WIDTH - filled)
    layout.label(text=f"进度 [{bar}] {pct:.0f}%")


class AUTOTOPO_PT_MainPanel(Panel):
    """AutoTopo 主面板 - 3D 视图侧边栏。"""

    bl_label = "自动拓扑"
    bl_idname = "AUTOTOPO_PT_MainPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "自动拓扑"

    def draw(self, context):
        layout = self.layout
        props = context.scene.auto_topo

        # === 引擎选择 ===
        box = layout.box()
        box.label(text="算法引擎", icon='PREFERENCES')
        box.prop(props, "engine", text="")

        engine_cls = get_engine(props.engine)
        if engine_cls is None:
            box = layout.box()
            box.label(text="未知引擎，请重新选择", icon='ERROR')
            layout.separator()
            row = layout.row()
            row.scale_y = 2.0
            row.operator("autotopo.retopologize", icon='MESH_DATA')
            self._draw_status(layout, props)
            return

        if not engine_cls.is_available():
            box = layout.box()
            box.label(text="引擎暂不可用", icon='ERROR')
            box.label(text=engine_cls.unavailable_hint())

        # === 共享面数控制 ===
        box = layout.box()
        box.label(text="面数控制", icon='MESH_DATA')
        col = box.column(align=True)
        col.prop(props, "target_face_count")

        # 快捷面数按钮
        row = box.row(align=True)
        op = row.operator("autotopo.set_face_count", text="低")
        op.count = 500
        op = row.operator("autotopo.set_face_count", text="中")
        op.count = 2000
        op = row.operator("autotopo.set_face_count", text="高")
        op.count = 8000

        # === 共享特征参数（引擎自选） ===
        shared = [k for k in getattr(engine_cls, "shared_props", ())
                  if hasattr(props, k)]
        if shared:
            box = layout.box()
            box.label(text="特征保留", icon='MOD_DECIM')
            for key in shared:
                box.prop(props, key)

        # === 引擎专属参数（基础 + 高级折叠） ===
        self._draw_engine_settings(layout, props, engine_cls)

        # === 执行按钮 ===
        layout.separator()
        row = layout.row()
        row.scale_y = 2.0
        row.operator("autotopo.retopologize", icon='MESH_DATA')

        self._draw_status(layout, props)

    @staticmethod
    def _draw_engine_settings(layout, props, engine_cls):
        specs = list(engine_cls.settings)
        basic = [s for s in specs if not s.advanced]
        advanced = [s for s in specs if s.advanced]

        if basic:
            box = layout.box()
            box.label(text="参数", icon='MODIFIER')
            col = box.column(align=True)
            for spec in basic:
                if spec.show_if and not spec.show_if(props):
                    continue
                col.prop(props, spec.key)

        if advanced:
            box = layout.box()
            box.label(text="高级参数", icon='SETTINGS')
            col = box.column(align=True)
            for spec in advanced:
                if spec.show_if and not spec.show_if(props):
                    continue
                col.prop(props, spec.key)

    @staticmethod
    def _draw_status(layout, props):
        """进度/状态/结果信息区域。"""
        # === 进度显示 ===
        if props.is_processing:
            box = layout.box()
            box.label(text=f"步骤: {props.step_name}", icon='TIME')
            # 只读进度：4.0+ 用 layout.progress()，3.4 退回文本进度条。
            _draw_progress(box, props)
            row = box.row()
            row.scale_y = 1.5
            row.operator("autotopo.cancel", icon='PANEL_CLOSE', text="取消")

        # === 状态 ===
        if props.status_message:
            box = layout.box()
            box.label(text=props.status_message, icon='INFO')

        if props.last_result_info:
            box = layout.box()
            for line in props.last_result_info.split('\n'):
                if line.strip():
                    box.label(text=line)
