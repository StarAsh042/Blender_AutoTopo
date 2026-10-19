"""Verify release_native_libs lifts the Windows file lock on the DLLs.

Works on temp copies of the DLLs so the shipped binaries are never
touched.

Run:
  blender --background --python test/test_dll_release.py

Requires the precompiled native libraries (bin/quadwild/*.dll); under
pytest without Blender this module is skipped, and it also skips when
the native libraries are absent.
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
NATIVE_TEST = True


def _run():
    import shutil
    import tempfile
    import unittest.mock as mock

    from Blender_AutoTopo.engines.quadwild_engine import (
        release_native_libs, _bin_dir, _lib_filenames, _load_native_lib,
        is_quadwild_available,
    )

    if not is_quadwild_available():
        raise RuntimeError(
            "QuadWild native libraries not present in bin/quadwild — "
            "cannot run the DLL release test"
        )

    bin_dir = _bin_dir()
    qw_name, qp_name = _lib_filenames()

    tmp = tempfile.mkdtemp(prefix="dll_release_test_")
    qw_tmp = os.path.join(tmp, qw_name)
    qp_tmp = os.path.join(tmp, qp_name)
    shutil.copy(os.path.join(bin_dir, qw_name), qw_tmp)
    shutil.copy(os.path.join(bin_dir, qp_name), qp_tmp)

    print("=== DLL release test (temp copies) ===")
    # The temp copies live outside the addon root, so the SHA-256 manifest
    # lookup (integrity.verify_file -> rel_key_for) can never match them.
    # This test targets release_native_libs()'s Windows file-lock behaviour,
    # not the integrity gate (covered by utils/integrity tests), so verify is
    # stubbed to keep the lock test independent of the shipped manifest.
    patcher = mock.patch(
        "Blender_AutoTopo.utils.integrity.verify_file", return_value=True)
    patcher.start()
    try:
        # 1. Load the temp copies like the engine does
        lib1 = _load_native_lib(qw_tmp)
        lib2 = _load_native_lib(qp_tmp)
        print("loaded:", lib1._handle, lib2._handle)

        # 2. While loaded, delete must fail (this is the uninstall bug)
        try:
            os.remove(qw_tmp)
            print("note: delete succeeded while loaded (no lock on this OS)")
        except PermissionError:
            print("expected: file locked while DLL loaded")

        # 3. Release and verify the lock is gone
        release_native_libs()
        os.remove(qw_tmp)
        os.remove(qp_tmp)
        print("OK: files deletable after release_native_libs")

        # 4. Reloading after release must work (registry cleared)
        shutil.copy(os.path.join(bin_dir, qw_name), qw_tmp)
        lib3 = _load_native_lib(qw_tmp)
        assert lib3._handle, "reload failed"
        print("OK: reload after release works, handle:", lib3._handle)
        release_native_libs()
        os.remove(qw_tmp)

        print("=== DLL RELEASE TEST PASSED ===")
    finally:
        patcher.stop()
        shutil.rmtree(tmp, ignore_errors=True)


def test_dll_release():
    import pytest
    pytest.importorskip("bpy", reason="requires Blender background mode")
    _run()


if __name__ == "__main__":
    _run()
