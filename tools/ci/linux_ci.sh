#!/usr/bin/env bash
# The Linux jobs of the local CI (tools/ci/local_ci.sh), run inside WSL with
# the sources in place (/mnt/c/...) and the builds under ~/df-build/ci for
# speed. Prints one "RESULT <job> PASS|FAIL <detail>" line per job.
#
# usage: linux_ci.sh <job...>
#   gcc-asan          GCC Debug with ASan and UBSan
#   clang-debug       Clang Debug
#   gcc-release-ipo   GCC Release with link-time optimization
#   clang-release-ipo Clang Release with link-time optimization
#   clang-tsan        Clang with ThreadSanitizer, the batch tests
set -u

SRC=$(cd "$(dirname "$0")/../.." && pwd)
OUT=$HOME/df-build/ci
JOBS=$(nproc)
mkdir -p "$OUT"
git config --global --add safe.directory "$SRC" 2>/dev/null

job() { # name cc cxx test-regex configure-arguments...
    local name=$1 cc=$2 cxx=$3 regex=$4
    shift 4
    local dir="$OUT/$name" log="$OUT/$name.log"
    rm -rf "$dir"
    if ! CC=$cc CXX=$cxx cmake -S "$SRC" -B "$dir" -G Ninja -DBUILD_TESTING=ON -DDUOFORGE_WARNINGS_AS_ERRORS=ON "$@" \
        > "$log" 2>&1; then
        echo "RESULT $name FAIL configure (see $log)"
        return
    fi
    if ! cmake --build "$dir" --parallel "$JOBS" >> "$log" 2>&1; then
        echo "RESULT $name FAIL build (see $log)"
        return
    fi
    local filter=()
    [ -n "$regex" ] && filter=(-R "$regex")
    local result
    # setarch -R: ThreadSanitizer cannot map its shadow memory under full ASLR.
    result=$(cd "$dir" && TSAN_OPTIONS="halt_on_error=1" setarch "$(uname -m)" -R \
        ctest --timeout 600 -j "$JOBS" --no-tests=error "${filter[@]}" 2>&1)
    echo "$result" >> "$log"
    local line
    line=$(echo "$result" | grep -E "tests passed" | tail -1)
    if echo "$line" | grep -q "^100% tests passed"; then
        echo "RESULT $name PASS $line"
    else
        echo "RESULT $name FAIL ${line:-no test summary} (see $log)"
    fi
}

for j in "$@"; do
    case "$j" in
    gcc-asan) job "$j" gcc g++ "" -DCMAKE_BUILD_TYPE=Debug -DDUOFORGE_ENABLE_SANITIZERS=ON ;;
    clang-debug) job "$j" clang clang++ "" -DCMAKE_BUILD_TYPE=Debug ;;
    gcc-release-ipo) job "$j" gcc g++ "" -DCMAKE_BUILD_TYPE=Release -DDUOFORGE_ENABLE_IPO=ON ;;
    clang-release-ipo) job "$j" clang clang++ "" -DCMAKE_BUILD_TYPE=Release -DDUOFORGE_ENABLE_IPO=ON ;;
    clang-tsan) job "$j" clang clang++ 'duoforge\.batch\.' -DCMAKE_BUILD_TYPE=RelWithDebInfo -DDUOFORGE_ENABLE_TSAN=ON ;;
    *) echo "RESULT $j FAIL unknown job" ;;
    esac
done
