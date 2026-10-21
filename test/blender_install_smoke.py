"""Install the packaged addon zip into Blender and verify its lifecycle.

This is the closest CI can get to what a user does:
  1. ``bpy.ops.preferences.addon_install(filepath=<zip>)``
  2. ``bpy.ops.preferences.addon_enable(module="Blender_AutoTopo")``
  3. verify the registration surface exists
  4. disable -> verify nothing is left behind
  5. enable again -> verify the addon can be enabled a second time
     (register/unregister symmetry in practice)

Run:
  AUTOTOPO_ZIP=dist/Blender_AutoTopo-2.1.0.zip \\
    blender --background --factory-startup --python-exit-code 1 \\
    --python test/blender_install_smoke.py

``BLENDER_USER_CONFIG`` / ``BLENDER_USER_SCRIPTS`` should point at a
throw-away directory so the install never touches a real user profile.

Under pytest without Blender this module is skipped (see conftest.py /
``pytest.importorskip``).
"""
import os

BLENDER_TEST = True

MODULE = "Blender_AutoTopo"


def _run():
    import bpy

    zip_path = os.environ.get("AUTOTOPO_ZIP", "")
    assert zip_path, "AUTOTOPO_ZIP is not set"
    assert os.path.isfile(zip_path), f"addon zip not found: {zip_path}"

    # ── 1. Install exactly like a user would ──
    result = bpy.ops.preferences.addon_install(filepath=zip_path)
    assert result == {'FINISHED'}, f"addon_install returned {result}"
    print(f"=== installed {os.path.basename(zip_path)} ===")

    # ── 2. Enable and verify the registration surface ──
    result = bpy.ops.preferences.addon_enable(module=MODULE)
    assert result == {'FINISHED'}, f"addon_enable returned {result}"

    from Blender_AutoTopo.ui.operators import (
        AUTOTOPO_OT_Cancel,
        AUTOTOPO_OT_Retopologize,
        AUTOTOPO_OT_SetFaceCount,
    )
    from Blender_AutoTopo.ui.panels import AUTOTOPO_PT_MainPanel
    from Blender_AutoTopo.ui.preferences import AUTOTOPO_Preferences
    from Blender_AutoTopo.ui.properties import AutoTopoProperties

    for cls in (
        AUTOTOPO_OT_Retopologize,
        AUTOTOPO_OT_Cancel,
        AUTOTOPO_OT_SetFaceCount,
        AUTOTOPO_PT_MainPanel,
        AUTOTOPO_Preferences,
        AutoTopoProperties,
    ):
        assert cls.is_registered, f"{cls.__name__} is not registered"
    assert hasattr(bpy.context.scene, "auto_topo"), "Scene.auto_topo missing"
    assert bpy.context.scene.auto_topo.engine == "autoremesher"
    print("=== enabled; registration surface present ===")

    # ── 3. Disable: the addon must leave nothing behind ──
    result = bpy.ops.preferences.addon_disable(module=MODULE)
    assert result == {'FINISHED'}, f"addon_disable returned {result}"
    for cls in (
        AUTOTOPO_OT_Retopologize,
        AUTOTOPO_OT_Cancel,
        AUTOTOPO_OT_SetFaceCount,
        AUTOTOPO_PT_MainPanel,
        AUTOTOPO_Preferences,
        AutoTopoProperties,
    ):
        assert not cls.is_registered, f"{cls.__name__} left registered after disable"
    assert not hasattr(bpy.context.scene, "auto_topo"), \
        "Scene.auto_topo left behind after disable"
    print("=== disabled; no leftovers ===")

    # ── 4. Enable again: proves register/unregister symmetry ──
    result = bpy.ops.preferences.addon_enable(module=MODULE)
    assert result == {'FINISHED'}, f"second addon_enable returned {result}"
    assert AUTOTOPO_PT_MainPanel.is_registered
    bpy.ops.preferences.addon_disable(module=MODULE)
    print("=== BLENDER INSTALL SMOKE PASSED ===")


def test_blender_install_smoke():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
