@echo off
REM ─────────────────────────────────────────────────────────────────────
REM Build bin\autotopo_native.dll from the Rust crate
REM (native\autotopo_native) with cargo.
REM
REM The DLL is intentionally self-contained: .cargo\config.toml pins
REM +crt-static for the MSVC target, so the shipped artifact has no VC
REM runtime dependency (matching the previous MinGW static build). It is
REM loaded by plain ctypes (utils/native.py) — no Python headers, no
REM MSVC ABI coupling.
REM
REM The script cds into the crate directory first so cargo always
REM discovers the repository-level .cargo\config.toml regardless of the
REM caller's working directory.
REM
REM After building, re-register the digest (fail-closed integrity):
REM   python scripts\gen_integrity.py
REM ─────────────────────────────────────────────────────────────────────
setlocal

set "HERE=%~dp0"
set "CRATE=%HERE%autotopo_native"
set "OUT=%HERE%..\bin\autotopo_native.dll"

echo [autotopo_native] crate: "%CRATE%"
echo [autotopo_native] output: "%OUT%"

cd /d "%CRATE%"
cargo build --release
if errorlevel 1 (
    echo [autotopo_native] BUILD FAILED
    exit /b 1
)

copy /Y "%CRATE%\target\release\autotopo_native.dll" "%OUT%" > nul
if errorlevel 1 (
    echo [autotopo_native] COPY FAILED
    exit /b 1
)
echo [autotopo_native] BUILD OK
echo [autotopo_native] remember: python scripts\gen_integrity.py
endlocal
