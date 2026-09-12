# Pokémon Doubles Engine in C — Architekturpaket v0.1

Stand: 12. September 2026. Arbeitsname: `pokemon-doubles-core`, Symbolpräfix `pbd_`.

Dies ist ein **Entwurf und Codex-Arbeitspaket**, keine implementierte Engine. Es wurden keine Engine-Tests, Builds oder Benchmarks ausgeführt und keine GitHub-Repositories angelegt oder verändert.

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
- Unveränderliche Referenz-Commits: noch nicht gepinnt.
- Konkrete Teams und Regelprofil: noch nicht ausgewählt.
- Code, Engine-Konformität, Performance und Hosted CI: nicht vorhanden bzw. nicht ausgeführt.
