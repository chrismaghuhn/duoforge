#!/usr/bin/env python3
"""Every Python test file that CTest runs as a script keeps its unittest.main()
block last: a TestCase class defined after `if __name__ == '__main__':` is never
run when the file is called directly, so its cases would pass by not running
(issue #457: the BulletFlag cases of test_gen_closure.py).

The files are the scripts named by a COMMAND "${PROJECT_SOURCE_DIR}/....py" in the
committed CMake files. A file that is not run as a script (python -m unittest)
loads all of its classes and is not affected.

usage: python3 tools/datagen/tests/test_main_last.py
"""
import ast
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRIPT = re.compile(r'"\$\{PROJECT_SOURCE_DIR\}/([^"]+\.py)"')


def registered_scripts():
    """The repository paths of the Python scripts the CMake files run."""
    found = set()
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if not x.startswith('.') and x not in ('build', 'third_party')]
        for f in files:
            if f == 'CMakeLists.txt' or f.endswith('.cmake'):
                with open(os.path.join(d, f), encoding='utf-8') as fh:
                    found.update(SCRIPT.findall(fh.read()))
    return sorted(found)


def is_main_guard(node):
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    names = [node.test.left] + node.test.comparators
    return any(isinstance(n, ast.Name) and n.id == '__name__' for n in names) and \
        any(isinstance(n, ast.Constant) and n.value == '__main__' for n in names)


def is_test_case(node):
    return isinstance(node, ast.ClassDef) and any(
        (isinstance(b, ast.Attribute) and b.attr == 'TestCase') or (isinstance(b, ast.Name) and b.id == 'TestCase')
        for b in node.bases)


def classes_after_main(text):
    """The TestCase classes defined at module level after the first main guard."""
    body = ast.parse(text).body
    guard = next((i for i, n in enumerate(body) if is_main_guard(n)), None)
    return [] if guard is None else [n.name for n in body[guard + 1:] if is_test_case(n)]


class MainLast(unittest.TestCase):
    def test_the_check_finds_a_class_after_main(self):
        text = ("import unittest\nclass A(unittest.TestCase):\n    pass\n"
                "if __name__ == '__main__':\n    unittest.main()\n"
                "class B(unittest.TestCase):\n    pass\n")
        self.assertEqual(classes_after_main(text), ['B'])
        self.assertEqual(classes_after_main(text.replace("if __name__ == '__main__'", "if '__main__' == __name__")), ['B'])

    def test_the_check_passes_a_class_before_main(self):
        text = ("import unittest\nclass A(unittest.TestCase):\n    pass\n"
                "if __name__ == '__main__':\n    unittest.main()\n")
        self.assertEqual(classes_after_main(text), [])

    def test_the_registered_scripts_keep_main_last(self):
        scripts = registered_scripts()
        self.assertIn('tools/datagen/tests/test_gen_closure.py', scripts)
        for rel in scripts:
            with self.subTest(script=rel):
                with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
                    self.assertEqual(classes_after_main(f.read()), [])


if __name__ == '__main__':
    unittest.main()
