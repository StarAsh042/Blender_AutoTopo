"""Regression tests for ``utils/integrity.py::verify_tree``.

``verify_tree`` walks a bundled-binary tree and verifies every ``*.dll`` /
``*.exe`` against the SHA-256 manifest. The security property that is easy
to silently regress is the rejection of **symbolic links / Windows reparse
points** used as *sub-directories*: ``os.walk`` does not descend into them,
so an attacker could hide tampered plugin DLLs behind a link and escape
verification. This module pins that behaviour.

Coverage:

1. a clean sandbox (entry ``.exe`` + a normal nested ``styles/`` DLL)
   verifies ``(True, None)`` — guards against false positives;
2. a normal nested sub-directory is **not** treated as a link;
3. a directory **junction** sub-directory is rejected ``(False, <link>)``;
4. a directory **symlink** sub-directory is rejected ``(False, <link>)``;
5. a tampered ``.exe`` is rejected ``(False, <exe>)``;
6. a missing manifest is **fail-closed** ``(False, ...)``.

Pure standard library; no ``bpy``. The real module is loaded through
``test/_pkgload.py`` and its ``_ADDON_ROOT`` / ``_MANIFEST_PATH`` are
redirected at throwaway ``tmp_path`` sandboxes, so the shipped ``bin/``
tree and its manifest are never read or touched.
"""
import hashlib
import json
import os
import subprocess

import pytest

import _pkgload

integrity = _pkgload.load_module("utils/integrity.py")


# --------------------------------------------------------------------------
# state isolation: never leak a sandbox pointer into other tests
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _restore_integrity_state():
    saved = (
        integrity._ADDON_ROOT,
        integrity._MANIFEST_PATH,
        integrity._manifest,
        integrity._manifest_loaded,
    )
    yield
    (integrity._ADDON_ROOT,
     integrity._MANIFEST_PATH,
     integrity._manifest,
     integrity._manifest_loaded) = saved


def _point_at(root, manifest):
    """Redirect the module's root/manifest at a sandbox (clears the cache)."""
    integrity._ADDON_ROOT = str(root)
    integrity._MANIFEST_PATH = str(manifest)
    integrity._manifest = None
    integrity._manifest_loaded = False


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel_key(root, path):
    rel = os.path.relpath(os.path.abspath(path), str(root))
    return rel.replace(os.sep, "/")


def _write_manifest(bin_dir, files):
    manifest = os.path.join(bin_dir, "integrity.json")
    with open(manifest, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "algorithm": "sha256", "files": files},
                  handle)
    return manifest


class _Sandbox:
    """A throwaway ``bin/<engine>/`` tree plus its manifest."""

    def __init__(self, root):
        self.root = str(root)
        self.bin_dir = os.path.join(self.root, "bin")
        self.engine_dir = os.path.join(self.bin_dir, "autoremesher")
        os.makedirs(self.engine_dir)

        self.exe = os.path.join(self.engine_dir, "autoremesher.exe")
        with open(self.exe, "wb") as handle:
            handle.write(b"MZ fake autoremesher v1")

        # A normal nested plugin directory (like Qt's ``styles/``).
        self.styles = os.path.join(self.engine_dir, "styles")
        os.makedirs(self.styles)
        self.nested_dll = os.path.join(self.styles, "qwindows.dll")
        with open(self.nested_dll, "wb") as handle:
            handle.write(b"plugin dll payload v1")

        self.files = {
            _rel_key(self.root, self.exe): _sha256(self.exe),
            _rel_key(self.root, self.nested_dll): _sha256(self.nested_dll),
        }
        self.manifest = _write_manifest(self.bin_dir, self.files)

    def external_dir(self, name="outside"):
        """A directory *outside* ``bin/`` to point a link at."""
        out = os.path.join(self.root, name)
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "evil.dll"), "wb") as handle:
            handle.write(b"tampered payload outside bin")
        return out


@pytest.fixture
def sandbox(tmp_path):
    return _Sandbox(tmp_path)


# --------------------------------------------------------------------------
# 1 & 2. clean tree verifies; a normal nested dir is not a link
# --------------------------------------------------------------------------
def test_clean_sandbox_with_nested_dir_verifies(sandbox):
    _point_at(sandbox.root, sandbox.manifest)
    assert integrity.verify_tree(sandbox.bin_dir) == (True, None)


def test_normal_nested_dir_is_not_link_like(sandbox):
    assert integrity._is_link_like(sandbox.styles) is False
    # And it must not abort the walk.
    _point_at(sandbox.root, sandbox.manifest)
    ok, failed = integrity.verify_tree(sandbox.bin_dir)
    assert ok is True and failed is None


# --------------------------------------------------------------------------
# 3. junction sub-directory -> rejected
# --------------------------------------------------------------------------
def _make_junction(link, target):
    if os.name != "nt":
        pytest.skip("directory junctions are Windows-only")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         f"New-Item -ItemType Junction -Path '{link}' -Target '{target}' "
         "| Out-Null"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not os.path.exists(link):
        pytest.skip(f"cannot create junction: {result.stderr.strip()}")


def test_junction_subdir_rejected(sandbox):
    outside = sandbox.external_dir()
    link = os.path.join(sandbox.engine_dir, "imageformats")
    _make_junction(link, outside)

    assert integrity._is_link_like(link) is True
    _point_at(sandbox.root, sandbox.manifest)
    ok, failed = integrity.verify_tree(sandbox.bin_dir)
    assert ok is False
    assert failed is not None
    assert os.path.normcase(failed) == os.path.normcase(link)


# --------------------------------------------------------------------------
# 4. symlink sub-directory -> rejected (skip, never fail, without privilege)
# --------------------------------------------------------------------------
def test_symlink_subdir_rejected(sandbox):
    outside = sandbox.external_dir()
    link = os.path.join(sandbox.engine_dir, "plugins")
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlink: {exc}")

    assert integrity._is_link_like(link) is True
    _point_at(sandbox.root, sandbox.manifest)
    ok, failed = integrity.verify_tree(sandbox.bin_dir)
    assert ok is False
    assert failed is not None
    assert os.path.normcase(failed) == os.path.normcase(link)


# --------------------------------------------------------------------------
# 5. tampered executable -> rejected
# --------------------------------------------------------------------------
def test_tampered_exe_rejected(sandbox):
    with open(sandbox.exe, "r+b") as handle:
        handle.write(b"X")  # flip a single byte; manifest no longer matches

    _point_at(sandbox.root, sandbox.manifest)
    ok, failed = integrity.verify_tree(sandbox.bin_dir)
    assert ok is False
    assert failed is not None
    assert os.path.normcase(failed) == os.path.normcase(sandbox.exe)


# --------------------------------------------------------------------------
# 6. missing manifest -> fail-closed
# --------------------------------------------------------------------------
def test_missing_manifest_fail_closed(sandbox):
    os.remove(sandbox.manifest)

    _point_at(sandbox.root, sandbox.manifest)
    ok, failed = integrity.verify_tree(sandbox.bin_dir)
    assert ok is False
    assert failed is not None


def test_verify_tree_ignores_non_loadable_files(sandbox):
    """A stray non-``.dll``/``.exe`` file is not verified (and not rejected)."""
    stray = os.path.join(sandbox.engine_dir, "readme.txt")
    with open(stray, "w", encoding="utf-8") as handle:
        handle.write("not a binary")

    _point_at(sandbox.root, sandbox.manifest)
    assert integrity.verify_tree(sandbox.bin_dir) == (True, None)
