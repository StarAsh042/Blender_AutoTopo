"""Engine-dispatch matrix test (Blender background).

Parametrized over the three registered remesh backends:

* ``autoremesher`` — subprocess (bundled ``autoremesher.exe``)
* ``quadriflow``   — subprocess (bundled ``quadriflow.exe``)
* ``quadwild``     — ctypes (``lib_quadwild.dll`` / ``lib_quadpatches.dll``)

Every engine is fed the *same* subdivided-cube input. When
``is_available()`` is True the run must succeed and yield a valid
quad-dominant mesh (success + faces > 0 + quad ratio >= 0.80 + silhouette
error < 0.10). When it is False the run must degrade gracefully: no raise,
``success`` False and a non-empty ``error_message``.

Run directly:
  blender --background --python test/test_engine_dispatch.py
Under pytest without Blender the parametrized cases are skipped.
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

# The three backends exercised by the matrix, in registration order.
ENGINE_IDS = ("autoremesher", "quadriflow", "quadwild")

# Quality floors for a quad-dominant remesh of a smooth subdivided cube.
# Measured on Blender 3.4.1 (target 800): autoremesher/quadriflow reach a
# 1.00 quad ratio, quadwild 0.94; silhouette error is ~0.02-0.03 for all
# three. The floors below leave headroom for a slower/older machine while
# still catching a real regression.
TARGET_FACES = 800
MIN_QUAD_RATIO = 0.80
MAX_SILHOUETTE_ERROR = 0.10


def _make_input(bpy):
    """Subdivided cube (386 verts / 768 tris) shared by every engine."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    obj = bpy.context.active_object
    sub = obj.modifiers.new("sub", 'SUBSURF')
    sub.levels = 3
    bpy.ops.object.modifier_apply(modifier=sub.name)
    return obj


def _settings_for(engine_cls):
    """Defaults for every declared setting + the shared sharp-angle key."""
    settings = {spec.key: spec.default for spec in engine_cls.settings}
    settings["sharp_angle_threshold"] = 90.0
    return settings


def run_engine_case(engine_id):
    """Run one backend on the shared input and assert its contract."""
    import bpy

    from Blender_AutoTopo.engines.base import get_engine
    from Blender_AutoTopo.utils.mesh_io import blender_to_mesh_data

    engine_cls = get_engine(engine_id)
    assert engine_cls is not None, f"{engine_id} not registered"

    mesh = blender_to_mesh_data(_make_input(bpy))
    available = engine_cls.is_available()
    result = engine_cls.run(
        mesh,
        target_face_count=TARGET_FACES,
        settings=_settings_for(engine_cls),
        progress_callback=lambda s, p: None,
    )

    print(
        f"[{engine_id}] available={available} success={result.success} "
        f"faces={result.output_face_count} quads={result.output_quad_count} "
        f"tri_ratio={getattr(result, 'triangle_ratio', 0.0):.3f} "
        f"sil={getattr(result, 'silhouette_error', None)} "
        f"time={result.time_total:.2f}s err={result.error_message[:80]!r}"
    )

    if available:
        assert result.success, f"{engine_id} failed: {result.error_message}"
        assert result.output_face_count > 0, f"{engine_id} produced no faces"
        quad_ratio = result.output_quad_count / max(result.output_face_count, 1)
        assert quad_ratio >= MIN_QUAD_RATIO, (
            f"{engine_id} quad ratio {quad_ratio:.2%} < {MIN_QUAD_RATIO:.0%}"
        )
        sil = getattr(result, "silhouette_error", 1.0)
        assert sil < MAX_SILHOUETTE_ERROR, (
            f"{engine_id} silhouette error {sil} >= {MAX_SILHOUETTE_ERROR}"
        )
    else:
        assert not result.success, (
            f"{engine_id} reports unavailable but run() returned success"
        )
        assert result.error_message, (
            f"{engine_id} unavailable but produced an empty error_message"
        )
    return result


def _run():
    """Direct ``--python`` entry point: register and sweep the matrix."""
    import importlib

    mod = importlib.import_module("Blender_AutoTopo")
    mod.register()
    print("=== engine dispatch matrix ===")
    try:
        from Blender_AutoTopo.engines.base import list_engines

        ids = [e.id for e in list_engines()]
        print("registered engines:", ids)
        assert "quadwild" in ids and "autoremesher" in ids and "quadriflow" in ids, (
            f"engine set incomplete: {ids}"
        )
        for engine_id in ENGINE_IDS:
            run_engine_case(engine_id)
    finally:
        mod.unregister()
    print("=== ENGINE DISPATCH MATRIX PASSED ===")


# ── pytest parametrization (skipped without bpy) ──
try:
    import pytest as _pytest
except Exception:  # pragma: no cover - Blender's bundled Python may lack pytest
    _pytest = None


if _pytest is not None:
    @_pytest.mark.parametrize("engine_id", ENGINE_IDS)
    def test_engine_dispatch_matrix(engine_id):
        _pytest.importorskip("bpy", reason="requires Blender background mode")
        import importlib

        mod = importlib.import_module("Blender_AutoTopo")
        mod.register()
        try:
            run_engine_case(engine_id)
        finally:
            mod.unregister()


if __name__ == "__main__":
    _run()
