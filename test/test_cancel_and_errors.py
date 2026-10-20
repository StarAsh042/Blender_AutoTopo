"""Cancel-path and error-branch coverage for the AutoTopo operator layer.

These branches (audit finding #27) are never touched by the happy-path
integration/e2e tests:

(a) cancel after start -> ``is_processing`` False, status mentions 取消, no
    ``*_retopo`` output object;
(b) operator poll / execute with no MESH active object -> CANCELLED;
(c) engine unavailable / native library missing -> friendly Chinese error,
    no crash (engine level and operator-level mapping);
(d) empty engine output -> "未生成输出网格" / "未生成有效输出" branch;
(e) unregister while a run is in flight is refused safely (controlled
    RuntimeError, no half-teardown); after the run no poll timer is left.

Run directly:
  blender --background --python test/test_cancel_and_errors.py
Under pytest without Blender this module is skipped.
"""
import os
import sys
import time

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)
_PACKAGE_PARENT = os.path.dirname(_PROJECT_ROOT)
for _p in (_TEST_DIR, _PACKAGE_PARENT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BLENDER_TEST = True


def _make_cube(bpy):
    """Fresh subdivided cube, active in the view layer."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    obj = bpy.context.active_object
    sub = obj.modifiers.new("sub", 'SUBSURF')
    sub.levels = 3
    bpy.ops.object.modifier_apply(modifier=sub.name)
    return obj


def _pump_until_done(ops_mod, props, timeout=60.0):
    """Drive the poll timer manually (background mode has no event loop)."""
    deadline = time.time() + timeout
    while time.time() < deadline and props.is_processing:
        if ops_mod._poll_timer() is None:
            break
        time.sleep(0.05)


def _timer_registered(func):
    try:
        return bpy.app.timers.is_registered(func)
    except Exception:  # pragma: no cover - very old Blender
        return None


# ── (b) poll / execute with no mesh ──
def subtest_poll_without_mesh(bpy):
    from Blender_AutoTopo.ui.operators import AUTOTOPO_OT_Retopologize

    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    bpy.ops.object.empty_add()
    assert bpy.context.active_object is not None
    assert bpy.context.active_object.type != 'MESH'

    assert AUTOTOPO_OT_Retopologize.poll(bpy.context) is False, (
        "poll must reject a non-mesh active object"
    )
    # Blender refuses to invoke an operator whose poll() fails: the call
    # raises RuntimeError and no worker is started.
    raised = False
    try:
        bpy.ops.autotopo.retopologize()
    except RuntimeError:
        raised = True
    assert raised, "operator with no mesh must be refused by poll()"
    assert bpy.context.scene.auto_topo.is_processing is False
    print("(b) poll/execute without mesh -> refused OK")


# ── (c) error-message mapping + engine-level missing-lib graceful failure ──
def subtest_error_mapping(bpy):
    from Blender_AutoTopo.ui.operators import _to_friendly_error
    from Blender_AutoTopo.ui.i18n import t

    # The raw strings mirror engine-internal exceptions and stay Chinese
    # (they are not translated); the expected messages go through t() so
    # the assertions are language-independent.
    cases = [
        ("QuadWild 引擎库缺失：请将 lib_quadwild.dll 与 lib_quadpatches.dll 放入",
         t("QuadWild libraries are missing: make sure lib_quadwild.dll and "
           "lib_quadpatches.dll are in the addon's bin/quadwild directory, "
           "then restart Blender and try again.")),
        ("未找到 AutoRemesher。请下载 autoremesher 可执行文件",
         t("External executable not found: make sure the engine is bundled "
           "or set the correct executable path in the addon preferences, "
           "then try again.")),
        ("无效的网格数据",
         t("Invalid mesh data: make sure the selected object is a valid mesh "
           "(check it in Edit Mode and remove zero-area faces), then try "
           "again.")),
        ("未知引擎 'nope'",
         t("Unknown algorithm engine: select an engine again in the panel "
           "and retry.")),
        ("输出网格为空",
         t("The engine produced no valid output: try lowering the target "
           "face count, disabling adaptive density, or relaxing the "
           "tolerance, then retry.")),
        ("用户取消",
         t("Cancelled: the retopology job was aborted. Adjust the parameters "
           "and try again.")),
    ]
    for raw, expected in cases:
        msg = _to_friendly_error(raw)
        assert msg == expected, f"{raw!r} -> {msg!r} != {expected!r}"
    print("(c) friendly-error mapping OK")


def subtest_missing_lib_graceful(bpy):
    import unittest.mock as mock

    from Blender_AutoTopo.engines.base import get_engine
    from Blender_AutoTopo.ui.operators import _to_friendly_error
    from Blender_AutoTopo.utils.mesh_io import blender_to_mesh_data

    qw = get_engine("quadwild")
    mesh = blender_to_mesh_data(_make_cube(bpy))

    # Simulate the shipped native libraries being absent without touching
    # bin/ on disk.
    with mock.patch(
        "Blender_AutoTopo.engines.quadwild_engine.is_quadwild_available",
        return_value=False,
    ):
        res = qw.run(
            mesh, target_face_count=200, settings={},
            progress_callback=lambda s, p: None,
        )

    assert res.success is False, "missing lib must not report success"
    assert "库缺失" in res.error_message, res.error_message
    assert "QuadWild" in _to_friendly_error(res.error_message)
    print("(c) missing native lib -> graceful Chinese error OK")


# ── (d) empty / invalid engine output ──
def subtest_empty_output(bpy):
    from Blender_AutoTopo.engines.evaluation import RetopoResult
    from Blender_AutoTopo.ui import operators as ops_mod
    from Blender_AutoTopo.ui.i18n import t

    props = bpy.context.scene.auto_topo
    props.is_processing = True

    # success=True but no output mesh -> "engine finished without output"
    res = RetopoResult()
    res.success = True
    res.output_mesh = None
    ops_mod._handle_pipeline_done(res)
    assert props.status_message == t(
        "Error: the engine finished but produced no output mesh"), \
        props.status_message
    assert props.is_processing is False

    # engine reported an empty-output error -> friendly "未生成有效输出"
    props.is_processing = True
    res2 = RetopoResult()
    res2.success = False
    res2.error_message = "四边面过少"
    ops_mod._handle_pipeline_done(res2)
    assert props.status_message == t(
        "The engine produced no valid output: try lowering the target face "
        "count, disabling adaptive density, or relaxing the tolerance, then "
        "retry."), props.status_message
    print("(d) empty output branch OK")


# ── (a) cancel after start ──
def subtest_cancel(bpy):
    from Blender_AutoTopo.ui import operators as ops_mod
    from Blender_AutoTopo.ui.i18n import t

    props = bpy.context.scene.auto_topo
    _make_cube(bpy)
    props.engine = "quadwild"
    props.target_face_count = 4000

    # Pre-arm the cancel flag so the worker's first cancel_check trips
    # deterministically (no race with a fast engine).
    ops_mod._cancel_requested = True
    r = bpy.ops.autotopo.retopologize()
    assert r == {'FINISHED'}, f"op returned {r}"
    assert props.is_processing

    _pump_until_done(ops_mod, props)
    assert props.is_processing is False
    assert props.status_message == t("Cancelled"), props.status_message

    retopo = [o for o in bpy.data.objects if o.name.endswith("_retopo")]
    assert retopo == [], f"cancelled run left output: {[o.name for o in retopo]}"
    assert ops_mod._cancel_requested is False
    print("(a) cancel -> is_processing False, Cancelled status, no *_retopo OK")


# ── (e) unregister guard + no residual timer ──
def subtest_unregister_guard(bpy, mod):
    from Blender_AutoTopo.ui import operators as ops_mod

    props = bpy.context.scene.auto_topo

    # 1. Refuse while a run is flagged in flight (controlled, not a crash).
    props.is_processing = True
    refused = False
    try:
        mod.unregister()
    except RuntimeError as e:
        refused = True
        assert "运行" in str(e) or "取消" in str(e), str(e)
    assert refused, "unregister must refuse while is_processing"
    # No half-teardown: the addon is still fully registered.
    assert hasattr(bpy.context.scene, "auto_topo")

    # 2. Clean unregister succeeds. First drop the background-mode timer
    #    registration (a GUI event loop removes it when _poll_timer returns
    #    None; background mode has no event loop to do that).
    props.is_processing = False
    if _timer_registered(ops_mod._poll_timer):
        bpy.app.timers.unregister(ops_mod._poll_timer)
    mod.unregister()
    assert not hasattr(bpy.context.scene, "auto_topo")
    assert _timer_registered(ops_mod._poll_timer) is not True, (
        "poll timer left registered after unregister"
    )
    print("(e) unregister guard + no residual timer OK")


def _run():
    import importlib

    import bpy

    mod = importlib.import_module("Blender_AutoTopo")
    mod.register()
    print("=== cancel / error-branch test ===")
    try:
        subtest_poll_without_mesh(bpy)
        subtest_error_mapping(bpy)
        subtest_missing_lib_graceful(bpy)
        subtest_empty_output(bpy)
        subtest_cancel(bpy)
        subtest_unregister_guard(bpy, mod)
    finally:
        if hasattr(bpy.context.scene, "auto_topo"):
            try:
                mod.unregister()
            except Exception:
                pass
    print("=== CANCEL / ERROR-BRANCH TEST PASSED ===")


# ── pytest entry (skipped without bpy) ──
try:
    import pytest as _pytest
except Exception:  # pragma: no cover - Blender's bundled Python may lack pytest
    _pytest = None


if _pytest is not None:
    def test_cancel_and_errors():
        _pytest.importorskip("bpy", reason="requires Blender background mode")
        _run()


if __name__ == "__main__":
    _run()
