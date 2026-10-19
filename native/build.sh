#!/usr/bin/env bash
# Build bin/autotopo_native.dll with the MinGW-w64 g++ toolchain.
#
# POSIX-shell twin of build.bat (same flags, same pinned compiler).
# The compiler is NOT on PATH, so its absolute location is pinned here.
# Override with: GXX=/path/to/g++ ./build.sh
#
# The DLL is intentionally self-contained (-static -static-libgcc
# -static-libstdc++) so it has no runtime dependency on libstdc++ /
# libwinpthread, and is loaded by plain ctypes (no Python headers, no
# MSVC ABI coupling).
set -euo pipefail

GXX="${GXX:-C:/Users/Administrator/.workbuddy-ai/binaries/mingw64/mingw64/bin/g++.exe}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/autotopo_native.cpp"
OUT="$HERE/../bin/autotopo_native.dll"

echo "[autotopo_native] compiler: $GXX"
echo "[autotopo_native] output  : $OUT"

"$GXX" -std=c++17 -O2 -shared -static -static-libgcc -static-libstdc++ \
    -Wall -Wextra \
    -o "$OUT" "$SRC"

echo "[autotopo_native] BUILD OK"
