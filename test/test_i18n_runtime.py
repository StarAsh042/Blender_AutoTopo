"""Runtime i18n test (Blender background).

Verifies:
1. The zh_CN catalog follows Blender's language setting.
2. The runtime helper ``t()`` translates and fills placeholders.
3. Registration is idempotent (enable -> disable -> enable).
4. Unregister restores the source string.

Run:
  blender --background --factory-startup --python-exit-code 1 \
      --python test/test_i18n_runtime.py

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

MODULE = "Blender_AutoTopo"


def _run():
    import bpy

    from Blender_AutoTopo.ui.i18n import (
        register_translations,
        t,
        unregister_translations,
    )

    prefs = bpy.context.preferences.view
    original = prefs.language
    try:
        register_translations(MODULE)

        prefs.language = 'en_US'
        assert t("Engine") == "Engine", t("Engine")
        assert t("Cancel") == "Cancel", t("Cancel")

        prefs.language = 'zh_CN'
        # Escape non-ASCII literals on purpose: Blender's ``--python``
        # reads this file with the system encoding on Windows, while
        # imported modules are decoded as UTF-8. Keeping this file pure
        # ASCII makes the assertion independent of that difference.
        assert t("Engine") == "\u7b97\u6cd5\u5f15\u64ce", t("Engine")
        assert t("Cancel") == "\u53d6\u6d88", t("Cancel")
        assert t("Step: {step}", step="Export") == "\u6b65\u9aa4: Export"

        # Re-enable path: registering again must replace, not raise.
        register_translations(MODULE)
        assert t("Engine") == "\u7b97\u6cd5\u5f15\u64ce"

        # Unregister restores the source string.
        unregister_translations(MODULE)
        prefs.language = 'en_US'
        assert t("Engine") == "Engine"

        # Double unregister is a no-op.
        unregister_translations(MODULE)

        # Full enable -> disable -> enable cycle (addon lifecycle).
        register_translations(MODULE)
        unregister_translations(MODULE)
        register_translations(MODULE)
        prefs.language = 'zh_CN'
        assert t("Engine") == "\u7b97\u6cd5\u5f15\u64ce"
        unregister_translations(MODULE)
    finally:
        prefs.language = original

    print("=== I18N RUNTIME TEST PASSED ===")


def test_i18n_runtime():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
