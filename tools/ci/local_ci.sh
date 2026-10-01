#!/usr/bin/env bash
# Local CI: the merge gate while GitHub Actions runs only nightly (the free
# plan's minutes). It runs the CI matrix on this machine: Windows jobs with
# GCC, Clang and MSVC, and Linux jobs in WSL (tools/ci/linux_ci.sh). One line
# per job, logs under build/ci/; exit status 1 if any job fails.
#
# usage (Git Bash): tools/ci/local_ci.sh [--quick] [--no-linux] [--no-reference]
#   --quick         Windows GCC Debug and MSVC Release, Linux GCC ASan+UBSan
#   --no-linux      only the Windows jobs
#   --no-reference  without the Showdown reference traces
# environment (the defaults fit the owner's machine):
#   DUOFORGE_CI_GCC_BIN  WinLibs bin directory (gcc, ninja)
#   DUOFORGE_CI_CLANG    LLVM bin directory (clang, clang++, llvm-rc)
#   DUOFORGE_CI_PS       pinned Showdown checkout for the reference traces
#   DUOFORGE_CI_DISTRO   WSL distribution
#   DUOFORGE_CI_JOBS     parallel build and test jobs
set -u

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
GCC_BIN=${DUOFORGE_CI_GCC_BIN:-"$LOCALAPPDATA/Microsoft/WinGet/Packages/BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe/mingw64/bin"}
CLANG=${DUOFORGE_CI_CLANG:-"C:/Program Files/LLVM/bin"}
PS=${DUOFORGE_CI_PS:-"C:/Dev/src/pokemon-showdown"}
DISTRO=${DUOFORGE_CI_DISTRO:-"Ubuntu-24.04"}
JOBS=${DUOFORGE_CI_JOBS:-${NUMBER_OF_PROCESSORS:-8}}
QUICK=0
LINUX=1
REFERENCE=1
for arg in "$@"; do
    case "$arg" in
    --quick) QUICK=1 ;;
    --no-linux) LINUX=0 ;;
    --no-reference) REFERENCE=0 ;;
    *) echo "usage: $0 [--quick] [--no-linux] [--no-reference]" >&2; exit 2 ;;
    esac
done
export PATH="$GCC_BIN:$PATH"
OUT="$ROOT/build/ci"
mkdir -p "$OUT"
FAILED=0
SUMMARY=()

record() { # name status detail
    SUMMARY+=("$(printf '%-26s %-4s %s' "$1" "$2" "$3")")
    echo "$(printf '%-26s %-4s %s' "$1" "$2" "$3")"
    [ "$2" = PASS ] || FAILED=1
}

# win_job <name> <config or ""> <cmake configure arguments...>
win_job() {
    local name=$1 config=$2
    shift 2
    local dir="$OUT/$name" log="$OUT/$name.log"
    local build_cfg=() test_cfg=()
    if [ -n "$config" ]; then
        build_cfg=(--config "$config")
        test_cfg=(-C "$config")
    fi
    if ! cmake -S "$ROOT" -B "$dir" -DBUILD_TESTING=ON -DDUOFORGE_WARNINGS_AS_ERRORS=ON "$@" > "$log" 2>&1; then
        record "$name" FAIL "configure (see $log)"
        return
    fi
    if ! cmake --build "$dir" "${build_cfg[@]}" --parallel "$JOBS" >> "$log" 2>&1; then
        record "$name" FAIL "build (see $log)"
        return
    fi
    local result
    result=$(ctest --test-dir "$dir" "${test_cfg[@]}" --timeout 900 -j "$JOBS" 2>&1)
    echo "$result" >> "$log"
    local line
    line=$(echo "$result" | grep -E "tests passed" | tail -1)
    if echo "$line" | grep -q "^100% tests passed"; then
        record "$name" PASS "$line"
    else
        record "$name" FAIL "${line:-no test summary} (see $log)"
    fi
}

ref=()
if [ "$REFERENCE" = 1 ] && [ -d "$PS/dist" ]; then
    ref=(-DDUOFORGE_PS_REFERENCE_DIR="$PS")
fi
clang=(-DCMAKE_C_COMPILER="$CLANG/clang.exe" -DCMAKE_CXX_COMPILER="$CLANG/clang++.exe" -DCMAKE_RC_COMPILER="$CLANG/llvm-rc.exe")

win_job win-gcc-debug "" -G Ninja -DCMAKE_BUILD_TYPE=Debug -DCMAKE_C_COMPILER=gcc "${ref[@]}"
win_job win-msvc-release-ipo Release -G "Visual Studio 17 2022" -A x64 -DDUOFORGE_ENABLE_IPO=ON
if [ "$QUICK" = 0 ]; then
    win_job win-gcc-release-ipo "" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=gcc -DDUOFORGE_ENABLE_IPO=ON
    win_job win-clang-release "" -G Ninja -DCMAKE_BUILD_TYPE=Release "${clang[@]}"
    win_job win-msvc-debug Debug -G "Visual Studio 17 2022" -A x64
    win_job win-msvc-win32-release Release -G "Visual Studio 17 2022" -A Win32
fi

if [ "$LINUX" = 1 ]; then
    win_root=$(cygpath -m "$ROOT")
    drive=$(echo "${win_root:0:1}" | tr 'A-Z' 'a-z')
    wsl_root="/mnt/$drive${win_root:2}"
    if [ "$QUICK" = 1 ]; then
        linux_jobs=(gcc-asan)
    else
        linux_jobs=(gcc-asan clang-debug gcc-release-ipo clang-release-ipo clang-tsan)
    fi
    while IFS= read -r line; do
        line=${line//$'\r'/}
        case "$line" in
        RESULT\ *)
            set -- $line
            name=$2 status=$3
            shift 3
            record "linux-$name" "$status" "$*"
            ;;
        esac
    done < <(MSYS_NO_PATHCONV=1 wsl.exe -d "$DISTRO" -- bash "$wsl_root/tools/ci/linux_ci.sh" "${linux_jobs[@]}" 2>&1 | tr -d '\000')
    if [ "${#SUMMARY[@]}" -eq 0 ] || ! printf '%s\n' "${SUMMARY[@]}" | grep -q "^linux-"; then
        record linux FAIL "WSL ($DISTRO) gave no result"
    fi
fi

echo
echo "local CI: ${#SUMMARY[@]} jobs, $([ "$FAILED" = 0 ] && echo "all passed" || echo "FAILED")"
exit "$FAILED"
