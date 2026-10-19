"""Load ``Blender_AutoTopo`` submodules without executing the package
``__init__`` (which imports ``bpy`` and is therefore unusable outside
Blender).

The real package directory is ``Blender_AutoTopo/`` (this file lives in
``Blender_AutoTopo/test/``). Its ``__init__.py`` does ``import bpy`` at
module scope, so a plain ``import Blender_AutoTopo.engines.obj_io`` fails
under system Python even though ``obj_io`` itself only needs numpy.

``load_module`` registers lightweight package placeholders in
``sys.modules`` and loads an individual submodule straight from its file,
so relative imports (``from ..utils.logger import logger``) still resolve.
"""

import importlib.util
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_HERE)            # .../Blender_AutoTopo
PACKAGE_PARENT = os.path.dirname(PROJECT_ROOT)   # .../BlenderPlugin
PKG = "Blender_AutoTopo"

_SUBPACKAGES = ("engines", "utils", "ui")


def _stub_package(dotted_name: str, path: str) -> types.ModuleType:
    mod = sys.modules.get(dotted_name)
    if mod is None:
        mod = types.ModuleType(dotted_name)
        mod.__package__ = dotted_name
        sys.modules[dotted_name] = mod
    mod.__path__ = [path]
    return mod


def _ensure_packages() -> None:
    _stub_package(PKG, PROJECT_ROOT)
    for sub in _SUBPACKAGES:
        _stub_package(f"{PKG}.{sub}", os.path.join(PROJECT_ROOT, sub))


def load_module(rel_path: str):
    """Import ``Blender_AutoTopo/<rel_path>`` as a real submodule.

    ``rel_path`` uses ``/`` separators, e.g. ``"engines/obj_io.py"`` or
    ``"utils/logger.py"``.
    """
    _ensure_packages()
    dotted = f"{PKG}." + rel_path[:-3].replace("/", ".")
    if dotted in sys.modules:
        return sys.modules[dotted]

    file_path = os.path.join(PROJECT_ROOT, *rel_path.split("/"))
    spec = importlib.util.spec_from_file_location(dotted, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {rel_path!r} from {file_path!r}")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    parent_name, child_name = dotted.rsplit(".", 1)
    parent = sys.modules.get(parent_name)
    if parent is not None:
        setattr(parent, child_name, mod)
    spec.loader.exec_module(mod)
    return mod
