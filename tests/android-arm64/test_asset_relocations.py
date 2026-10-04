"""Protect full native pointer slots during release asset stripping."""

import ast
import bisect
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class AssetRelocationTests(unittest.TestCase):
    def test_full_pointer_width_is_excluded(self):
        source = (ROOT / 'tools/dualscreen/make_asset_holes.py').read_text()
        function = next(node for node in ast.walk(ast.parse(source))
                        if isinstance(node, ast.FunctionDef) and node.name == 'split_around_relocs')
        extracted = ast.Module(body=[function], type_ignores=[])
        for width in (4, 8):
            with self.subTest(width=width):
                namespace = {'bisect': bisect, 'reloc_offsets': [164],
                             'pointer_bytes': width, 'MIN_SIZE': 32}
                exec(compile(extracted, '<production relocation splitter>', 'exec'), namespace)
                split = namespace['split_around_relocs']
                self.assertEqual(split(100, 128), [(100, 64), (164 + width, 64 - width)])
                # Range begins inside a pointer: exclude all remaining bytes,
                # including the upper half of an ELF64 pointer.
                self.assertEqual(split(164 + width - 1, 65), [(164 + width, 64)])


if __name__ == '__main__':
    unittest.main()
