"""Bundled-binary integrity verification (SHA-256).

Central trust anchor for the multi-engine addon. Before a bundled native
binary is loaded or executed — the AutoRemesher / QuadriFlow executables,
the QuadWild DLLs, or the optional ``autotopo_native`` acceleration DLL —
its SHA-256 is compared against a manifest shipped with the addon
(``bin/integrity.json``). This closes the "tamper a bundled binary (or a
preference that points at one) -> arbitrary code execution" surface.

Manifest format::

    {
      "version": 1,
      "algorithm": "sha256",
      "files": {
        "bin/autoremesher/autoremesher.exe": "<lower-case hex sha256>",
        ...
      }
    }

Keys are POSIX-style paths relative to the addon root; values are the
lower-case hex SHA-256 digests.

Policy (see :func:`verify`):

* **Manifest present** — strict: the file must be listed and its digest
  must match. A missing key or a mismatch returns ``False``; the caller
  refuses to load / execute and surfaces a Chinese error.
* **Manifest missing / unparseable** — fail-closed: returns ``False`` so
  bundled binaries are refused. The manifest ships with the addon, so its
  absence is treated as a broken / tampered install. There is
  deliberately no silent pass-through and no environment-variable
  override.

This module never raises: every failure path is logged and mapped to a
boolean.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from typing import Dict, Optional, Tuple

from .logger import logger

# Addon root = the directory containing ``utils/`` (and ``bin/``).
_ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MANIFEST_PATH = os.path.join(_ADDON_ROOT, "bin", "integrity.json")

_CHUNK = 1 << 20  # 1 MiB

_manifest: Optional[Dict[str, str]] = None
_manifest_loaded = False


def addon_root() -> str:
    """Absolute path of the addon root (the directory holding ``bin/``)."""
    return _ADDON_ROOT


def manifest_path() -> str:
    """Absolute path of the integrity manifest."""
    return _MANIFEST_PATH


def sha256_file(path: str) -> str:
    """Hex SHA-256 digest of ``path`` (streamed, memory-bounded)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel_key_for(path: str) -> str:
    """Manifest key (POSIX relative path) for an on-disk ``path``."""
    try:
        rel = os.path.relpath(os.path.abspath(path), _ADDON_ROOT)
    except Exception:
        return os.path.basename(path)
    return rel.replace(os.sep, "/")


def _load_manifest() -> Optional[Dict[str, str]]:
    """Load and cache the manifest. ``None`` when unavailable."""
    global _manifest, _manifest_loaded
    if _manifest_loaded:
        return _manifest
    _manifest_loaded = True
    try:
        with open(_MANIFEST_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        files = data.get("files", data) if isinstance(data, dict) else {}
        _manifest = {
            str(key).replace("\\", "/"): str(value).strip().lower()
            for key, value in dict(files).items()
        }
        logger.info(
            "integrity: 已加载校验清单（%d 项）：%s",
            len(_manifest), _MANIFEST_PATH,
        )
    except Exception as exc:
        _manifest = None
        logger.warning(
            "integrity: 校验清单不可用（%s）：%s", _MANIFEST_PATH, exc)
    return _manifest


def verify(path: str, rel_key: str) -> bool:
    """Return ``True`` when ``path`` passes integrity verification.

    ``rel_key`` is the manifest key the file is checked against (for a
    bundled file this is :func:`rel_key_for`). The digest is recomputed on
    every call — no mtime/size cache, which an attacker could otherwise
    poison by restoring a timestamp after tampering. A missing or
    unreadable manifest is **fail-closed**: verification returns ``False``,
    so a bundled binary is never executed unverified. Callers are
    responsible for restricting user-supplied overrides to the engine's
    own ``bin/<engine>/`` directory before this is reached.
    """
    manifest = _load_manifest()
    if manifest is None:
        logger.error(
            "integrity: 校验清单缺失/不可解析，拒绝加载（fail-closed）：%s",
            _MANIFEST_PATH)
        return False

    key = str(rel_key).replace("\\", "/")
    expected = manifest.get(key)
    if not expected:
        logger.error("integrity: 清单未收录 %s，拒绝加载", key)
        return False

    # Always hash fresh — no caching. A cache keyed on (path, mtime, size)
    # can be poisoned by an attacker who restores the timestamp after
    # tampering, so the digest is deliberately recomputed on every call.
    try:
        actual = sha256_file(path).lower()
    except Exception as exc:
        logger.error("integrity: 计算 SHA-256 失败 %s：%s", path, exc)
        return False

    if actual != expected:
        logger.error(
            "integrity: SHA-256 不匹配 %s（期望 %s…，实际 %s…）",
            path, expected[:12], actual[:12],
        )
        return False
    return True


def verify_file(path: str) -> bool:
    """Convenience wrapper: :func:`verify` with the derived manifest key."""
    return verify(path, rel_key_for(path))


def _is_link_like(path: str) -> bool:
    """True for a symbolic link or a Windows reparse point (e.g. junction)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def verify_tree(root_dir: str) -> Tuple[bool, Optional[str]]:
    """Verify every loadable binary (``*.dll`` / ``*.exe``) under ``root_dir``.

    Windows loads an executable's *same-directory* DLLs first, so checking
    only the entry binary is not enough — a tampered sibling dependency
    (e.g. ``Qt5Core.dll``) would still execute while the entry executable
    keeps verifying. This walks ``root_dir`` recursively (covering Qt
    plugin sub-directories such as ``platforms/`` / ``imageformats/``) and
    verifies each loadable file against the manifest.

    Sub-directories that are symbolic links / reparse points are rejected
    outright: ``os.walk`` does not descend into them, which would otherwise
    let an attacker hide tampered plugin DLLs behind a link and escape
    verification.

    Returns ``(ok, failed_path)`` where ``failed_path`` is the first entry
    that failed verification (``None`` when everything passed). A missing
    manifest is fail-closed (see :func:`verify`).
    """
    if not os.path.isdir(root_dir):
        return True, None
    for dirpath, dirs, names in os.walk(root_dir):
        for name in sorted(dirs):
            full = os.path.join(dirpath, name)
            if _is_link_like(full):
                logger.error(
                    "integrity: 拒绝符号链接/重解析点目录：%s", full)
                return False, full
        for name in sorted(names):
            if not name.lower().endswith((".dll", ".exe")):
                continue
            full = os.path.join(dirpath, name)
            if not verify_file(full):
                return False, full
    return True, None
