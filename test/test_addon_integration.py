"""Full addon integration test in Blender background mode.

Tests:
1. Addon register (properties/panels/operators)
2. AI placeholder rejection
3. QuadWild engine via operator dispatch (thread + manual poll)

Run:
  blender --background --python test/test_addon_integration.py

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
    import time

    try:
        import scipy  # noqa: F401
    except ImportError:
        sys.path.append(r"C:\Program Files (x86)\Python\lib\site-packages")

    import bpy
    import importlib

    # ── 1. Register the addon ──
    mod = importlib.import_module('Blender_AutoTopo')
    mod.register()
    print("=== addon registered ===")
    assert hasattr(bpy.types.Scene, 'auto_topo')

    props = bpy.context.scene.auto_topo
    assert props.engine == 'autoremesher', f"default engine: {props.engine}"

    # ── Helper: fresh subdivided cube ──
    def make_test_cube():
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete()
        bpy.ops.mesh.primitive_cube_add(size=2.0)
        obj = bpy.context.active_object
        sub = obj.modifiers.new("sub", 'SUBSURF')
        sub.levels = 3
        bpy.ops.object.modifier_apply(modifier=sub.name)
        return obj

    # ── 2. engine registry validation ──
    from Blender_AutoTopo.engines.base import get_engine
    assert get_engine('does_not_exist') is None, "unknown engine lookup"
    for eid in ('quadwild', 'autoremesher', 'quadriflow'):
        assert get_engine(eid) is not None, f"{eid} not registered"
    print("=== engine registry validation OK ===")

    # ── 3. QuadWild path (thread + manual polling) ──
    import Blender_AutoTopo.ui.operators as ops_mod

    obj = make_test_cube()
    props.engine = 'quadwild'
    props.target_face_count = 500
    r = bpy.ops.autotopo.retopologize()
    assert r == {'FINISHED'}, f"quadwild op returned {r}"
    assert props.is_processing

    # Background mode has no event loop; pump the poll timer manually
    deadline = time.time() + 300
    while time.time() < deadline and props.is_processing:
        ret = ops_mod._poll_timer()
        if ret is None:
            break
        time.sleep(0.5)

    assert not props.is_processing, "quadwild did not finish in time"
    retopo_objs = [o for o in bpy.data.objects if o.name.endswith('_retopo')]
    assert len(retopo_objs) == 1, f"expected 1 retopo obj, got {len(retopo_objs)}"
    n_quads = sum(1 for p in retopo_objs[0].data.polygons
                  if len(p.vertices) == 4)
    n_total = len(retopo_objs[0].data.polygons)
    print(f"=== QuadWild OK: {n_total} faces, {n_quads} quads "
          f"({n_quads / max(n_total, 1) * 100:.1f}%) ===")
    print("result info:")
    print(props.last_result_info)
    assert props.status_message == "完成!", f"status: {props.status_message}"

    mod.unregister()
    print("=== ALL INTEGRATION TESTS PASSED ===")


def test_addon_integration():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
