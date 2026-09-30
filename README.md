# Pokémon Doubles Engine in C — Architekturpaket v0.1

Stand: 12. September 2026. Arbeitsname: `pokemon-doubles-core`, Symbolpräfix `pbd_`.

Dies ist ein **Architekturentwurf mit dem M0-Build-Grundgerüst**, aber **noch keine Kampfengine**. Vorhanden sind: CMake/C17-Projekt, statische Core-Bibliothek, eine Versions-/Statusabfrage, Smoke- und Manifest-Tests sowie eine CI-Konfiguration. Es gibt noch keinen RNG, keinen Battle-State, keine Entscheidungen, keine Kampfmechanik und keine Benchmarks.

## Ziel

Eine headless, deterministische Pokémon-Doubles-Kampfengine in C17, zunächst für einen kleinen Generation-9-Slice mit zwei festen Teams. Später: zertifizierte VGC-Profile, Batch-Environments, Python-ML-Anbindung und Planung auf hypothetischen Zuständen.

Die Engine entscheidet Regeln; ein Modell wählt aus ihren angebotenen Entscheidungen. Weder Python noch ein neuronales Netz implementieren eine zweite Regelauthorität.

## So verwendest du das Paket

1. Öffne für dieses Projekt einen eigenen lokalen Arbeitsordner in Codex. Dieses Paket gehört **nicht** in Manafold, OCGForge oder Argentum Engine.
2. Kopiere die enthaltenen Dateien in diesen Ordner. Der Name ist ein Vorschlag, kein bereits angelegtes Repository.
3. Gib Codex den vollständigen Inhalt von `tasks/M0_BOOTSTRAP.md` als ersten Auftrag.
4. Prüfe dessen Diff und Testbericht. M0 autorisiert nicht automatisch M1 oder spätere Meilensteine.

Die Architekturdateien sind bewusst englisch, damit sie unmittelbar als technische Arbeitsgrundlage dienen. Dieser Einstieg ist deutsch.

## Dateien

| Datei | Zweck |
|---|---|
| `AGENTS.md` | Arbeitsregeln und Projektgrenzen für Codex |
| `docs/ARCHITECTURE.md` | Module, Zuständigkeiten, State, Ausführung, Daten und ML-Grenzen |
| `docs/DECISION_CONTRACT.md` | Gleichzeitige Entscheidungen, Kandidaten, Pausen und Fehlersemantik |
| `docs/DETERMINISM_AND_REPLAY.md` | RNG, Snapshots, Serialisierung und Reproduzierbarkeit |
| `docs/ROADMAP.md` | Kleine Umsetzungsslices mit überprüfbaren Exit-Kriterien |
| `docs/TESTING_AND_BENCHMARKS.md` | Referenztests, Datenschutztests, Diagnostik und Messmethodik |
| `docs/OPEN_DECISIONS.md` | Entscheidungen, die vor den jeweiligen Slices tatsächlich geklärt werden müssen |
| `docs/SOURCES.md` | Am 12. September 2026 geprüfte Primärquellen und ihre Grenzen |
| `tasks/M0_BOOTSTRAP.md` | Direkt verwendbarer erster Codex-Auftrag |
| `docs/decisions/0001-m0-build-foundation.md` | Entscheidungsnotiz zum M0-Build-Grundgerüst (vorgeschlagen, Review offen) |
| `CMakeLists.txt`, `CMakePresets.json`, `cmake/` | Build-Konfiguration, Presets, compiler-spezifische Warnungen/Sanitizer |
| `include/pbd/version.h`, `src/version.c` | Einzige öffentliche API bisher: Version und Implementierungsstufe |
| `tests/` | Smoke-Test und Manifest-Prüfung (mit Negativ-Fixtures) |
| `manifests/` | Source-Lock und Support-Manifest als Gerüst: alles `UNPINNED` bzw. `UNSUPPORTED` |
| `.github/workflows/ci.yml` | CI-Konfiguration für Linux (GCC/Clang, ASan/UBSan) und Windows (MSVC) |

## Bauen und testen

Voraussetzungen: CMake ≥ 3.21, ein C17-Compiler, unter Linux zusätzlich Ninja. Lokal verifiziert wurden nur die unten unter *Status* genannten Toolchains.

**Linux (GCC oder Clang, Ninja):**

```sh
cmake --preset ninja-debug            # bzw. ninja-release
cmake --build --preset ninja-debug
ctest --preset ninja-debug
```

