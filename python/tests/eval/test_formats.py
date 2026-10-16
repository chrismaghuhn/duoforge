"""duoforge.python.formats: the format of a run as metadata (duoforge.formats, restructure step 8, plan "Format axis").

The transitional data kind -> format table is checked against the header (every DUOFORGE_DATA_KIND_* constant has a
format or a named refusal), the generated layout and the definition files; a Showdown format id matches exactly or is
refused, and so is a data kind without a format.
"""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from duoforge import _layout, formats

ROOT = Path(__file__).resolve().parents[3]
HEADER = ROOT / "include" / "duoforge" / "duoforge.h"


def header_kinds():
    """The DUOFORGE_DATA_KIND_* constants of the public header, by name (read here independently of formats)."""
    text = HEADER.read_text(encoding="utf-8")
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"#define (DUOFORGE_DATA_KIND_\w+)\s+(\d+)u", text)}


class TableTest(unittest.TestCase):
    def test_every_data_kind_has_a_format_or_a_named_refusal(self):
        kinds = header_kinds()
        self.assertIn("DUOFORGE_DATA_KIND_POOL", kinds)
        self.assertEqual(formats.data_kinds(), kinds)
        self.assertEqual(set(formats.DATA_KIND_FORMATS) | set(formats.NO_FORMAT), set(kinds))
        self.assertEqual(set(formats.DATA_KIND_FORMATS) & set(formats.NO_FORMAT), set())
        for name, value in kinds.items():  # the lookup the tools make, by value
            with self.subTest(kind=name):
                if name in formats.NO_FORMAT:
                    with self.assertRaisesRegex(formats.FormatError, f"{name} plays no format"):
                        formats.of_data_kind(value)
                else:
                    self.assertEqual(formats.of_data_kind(value)["id"], formats.DATA_KIND_FORMATS[name])

    def test_the_layout_agrees_with_the_header(self):
        kinds = header_kinds()
        layout = {n: v for n, v in _layout.CONSTANTS.items() if n.startswith("DUOFORGE_DATA_KIND_")}
        self.assertTrue(layout)
        for name, value in layout.items():
            self.assertEqual(kinds.get(name), value, name)

    def test_every_format_of_the_table_has_its_definition(self):
        self.assertEqual(formats.known(), sorted(p.stem for p in (ROOT / "data" / "formats").glob("*.json")))
        for name, format_id in formats.DATA_KIND_FORMATS.items():
            with self.subTest(kind=name):
                self.assertIn(format_id, formats.known())
                self.assertEqual(formats.definition(format_id)["id"], format_id)


class LookupTest(unittest.TestCase):
    def test_the_record_of_a_definition(self):
        self.assertEqual(formats.record("reg-mc"), {"id": "reg-mc", "showdown_format_id": "gen9championsvgc2026regmc"})
        with self.assertRaisesRegex(formats.FormatError, "no format definition 'gen9ou'"):
            formats.record("gen9ou")

    def test_a_showdown_format_id_matches_exactly(self):
        self.assertEqual(formats.by_showdown_id("gen9championsvgc2026regmc")["id"], "reg-mc")
        self.assertEqual(formats.by_showdown_id("gen9championsou")["id"], "champions-ou")
        for other in ("gen9championsvgc2026regmcbo3", "gen9championsvgc2026", "", "gen9ou"):
            with self.subTest(showdown=other), self.assertRaisesRegex(formats.FormatError, "no format definition"):
                formats.by_showdown_id(other)

    def test_the_format_of_a_data_kind(self):
        constants = _layout.CONSTANTS
        self.assertEqual(formats.of_data_kind(constants["DUOFORGE_DATA_KIND_POOL"])["id"], "reg-mc")
        self.assertEqual(formats.of_data_kind(header_kinds()["DUOFORGE_DATA_KIND_POOL_SINGLES_DEV"])["id"],
                         "champions-ou")
        with self.assertRaisesRegex(formats.FormatError, "DUOFORGE_DATA_KIND_SYNTHETIC plays no format"):
            formats.of_data_kind(constants["DUOFORGE_DATA_KIND_SYNTHETIC"])
        for kind in (0, 99, None):
            with self.subTest(kind=kind), self.assertRaisesRegex(formats.FormatError, "no DUOFORGE_DATA_KIND"):
                formats.of_data_kind(kind)
        with self.assertRaisesRegex(formats.FormatError, "has no format"):
            formats.of_data_kind(9, {"DUOFORGE_DATA_KIND_NEW": 9})

    def test_the_live_arenas_server_format_is_a_definition(self):
        from duoforge_live.arena import FORMAT  # live_arena records it (it challenges with it)
        self.assertEqual(formats.by_showdown_id(FORMAT)["id"], "reg-mc")

    def test_a_definition_names_its_own_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(ROOT / "data" / "formats" / "reg-mc.json", Path(tmp, "reg-mc.json"))
            other = json.loads(Path(tmp, "reg-mc.json").read_text(encoding="utf-8"))
            Path(tmp, "copy.json").write_text(json.dumps(other), encoding="utf-8")  # a copy under another name
            with mock.patch.object(formats, "FORMATS", Path(tmp)):
                self.assertEqual(formats.record("reg-mc")["id"], "reg-mc")
                with self.assertRaisesRegex(formats.FormatError, "names the id 'reg-mc', not its file name 'copy'"):
                    formats.record("copy")


if __name__ == "__main__":
    unittest.main()
