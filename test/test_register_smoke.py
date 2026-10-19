"""Register/UI smoke test (Blender background).

Checks:
1. Addon registers without legacy/analysis classes.
2. Sharp angle default is 90 (plain degrees, no radian reinterpretation).
3. Runtime info is NOT persisted into the .blend (SKIP_SAVE).

Run:
  blender --background --python test/test_register_smoke.py

Under pytest without Blender this module is skipped (see conftest.py /
``pytest.importorskip``).
"""
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)
_PACKAGE_PARENT = os.path.dirname(_PROJECT_ROOT)
for _p in (_TEST_DIR, _PACKAGE_PARENT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BLENDER_TEST = True


def _run():
    import tempfile

    try:
        import scipy  # noqa: F401
    except ImportError:
        sys.path.append(r"C:\Program Files (x86)\Python\lib\site-packages")

    import bpy
    import Blender_AutoTopo

    print("=== register/UI smoke test ===")
    Blender_AutoTopo.register()

    props = bpy.context.scene.auto_topo

    # 1. sharp angle: plain degrees, default 90
    assert abs(props.sharp_angle_threshold - 90.0) < 1e-3, \
        f"sharp angle default wrong: {props.sharp_angle_threshold}"
    print("sharp angle default:", props.sharp_angle_threshold)

    # 2. engine enum: all registered engines present, no AI placeholders
    items = [i.identifier
             for i in type(props).bl_rna.properties['engine'].enum_items]
    assert 'legacy' not in items, f"legacy still present: {items}"
    assert 'cloud_ai' not in items, f"cloud_ai still present: {items}"
    assert 'local_ai' not in items, f"local_ai still present: {items}"
    for e in ('quadwild', 'autoremesher', 'quadriflow'):
        assert e in items, f"{e} missing from engine enum: {items}"
    assert props.engine == 'autoremesher', f"default engine: {props.engine}"
    print("engines:", items)

    # 3. analysis/advanced classes gone
    assert not hasattr(bpy.types, 'AUTOTOPO_PT_AnalysisPanel')
    assert not hasattr(bpy.types, 'AUTOTOPO_PT_AdvancedPanel')
    assert not hasattr(bpy.types, 'AUTOTOPO_OT_AnalyzeQuality')
    assert not hasattr(bpy.types, 'AUTOTOPO_OT_DetectSpirals')
    print("analysis/legacy UI classes removed")

    # 4. stale runtime info saved inside a .blend must be cleared on
    # registration (deferred timer). Simulate a restart: save with stale
    # state, reload, re-register, wait for the reset timer.
    props.last_result_info = "输出: 1934 顶点 / 1932 面"
    props.status_message = "完成!"
    props.sharp_angle_threshold = 30.0  # old-convention value
    tmp = os.path.join(tempfile.gettempdir(), "_autotopo_persist_test.blend")
    bpy.ops.wm.save_as_mainfile(filepath=tmp)
    Blender_AutoTopo.unregister()
    bpy.ops.wm.open_mainfile(filepath=tmp)
    Blender_AutoTopo.register()

    props2 = bpy.context.scene.auto_topo
    assert props2.last_result_info == "", \
        f"runtime info survived: {props2.last_result_info!r}"
    assert props2.status_message == "", \
        f"status survived: {props2.status_message!r}"
    assert abs(props2.sharp_angle_threshold - 90.0) < 1e-3, \
        f"angle not migrated: {props2.sharp_angle_threshold}"
    print("reset-on-register verified: stale info cleared, angle migrated")

    # 5. migration: v1 normal-deviation value converts semantically
    props2.sharp_angle_threshold = 45.0
    Blender_AutoTopo._reset_runtime_state()
    assert abs(props2.sharp_angle_threshold - 135.0) < 1e-3, \
        f"v1 value not migrated: {props2.sharp_angle_threshold}"

    # 6. migration is idempotent: converted values (>= 90) and current-
    # convention values (>= 100) never re-fire
    Blender_AutoTopo._reset_runtime_state()
    assert abs(props2.sharp_angle_threshold - 135.0) < 1e-3, \
        f"migration fired twice: {props2.sharp_angle_threshold}"
    props2.sharp_angle_threshold = 120.0
    Blender_AutoTopo._reset_runtime_state()
    assert abs(props2.sharp_angle_threshold - 120.0) < 1e-3, \
        f"current-convention value altered: {props2.sharp_angle_threshold}"
    print("angle migration: v1 handled, idempotent")

    # 7. restart simulation WITH the addon staying registered: the
    # load_post handler must survive file loads (persistent marker) and
    # clear the stale state a saved file restores. This is the path the
    # user actually hits when reopening Blender with a project file.
    props2.last_result_info = "输出: 1869 顶点 / 2017 面"
    props2.status_message = "完成!"
    tmp2 = os.path.join(tempfile.gettempdir(), "_autotopo_restart_test.blend")
    bpy.ops.wm.save_as_mainfile(filepath=tmp2)
    bpy.ops.wm.open_mainfile(filepath=tmp2)

    props3 = bpy.context.scene.auto_topo
    assert props3.last_result_info == "", \
        f"runtime info survived restart: {props3.last_result_info!r}"
    assert props3.status_message == "", \
        f"status survived restart: {props3.status_message!r}"
    assert props3.is_processing is False
    print("restart with addon registered: load_post handler cleared state")
    os.remove(tmp2)

    os.remove(tmp)
    Blender_AutoTopo.unregister()
    print("=== REGISTER SMOKE TEST PASSED ===")


def test_register_smoke():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