Compiler wählen, z. B. mit `CC=clang cmake --preset ninja-debug`. Warnungen als Fehler: beim Konfigurieren `-DPBD_WARNINGS_AS_ERRORS=ON` anhängen (so läuft es in der CI).

**Linux mit AddressSanitizer + UndefinedBehaviorSanitizer:**

```sh
CC=gcc cmake --preset ninja-asan-ubsan
cmake --build --preset ninja-asan-ubsan
ctest --preset ninja-asan-ubsan
```

Mit Clang setzt dies die installierte compiler-rt-Laufzeit voraus (z. B. Ubuntu-Paket `libclang-rt-18-dev`).

**Windows (Visual Studio 2022, x64; cmd oder PowerShell):**

```sh
cmake --preset vs2022
cmake --build --preset vs2022-debug
ctest --preset vs2022-debug
```

Für Release `vs2022-release` statt `vs2022-debug` verwenden (Build und Test).

Build-Verzeichnisse liegen unter `build/<preset>/`. Alle Tests sind endlich und haben einen Timeout (Test-Presets: 60 s Standard).

## Die wichtigsten Festlegungen

**C17-Core, Windows und Linux, ein Battle pro kompakter State-Struktur.** Unveränderliche Regeldaten werden geteilt; temporäre Arbeitsdaten liegen in wiederverwendbarem Scratch-Speicher. Der Hot Path soll nach Initialisierung ohne Heap-Allokation auskommen, ohne dafür Regeln oder Diagnostik zu entfernen.

**Zwei Spieler, je zwei aktive Slots, gemeinsame Team-Entscheidungen.** Die Engine arbeitet von Entscheidungsgrenze zu Entscheidungsgrenze. Ein `step` ist nicht zwingend ein vollständiger Turn. Slot-Auswahl innerhalb eines Teams ist keine neue Spielrunde und verrät keine gegnerischen Entscheidungen.

**Zuerst ein kleiner, korrekt abgegrenzter Rules-Slice.** Unbekannte oder nicht unterstützte Mechaniken werden nicht ignoriert. Ein vereinfachtes Testprofil ist ausdrücklich kein vollständiges VGC-Profil. Die zwei Teams werden vor der inhaltlichen Implementierung anhand ihrer benötigten Mechaniken ausgewählt.

**Eigener RNG-Vertrag, keine behauptete Showdown-Seed-Parität.** Referenztests müssen Zufallsausgänge kontrollieren oder eine gesondert validierte Kompatibilitätsschicht benutzen.

**State ist nicht Observation.** Vollzustände und Replay-Seeds gehören nicht in den normalen Policy-Eingang. Kandidatenlisten, ihre Reihenfolge und Fehlerantworten gehören ebenfalls zur Informationsgrenze.

## Performance-Einordnung

Frühere Zahlen wie mehrere Tausend vollständige Gen-9-Doubles-Battles pro Sekunde und Core sind **keine belastbaren Messungen dieser Engine**. Dieses Paket legt keine solche Geschwindigkeit als Abnahmekriterium fest. Zuerst werden Workload, Regeln, Policies, Hardware und Log-Modus fixiert; anschließend wird gemessen.

## Status

- Architektur: Vorschlag v0.1.
- Referenz-Recherche: durchgeführt; siehe Quellen.
- Unveränderliche Referenz-Commits: noch nicht gepinnt (`manifests/source_lock.json`: `UNPINNED`).
- Konkrete Teams und Regelprofil: noch nicht ausgewählt (`manifests/support_manifest.json`: `NOT_SELECTED`).
- **M0 (Build-Grundgerüst): implementiert.** Lokal ausgeführt und bestanden unter Linux (Ubuntu 24.04, x86_64):
  - Debug und Release mit GCC 13.3.0 und mit Clang 18.1.3 (Warnungen als Fehler), CMake 3.28.3 und Ninja 1.11.1;
  - Debug und Release mit CMake 3.21.4 (deklariertes Minimum);
  - ASan+UBSan mit GCC 13.3.0.
- Nicht lokal ausgeführt: Windows/MSVC; ASan/UBSan mit Clang (in dieser Umgebung fehlt die compiler-rt-Laufzeit).
- Hosted CI: Workflow-Datei vorhanden. Sie gilt erst als bestanden, wenn ein Lauf auf der betreffenden Revision tatsächlich beobachtet wurde.
- Engine-Funktionalität (RNG, State, Entscheidungen, Kampf, Replay, Batch, Python): **nicht vorhanden**. Nächster Schritt ist M1 laut `docs/ROADMAP.md`, aber nur nach ausdrücklicher Freigabe.
