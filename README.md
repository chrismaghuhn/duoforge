# DuoForge

DuoForge is a deterministic, headless Pokémon Doubles simulation engine designed for machine-learning workloads.

The project is at a very early stage. M0 contains only a portable C17 static library, a public version query, a real smoke test, and build/CI scaffolding. It is not yet a complete Pokémon battle simulator.

No Pokémon species, moves, abilities, items, damage calculation, turn resolution, targeting, battle RNG, replay, observations, action generation, batch environments, Python bindings, or ML code are implemented.

## Requirements

- CMake 3.23 or newer
- A C17 compiler such as MSVC, GCC, or Clang
- Ninja for the supplied cross-platform presets

There are no third-party runtime dependencies.

## Build and test

The presets use Ninja and provide separate Debug and Release trees:

```text
cmake --preset debug
cmake --build --preset debug
ctest --preset debug

cmake --preset release
cmake --build --preset release
ctest --preset release
```

On Windows, run these commands from a Visual Studio Developer Command Prompt so that MSVC is available. On Linux, run them from a shell with GCC or Clang and Ninja on `PATH`.

The equivalent generator-neutral commands are:

```text
cmake -S . -B build/debug -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON
cmake --build build/debug
ctest --test-dir build/debug --output-on-failure
```

The sanitizer configuration is intended for GCC/Clang:

```text
cmake -S . -B build/sanitized -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON -DDUOFORGE_ENABLE_SANITIZERS=ON
cmake --build build/sanitized
ctest --test-dir build/sanitized --output-on-failure
```

## Project boundaries

The intended future boundaries are listed in [`docs/architecture/README.md`](docs/architecture/README.md). They are not frozen by M0. Source and support status is tracked separately in [`docs/support/README.md`](docs/support/README.md), where unpinned and unsupported items remain explicit.

M0 does not claim full Gen 9 support, VGC compatibility, Pokémon Showdown parity, high performance, or deterministic replay support.
