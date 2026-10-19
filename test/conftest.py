"""Pytest bootstrap for the Blender AutoTopo test suite.

Why this file lives in ``test/`` and not at the project root: the
project root *is* the ``Blender_AutoTopo`` package (it has an
``__init__.py`` that does ``import bpy`` at module scope). A
``conftest.py`` at the root would be imported by pytest as
``Blender_AutoTopo.conftest``, which executes that ``__init__`` and
crashes outside Blender. ``test/`` has no ``__init__.py``, so this
conftest is imported as a plain top-level module.

Responsibilities:

* Inject the **parent** of the package directory into ``sys.path`` so
  ``import Blender_AutoTopo`` resolves (the addon is the package).
* Tag ``BLENDER_TEST`` / ``SLOW_TEST`` modules with the matching markers
  and skip the bpy-dependent ones when ``bpy`` is unavailable.
"""

import importlib.util
import os
import sys
import warnings

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))            # .../Blender_AutoTopo/test
_PACKAGE_PARENT = os.path.dirname(os.path.dirname(_HERE))     # .../BlenderPlugin

if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)


def _bpy_available() -> bool:
    """True only when a real ``bpy`` module can be imported."""
    try:
        return importlib.util.find_spec("bpy") is not None
    except (ImportError, ValueError):
        return False


_BLENDER_SKIP_REASON = (
    "requires Blender background mode (bpy); run with: "
    "blender --background --python <test file>"
)


def pytest_collection_modifyitems(config, items):
    has_bpy = _bpy_available()
    for item in items:
        module = getattr(item, "module", None)
        if module is None:
            continue
        if getattr(module, "BLENDER_TEST", False):
            item.add_marker(pytest.mark.blender)
            if not has_bpy:
                item.add_marker(pytest.mark.skip(reason=_BLENDER_SKIP_REASON))
        if getattr(module, "SLOW_TEST", False):
            item.add_marker(pytest.mark.slow)


# numpy major/minor line the runtime baseline (Blender 3.4.1) ships.
# ``requirements-dev.txt`` pins ``numpy==2.2.6`` for CI reproducibility.
# A dev venv may carry a newer line, so a mismatch is reported as a
# *warning* only — never a hard failure.
_EXPECTED_NUMPY = (2, 2)


@pytest.fixture(scope="session", autouse=True)
def _warn_on_numpy_version_mismatch():
    try:
        import numpy
    except ImportError:  # pragma: no cover - numpy is a hard dev dep
        yield
        return

    parts = []
    for piece in numpy.__version__.split(".")[:2]:
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else -1)
    if tuple(parts) != _EXPECTED_NUMPY:
        warnings.warn(
            f"numpy {numpy.__version__} != runtime baseline "
            f"{_EXPECTED_NUMPY[0]}.{_EXPECTED_NUMPY[1]}.x "
            "(Blender 3.4.1 bundles 2.2.6); engine output may differ. "
            "This is a warning, not a failure.",
            UserWarning,
            stacklevel=1,
        )
    yield
