"""Regenerate ``bin/integrity.json`` from the bundled binaries.

Walks ``bin/`` recursively for every loadable binary (``*.dll`` /
``*.exe``) and records its SHA-256, so the addon can verify each one
before loading / executing it (see ``utils/integrity.py``).

Windows loads an executable's *same-directory* DLLs first, so a manifest
that only lists the entry executable is insufficient — a tampered sibling
dependency (e.g. ``Qt5Core.dll``) would still run. This script therefore
covers the whole ``bin/`` tree, including Qt plugin sub-directories.

Run after adding, removing or updating any bundled binary::

    python scripts/gen_integrity.py
"""

import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin")
OUT = os.path.join(BIN, "integrity.json")
LOADABLE_EXTS = (".dll", ".exe")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    files = {}
    for dirpath, _dirs, names in os.walk(BIN):
        for name in sorted(names):
            if not name.lower().endswith(LOADABLE_EXTS):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            files[rel] = sha256_file(full)

    data = {
        "version": 1,
        "algorithm": "sha256",
        "files": dict(sorted(files.items())),
    }
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    print("wrote %d entries to %s" % (len(files), OUT))


if __name__ == "__main__":
    main()
