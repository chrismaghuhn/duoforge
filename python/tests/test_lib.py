"""duoforge.python.lib: loading the shared library, errors, context, setups."""
import os
import shutil
import tempfile
import unittest

import numpy as np

import duoforge
from duoforge import _layout, _lib


class _Env:
    """Sets one environment variable for a block, then restores it."""

    def __init__(self, name, value):
        self.name, self.value, self.old = name, value, None

    def __enter__(self):
        self.old = os.environ.get(self.name)
        os.environ[self.name] = self.value

    def __exit__(self, *exc):
        if self.old is None:
            del os.environ[self.name]
        else:
            os.environ[self.name] = self.old


class LibTest(unittest.TestCase):
    def test_version(self):
        self.assertEqual(duoforge.version(), "0.27.0")
        self.assertEqual(_lib.EXPECTED_VERSION, "0.27.0")

    def test_missing_library_names_the_path(self):
        with _Env("DUOFORGE_LIBRARY", "nonexistent.dll"):
            with self.assertRaises(duoforge.DuoforgeLibraryError) as caught:
                duoforge.load_library()
        self.assertIn("nonexistent.dll", str(caught.exception))

    def test_other_version_names_path_and_version(self):
        path = os.environ["DUOFORGE_LIBRARY"]
        found = duoforge.version()
        expected = _lib.EXPECTED_VERSION
        _lib.EXPECTED_VERSION = "0.0.0"
        try:
            with self.assertRaises(duoforge.DuoforgeLibraryError) as caught:
                duoforge.load_library()
        finally:
            _lib.EXPECTED_VERSION = expected
        message = str(caught.exception)
        self.assertIn(path, message)
        self.assertIn(f"version {found}", message)

    def test_two_matching_builds_raise(self):
        source = os.environ["DUOFORGE_LIBRARY"]
        folder = tempfile.mkdtemp(prefix="duoforge-builds-")
        try:
            copies = []
            for name in ("a", "b"):
                os.mkdir(os.path.join(folder, name))
                copies.append(shutil.copy(source, os.path.join(folder, name)))
            with self.assertRaises(duoforge.DuoforgeLibraryError) as caught:
                _lib._load(((), tuple(copies)), _lib.EXPECTED_VERSION)
            for path in copies:
                self.assertIn(path, str(caught.exception))
            self.assertEqual(_lib._load(((), (copies[0],)), _lib.EXPECTED_VERSION)._duoforge_path, copies[0])
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.assertEqual(os.path.normcase(duoforge.library_path()), os.path.normcase(os.path.abspath(source)))

    def test_integers_are_checked_not_coerced(self):
        with self.assertRaises(ValueError):
            duoforge.reference_setups([2**32 + 3])
        with self.assertRaises(TypeError):
            duoforge.reference_setups([1.0])
        with self.assertRaises(TypeError):
            duoforge.Context(brought_count=4.7)
        with self.assertRaises(TypeError):
            _lib.uint(1.9, 32, "x")
        self.assertEqual(_lib.uint(np.uint8(3), 32, "x"), 3)

    def test_reference_setups(self):
        setups = duoforge.reference_setups([0, 1, 2, 3])
        self.assertEqual(setups.shape, (4,))
        self.assertEqual(setups.dtype, _layout.SETUP)
        self.assertEqual(int(setups[0]["sides"][0]["member_count"]), 6)
        self.assertTrue(np.array_equal(setups[1]["sides"][0], setups[0]["sides"][1]))
        with self.assertRaises(duoforge.DuoforgeError) as caught:
            duoforge.reference_setups([4])
        self.assertEqual(caught.exception.status_name, "DUOFORGE_E_INVALID_ARGUMENT")

    def test_context(self):
        with duoforge.Context() as ctx:
            self.assertTrue(ctx.handle)
        self.assertIsNone(ctx.handle)
        ctx.close()  # a second close is a no-op
        with self.assertRaises(duoforge.DuoforgeError) as caught:
            duoforge.Context(brought_count=7)
        self.assertEqual(caught.exception.status_name, "DUOFORGE_E_INVALID_ARGUMENT")

    def test_error_carries_statuses(self):
        statuses = np.array([0, 12], dtype=np.uint32)
        err = duoforge.DuoforgeError("DUOFORGE_E_STALE_EPOCH", statuses)
        self.assertIs(err.statuses, statuses)
        self.assertIn("DUOFORGE_E_STALE_EPOCH", str(err))


if __name__ == "__main__":
    unittest.main()
