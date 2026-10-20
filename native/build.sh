#!/usr/bin/env bash
# Build bin/autotopo_native.dll from the Rust crate
# (native/autotopo_native) with cargo.
#
# POSIX-shell twin of build.bat (same steps, same pinned configuration).
# The DLL is intentionally self-contained: .cargo/config.toml pins
# +crt-static for the MSVC target, so the shipped artifact has no VC
# runtime dependency (matching the previous MinGW static build). It is
# loaded by plain ctypes (utils/native.py) — no Python headers, no MSVC
# ABI coupling.
#
# The script cds into the crate directory first so cargo always
# discovers the repository-level .cargo/config.toml regardless of the
# caller's working directory.
#
# After building, re-register the digest (fail-closed integrity):
#   python scripts/gen_integrity.py
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRATE="$HERE/autotopo_native"
OUT="$HERE/../bin/autotopo_native.dll"

echo "[autotopo_native] crate: $CRATE"
echo "[autotopo_native] output: $OUT"

cd "$CRATE"
cargo build --release

cp -f "$CRATE/target/release/autotopo_native.dll" "$OUT"
echo "[autotopo_native] BUILD OK"
echo "[autotopo_native] remember: python scripts/gen_integrity.py"
