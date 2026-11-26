"""Regression guard for issue #8: legacy ``use_auto_smooth`` must be gated.

Blender 4.1 removed ``Mesh.use_auto_smooth``. Assigning it unconditionally
crashes every retopologize result write. CI runs against Blender 3.4, where
the attribute still exists, so a behavioural test alone cannot catch a
regression there. This test checks the source shape directly and fails on any
version if the guard is removed.

The behavioural counterpart is ``test/test_mesh_io_normals.py``, which runs in
Blender 4.x background mode.
"""
import ast
import os
import pathlib
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Pytest resolves test modules under the Blender_AutoTopo package root, whose
# __init__ imports bpy. Every pure test in this suite imports _pkgload first
# so that package name is stubbed before collection.
import _pkgload  # noqa: E402

# load_module() installs the lightweight package stubs; logger.py needs only
# the stdlib, so this is safe outside Blender and prevents pytest from trying
# to import the real package __init__ (which imports bpy).
_pkgload.load_module("utils/logger.py")

_MESH_IO = pathlib.Path(__file__).resolve().parents[1] / "utils" / "mesh_io.py"


def _is_guarded_hasattr(node, ancestors):
    """True when an ancestor ``if`` tests hasattr(mesh, "use_auto_smooth")."""
    for parent in ancestors:
        if not isinstance(parent, ast.If):
            continue
        test = parent.test
        if (isinstance(test, ast.Call)
                and isinstance(test.func, ast.Name)
                and test.func.id == "hasattr"
                and len(test.args) == 2
                and isinstance(test.args[0], ast.Name)
                and test.args[0].id == "mesh"
                and isinstance(test.args[1], ast.Constant)
                and test.args[1].value == "use_auto_smooth"):
            return True
    return False


def test_use_auto_smooth_assignment_is_guarded():
    tree = ast.parse(_MESH_IO.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = node.targets
        if not any(isinstance(t, ast.Attribute) and t.attr == "use_auto_smooth"
                   for t in targets):
            continue
        # Re-walk to collect ancestor If nodes for this exact assignment.
        ancestors = []

        def visit(parent):
            for child in ast.iter_child_nodes(parent):
                if child is node:
                    return True
                ancestors.append(child)
                if visit(child):
                    return True
                ancestors.pop()
            return False

        visit(tree)
        if not _is_guarded_hasattr(node, ancestors):
            offenders.append(node.lineno)

    assert not offenders, (
        f"unguarded mesh.use_auto_smooth assignment at line(s) {offenders}; "
        "wrap in `if hasattr(mesh, \"use_auto_smooth\"):` (issue #8)"
    )
