"""Package Blender_AutoTopo into a Blender-installable zip.

Produces dist/Blender_AutoTopo-2.1.0.zip with every addon file under a
top-level ``Blender_AutoTopo/`` directory, excluding dev/CI artifacts:
``.workbuddy-ai``, ``deliverables``, ``dist``, ``.pytest_cache``,
``.github`` (CI config), any ``__pycache__`` tree, any ``target``
tree (Rust build output), and stray ``.zip`` bundles inside ``bin/``.
"""

import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(DIST, "Blender_AutoTopo-2.1.0.zip")

PREFIX = "Blender_AutoTopo"

EXCLUDE_DIRS = {
    ".workbuddy-ai",
    "deliverables",
    "dist",
    ".pytest_cache",
    "__pycache__",
    ".git",
    ".github",
    "node_modules",
    "target",
}

EXCLUDE_TOP_FILES = {
    ".gitignore",
    "package_addon.py",
}

# Invariant: under fail-closed integrity, a shipped addon without its
# manifest (or without the native binaries the manifest covers) cannot run
# any engine. Fail the build loudly instead of producing a dead package.
REQUIRED_ENTRIES = (
    "Blender_AutoTopo/__init__.py",
    "Blender_AutoTopo/bin/integrity.json",
    "Blender_AutoTopo/bin/autotopo_native.dll",
    "Blender_AutoTopo/bin/quadwild/lib_quadwild.dll",
    "Blender_AutoTopo/bin/quadwild/lib_quadpatches.dll",
    "Blender_AutoTopo/bin/autoremesher/autoremesher.exe",
    "Blender_AutoTopo/bin/quadriflow/quadriflow.exe",
)


def should_skip(dirpath, names):
    """Return names to skip at this directory level."""
    skip = set()
    for n in names:
        full = os.path.join(dirpath, n)
        if os.path.isdir(full):
            if n in EXCLUDE_DIRS:
                skip.add(n)
        else:
            # stray zip bundles that shouldn't ship (e.g. bin/*.zip)
            if n.lower().endswith(".zip"):
                skip.add(n)
            if dirpath == ROOT and n in EXCLUDE_TOP_FILES:
                skip.add(n)
    return skip


def main():
    if not os.path.isdir(DIST):
        os.makedirs(DIST)
    # fresh archive
    if os.path.exists(OUT):
        os.remove(OUT)

    entries = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT)
        skip = should_skip(dirpath, dirnames + filenames)
        # prune dirnames in-place so walk doesn't descend
        dirnames[:] = [d for d in dirnames if d not in skip]
        filenames = [f for f in filenames if f not in skip]

        for f in filenames:
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, ROOT)
            arcname = os.path.join(PREFIX, rel).replace(os.sep, "/")
            entries.append((full, arcname))

    entries.sort(key=lambda x: x[1])

    arcnames = {arc for _full, arc in entries}
    missing = [e for e in REQUIRED_ENTRIES if e not in arcnames]
    if missing:
        raise RuntimeError(
            "打包缺少必需文件（fail-closed 完整性校验下插件将无法运行）："
            + ", ".join(missing)
        )

    total_bytes = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for full, arcname in entries:
            z.write(full, arcname)
            total_bytes += os.path.getsize(full)

    size_mb = total_bytes / (1024 * 1024)
    print(f"Wrote {OUT}")
    print(f"  entries: {len(entries)}")
    print(f"  uncompressed: {size_mb:.2f} MB")
    print(f"  archive size: {os.path.getsize(OUT) / (1024 * 1024):.2f} MB")


if __name__ == "__main__":
    main()
