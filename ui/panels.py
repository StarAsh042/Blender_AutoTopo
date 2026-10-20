"""Blender UI panels for AutoTopo.

The panel is engine-driven: it looks the selected engine up in the
registry and draws whatever :class:`SettingSpec` that engine declares —
plus the shared ``target_face_count`` and (when the engine opts in via
``shared_props``) ``sharp_angle_threshold``. No per-engine branching, so
adding an engine needs no panel changes.

All runtime text goes through :func:`ui.i18n.t`; ``bl_label`` and
``bl_category`` stay static because Blender translates them through the
``"*"`` context while drawing.
"""

import bpy
from bpy.types import Panel

from ..engines.base import get_engine
from .i18n import t


# Blender < 4.0 has no layout.progress(); fallback text bar width.
_PROGRESS_BAR_WIDTH = 20


def _draw_progress(layout, props):
    """Read-only progress display (the user cannot drag it).

    Blender 4.0+ provides ``layout.progress()``; 3.4 has no such API and
    falls back to a text bar. Neither path uses an editable
    ``box.prop()`` — the old implementation rendered a FloatProperty as
    a draggable slider.
    """
    factor = max(0.0, min(props.progress, 100.0)) / 100.0
    pct = props.progress

    progress_fn = getattr(layout, "progress", None)
    if callable(progress_fn):
        progress_fn(factor=factor, text=t("Progress {pct:.0f}%", pct=pct))
        return

    filled = int(round(factor * _PROGRESS_BAR_WIDTH))
    bar = "█" * filled + "░" * (_PROGRESS_BAR_WIDTH - filled)
    layout.label(text=t("Progress [{bar}] {pct:.0f}%", bar=bar, pct=pct))


class AUTOTOPO_PT_MainPanel(Panel):
    """AutoTopo main panel - 3D View sidebar."""

    bl_label = "AutoTopo"
    bl_idname = "AUTOTOPO_PT_MainPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "AutoTopo"

    def draw(self, context):
        layout = self.layout
        props = context.scene.auto_topo

        # === Engine selection ===
        box = layout.box()
        box.label(text=t("Algorithm Engine"), icon='PREFERENCES')
        box.prop(props, "engine", text="")

        engine_cls = get_engine(props.engine)
        if engine_cls is None:
            box = layout.box()
            box.label(text=t("Unknown engine. Select it again."), icon='ERROR')
            layout.separator()
            row = layout.row()
            row.scale_y = 2.0
            row.operator("autotopo.retopologize", icon='MESH_DATA')
            self._draw_status(layout, props)
            return

        if not engine_cls.is_available():
            box = layout.box()
            box.label(text=t("Engine unavailable"), icon='ERROR')
            box.label(text=t(engine_cls.unavailable_hint()))

        # === Shared face-count control ===
        box = layout.box()
        box.label(text=t("Face Count"), icon='MESH_DATA')
        col = box.column(align=True)
        col.prop(props, "target_face_count")

        # Quick face-count buttons
        row = box.row(align=True)
        op = row.operator("autotopo.set_face_count", text=t("Low"))
        op.count = 500
        op = row.operator("autotopo.set_face_count", text=t("Medium"))
        op.count = 2000
        op = row.operator("autotopo.set_face_count", text=t("High"))
        op.count = 8000

        # === Shared feature parameters (engine opt-in) ===
        shared = [k for k in getattr(engine_cls, "shared_props", ())
                  if hasattr(props, k)]
        if shared:
            box = layout.box()
            box.label(text=t("Feature Preservation"), icon='MOD_DECIM')
            for key in shared:
                box.prop(props, key)

        # === Engine-specific settings (basic + collapsible advanced) ===
        self._draw_engine_settings(layout, props, engine_cls)

        # === Run button ===
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
            box.label(text=t("Parameters"), icon='MODIFIER')
            col = box.column(align=True)
            for spec in basic:
                if spec.show_if and not spec.show_if(props):
                    continue
                col.prop(props, spec.key)

        if advanced:
            box = layout.box()
            box.label(text=t("Advanced"), icon='SETTINGS')
            col = box.column(align=True)
            for spec in advanced:
                if spec.show_if and not spec.show_if(props):
                    continue
                col.prop(props, spec.key)

    @staticmethod
    def _draw_status(layout, props):
        """Progress / status / result area."""
        # === Progress ===
        if props.is_processing:
            box = layout.box()
            box.label(text=t("Step: {step}", step=props.step_name), icon='TIME')
            # Read-only progress: 4.0+ uses layout.progress(), 3.4 falls
            # back to a text bar.
            _draw_progress(box, props)
            row = box.row()
            row.scale_y = 1.5
            row.operator("autotopo.cancel", icon='PANEL_CLOSE', text=t("Cancel"))

        # === Status ===
        if props.status_message:
            box = layout.box()
            box.label(text=props.status_message, icon='INFO')

        if props.last_result_info:
            box = layout.box()
            for line in props.last_result_info.split('\n'):
                if line.strip():
                    box.label(text=line)
