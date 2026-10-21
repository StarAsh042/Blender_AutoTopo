"""Packaging-artifact validation for the Blender addon zip.

Validates the archive produced by ``scripts/package_addon.py``:

* every entry is rooted at the top-level ``Blender_AutoTopo/`` directory;
* required package files/dirs are present;
* dev/CI artifacts are excluded (``deliverables/``, ``.workbuddy-ai/``,
  ``__pycache__/``, ``dist/``, and stray ``.zip`` bundles under ``bin/``);
* the native QuadWild libraries are present;
* the archive is intact (``ZipFile.testzip``) and below a size budget.

Pure pytest — no ``bpy`` needed. If the zip has not been generated yet (or is
older than the sources) the module skips with a clear message, because the
release manager rebuilds it once all contributors have finished.
"""
import os
import sys
import zipfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Stub the addon package in ``sys.modules`` so pytest's rootdir-package
# import never executes its bpy-dependent ``__init__.py`` (the same guard
# the other pure-Python tests get via ``_pkgload``). Without it, running
# this file alone fails at setup with ``ModuleNotFoundError: bpy``.
import _pkgload  # noqa: E402

_pkgload._ensure_packages()

_PROJECT_ROOT = os.path.dirname(_HERE)
ZIP_PATH = os.path.join(_PROJECT_ROOT, "dist", "Blender_AutoTopo-2.1.0.zip")
PREFIX = "Blender_AutoTopo/"

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024  # 50 MB

REQUIRED_ENTRIES = (
    "Blender_AutoTopo/__init__.py",
    "Blender_AutoTopo/engines/__init__.py",
    "Blender_AutoTopo/ui/operators.py",
    "Blender_AutoTopo/utils/mesh_io.py",
    "Blender_AutoTopo/bin/quadwild/lib_quadwild.dll",
    "Blender_AutoTopo/bin/quadwild/lib_quadpatches.dll",
)

EXCLUDED_SUBSTRINGS = (
    "deliverables/",
    ".workbuddy-ai/",
    "__pycache__/",
    "/dist/",
)

# Directory names the packager excludes (mirror scripts/package_addon.py)
# so the staleness walk never treats a build/CI cache as a source file.
_WALK_EXCLUDES = {
    ".workbuddy-ai",
    "deliverables",
    "dist",
    ".pytest_cache",
    "__pycache__",
    ".git",
    "node_modules",
}


def _skip_if_stale():
    """Skip with a clear message when the artifact is missing or outdated."""
    if not os.path.exists(ZIP_PATH):
        pytest.skip(
            "打包产物尚未生成：先运行 `python scripts/package_addon.py` "
            "生成 dist/Blender_AutoTopo-2.1.0.zip"
        )
    zip_mtime = os.path.getmtime(ZIP_PATH)
    newest = 0.0
    newest_file = ""
    for dirpath, dirnames, filenames in os.walk(_PROJECT_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _WALK_EXCLUDES]
        for name in filenames:
            if name.lower().endswith(".zip"):
                continue
            path = os.path.join(dirpath, name)
            try:
                mtime = os.path.getmtime(path)
                rel = os.path.relpath(path, _PROJECT_ROOT)
            except (OSError, ValueError):
                # e.g. a stray file whose name is a Windows device (nul/con);
                # it cannot be part of the shipped artifact.
                continue
            if mtime > newest:
                newest, newest_file = mtime, rel
    if newest > zip_mtime + 1:
        pytest.skip(
            f"打包产物已过期（{newest_file} 比 zip 更新）：重新运行 "
            "`python scripts/package_addon.py` 后重试"
        )


def _names():
    with zipfile.ZipFile(ZIP_PATH) as zf:
        return zf.namelist()


def test_archive_exists_and_intact():
    _skip_if_stale()
    with zipfile.ZipFile(ZIP_PATH) as zf:
        assert zf.testzip() is None, "zip 内部 CRC 校验失败（文件损坏）"


def test_top_level_prefix():
    _skip_if_stale()
    names = _names()
    assert names, "zip 为空"
    bad = [n for n in names if not n.startswith(PREFIX)]
    assert not bad, f"存在非 Blender_AutoTopo/ 顶层条目: {bad[:5]}"


def test_required_entries_present():
    _skip_if_stale()
    names = set(_names())
    missing = [entry for entry in REQUIRED_ENTRIES if entry not in names]
    assert not missing, f"缺少关键文件: {missing}"


def test_dev_artifacts_excluded():
    _skip_if_stale()
    names = _names()
    leaked = [
        n for n in names if any(sub in n for sub in EXCLUDED_SUBSTRINGS)
    ]
    assert not leaked, f"开发产物被打包: {leaked[:5]}"
    stray_zip = [
        n for n in names
        if n.startswith(PREFIX + "bin/") and n.lower().endswith(".zip")
    ]
    assert not stray_zip, f"bin/ 下残留 .zip 被打包: {stray_zip}"


def test_archive_size_budget():
    _skip_if_stale()
    size = os.path.getsize(ZIP_PATH)
    assert size < MAX_ARCHIVE_BYTES, (
        f"归档体积 {size / 1024 / 1024:.1f}MB 超过 "
        f"{MAX_ARCHIVE_BYTES / 1024 / 1024:.0f}MB 预算"
    )
