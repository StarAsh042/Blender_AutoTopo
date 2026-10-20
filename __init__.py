"""Blender AutoTopo - Automatic Retopology Plugin.

A Blender 3.4+ addon for automatic retopology with
silhouette preservation. Generates quad-dominant meshes
from high-poly source geometry.

Core Design Principle: Silhouette fidelity > quad purity.
"""

bl_info = {
    "name": "AutoTopo",
    "author": "AutoTopo Team",
    "version": (2, 0, 0),
    "blender": (3, 4, 0),
    "location": "View3D > Sidebar > AutoTopo",
    "description": "Automatic retopology with silhouette preservation",
    "category": "Mesh",
}

import bpy


def _migrate_sharp_angle(props):
    """Migrate sharp_angle_threshold to the current unit (idempotent).

    History of the stored value:
    - v1: normal-deviation degrees (flat=0, default 30)
    - v2: FloatProperty(subtype='ANGLE') — display bug only, stored
      values were still the v1 ones (min=10 rules out radian storage)
    - v3 (current): plain interior-dihedral degrees (flat=180),
      default 90

    Detection is value based: v1 values are < 100 and every converted
    result lands >= 90, so the rules never fire twice on the same
    value. Blender does not save a property equal to its default, so
    untouched v3 scenes stay absent here and simply show the default.
    """
    v = props.sharp_angle_threshold
    if 10.0 <= v < 100.0:
        # v1 stored normal-deviation degrees; the old default 30 maps
        # to the current default, other values convert semantically
        v = 90.0 if v == 30.0 else 180.0 - v
        props.sharp_angle_threshold = min(max(v, 10.0), 180.0)


@bpy.app.handlers.persistent
def _reset_runtime_state(dummy=None):
    """Clear runtime status so the sidebar always starts clean.

    Old plugin versions persisted their run results inside saved
    .blend files; without this reset the stale "完成!" block and
    progress bar would survive restarts and re-installs.

    Must stay registered across file loads, hence the persistent
    marker: Blender wipes non-persistent handlers whenever a file is
    opened — exactly the moment the stale state gets restored.
    """
    for scene in bpy.data.scenes:
        if hasattr(scene, 'auto_topo'):
            props = scene.auto_topo
            props.status_message = ""
            props.is_processing = False
            props.progress = 0.0
            props.step_name = ""
            props.last_result_info = ""
            _migrate_sharp_angle(props)


def register():
    """Register the AutoTopo plugin with Blender."""
    from .ui.i18n import register_translations
    register_translations(__name__)

    # Verify dependencies are available (installed in system Python)
    try:
        import numpy  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            f"AutoTopo: 缺少依赖库 numpy，请运行: pip install numpy"
        ) from e

    from .ui.properties import AutoTopoProperties
    from .ui.panels import AUTOTOPO_PT_MainPanel
    from .ui.operators import (
        AUTOTOPO_OT_Retopologize,
        AUTOTOPO_OT_Cancel,
        AUTOTOPO_OT_SetFaceCount,
    )
    from .ui.preferences import AUTOTOPO_Preferences

    bpy.utils.register_class(AUTOTOPO_Preferences)
    bpy.utils.register_class(AutoTopoProperties)
    bpy.types.Scene.auto_topo = bpy.props.PointerProperty(
        type=AutoTopoProperties,
    )

    # Clear stale runtime state immediately (covers enabling the addon
    # mid-session and background scripts) and whenever a file is
    # loaded (covers Blender startup: the file is read after
    # registration, restoring any persisted state).
    try:
        _reset_runtime_state()
    except Exception:
        pass
    if _reset_runtime_state not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_reset_runtime_state)

    bpy.utils.register_class(AUTOTOPO_OT_Retopologize)
    bpy.utils.register_class(AUTOTOPO_OT_Cancel)
    bpy.utils.register_class(AUTOTOPO_OT_SetFaceCount)

    bpy.utils.register_class(AUTOTOPO_PT_MainPanel)

    from .utils.logger import logger
    logger.info("AutoTopo plugin registered")


def unregister():
    """Unregister the AutoTopo plugin from Blender."""
    # Refuse to unregister while a remesh worker is still running:
    # dropping classes mid-run breaks the completion callback, and
    # releasing the QuadWild DLLs under a running thread would crash.
    for scene in bpy.data.scenes:
        auto_topo = getattr(scene, 'auto_topo', None)
        if auto_topo is not None and auto_topo.is_processing:
            raise RuntimeError(
                "AutoTopo: 重拓扑正在运行，请先取消或等待完成后再卸载插件"
            )

    from .ui.properties import AutoTopoProperties
    from .ui.panels import AUTOTOPO_PT_MainPanel
    from .ui.operators import (
        AUTOTOPO_OT_Retopologize,
        AUTOTOPO_OT_Cancel,
        AUTOTOPO_OT_SetFaceCount,
    )
    from .ui.preferences import AUTOTOPO_Preferences

    bpy.utils.unregister_class(AUTOTOPO_PT_MainPanel)

    if _reset_runtime_state in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_reset_runtime_state)

    bpy.utils.unregister_class(AUTOTOPO_OT_SetFaceCount)
    bpy.utils.unregister_class(AUTOTOPO_OT_Cancel)
    bpy.utils.unregister_class(AUTOTOPO_OT_Retopologize)

    del bpy.types.Scene.auto_topo
    bpy.utils.unregister_class(AutoTopoProperties)
    bpy.utils.unregister_class(AUTOTOPO_Preferences)

    # Release the native libraries (Windows file lock) so Blender's
    # "Remove" addon operator can delete the plugin folder within the
    # same session. Two independent handles: the QuadWild DLLs and the
    # optional C++ acceleration DLL.
    try:
        from .engines.quadwild_engine import release_native_libs
        release_native_libs()
    except Exception:
        pass

    try:
        from .utils import native as _native
        _native.release()
    except Exception:
        pass

    from .utils.logger import logger
    logger.info("AutoTopo plugin unregistered")

    from .ui.i18n import unregister_translations
    unregister_translations(__name__)


if __name__ == "__main__":
    register()
