"""duoforge.python.layout: every NumPy dtype and constant equals the C side.

The C tool duoforge_layout_dump (DUOFORGE_LAYOUT_DUMP) prints sizeof and the
offset and size of every field, and the constants the package uses; each
struct must have its dtype here with the same itemsize, field offsets and
field sizes, and each constant the same value.
"""
import json
import os
import subprocess
import unittest

from duoforge import _layout


def _dump():
    tool = os.environ.get("DUOFORGE_LAYOUT_DUMP")
    if not tool:
        raise RuntimeError("DUOFORGE_LAYOUT_DUMP is not set (the CTest test sets it)")
    out = subprocess.run([tool], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


class LayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dump = _dump()

    def test_every_struct_has_its_dtype(self):
        self.assertEqual(sorted(_layout.BY_C_NAME), sorted(self.dump["structs"]))

    def test_sizes_and_offsets_match(self):
        for c_name, entry in self.dump["structs"].items():
            dtype = _layout.BY_C_NAME[c_name]
            with self.subTest(struct=c_name):
                self.assertEqual(dtype.itemsize, entry["size"])
                self.assertEqual(sorted(dtype.names), sorted(entry["fields"]))
                for name, (offset, size) in entry["fields"].items():
                    field_dtype, field_offset = dtype.fields[name][:2]
                    self.assertEqual(field_offset, offset, name)
                    self.assertEqual(field_dtype.itemsize, size, name)

    def test_constants_match(self):
        self.assertEqual(_layout.CONSTANTS, self.dump["constants"])

    def test_factored_sizes(self):
        self.assertEqual(_layout.FACTORED_DOMAIN.itemsize, 652)
        self.assertEqual(_layout.FACTORED_CHOICE.itemsize, 8)


if __name__ == "__main__":
    unittest.main()
