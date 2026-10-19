@echo off
REM ─────────────────────────────────────────────────────────────────────
REM Build bin\autotopo_native.dll with the MinGW-w64 g++ toolchain.
REM
REM The compiler is NOT on PATH, so its absolute location is pinned
REM below. Override by setting GXX before invoking this script.
REM
REM The DLL is intentionally self-contained (-static -static-libgcc
REM -static-libstdc++) so it has no runtime dependency on libstdc++ /
REM libwinpthread, and is loaded by plain ctypes (no Python headers,
REM no MSVC ABI coupling).
REM ─────────────────────────────────────────────────────────────────────
setlocal

if "%GXX%"=="" set "GXX=C:\Users\Administrator\.workbuddy-ai\binaries\mingw64\mingw64\bin\g++.exe"

set "HERE=%~dp0"
set "SRC=%HERE%autotopo_native.cpp"
set "OUT=%HERE%..\bin\autotopo_native.dll"

echo [autotopo_native] compiler: "%GXX%"
echo [autotopo_native] output  : "%OUT%"

"%GXX%" -std=c++17 -O2 -shared -static -static-libgcc -static-libstdc++ ^
    -Wall -Wextra ^
    -o "%OUT%" "%SRC%"

if errorlevel 1 (
    echo [autotopo_native] BUILD FAILED
    exit /b 1
)
echo [autotopo_native] BUILD OK
endlocal
