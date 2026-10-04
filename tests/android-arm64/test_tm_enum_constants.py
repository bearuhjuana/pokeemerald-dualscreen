"""TM/HM assembly aliases must use absolute IDs with either pointer layout."""

import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TMEnumConstantsTests(unittest.TestCase):
    def check_tm_hm_ids(self, portable_64bit):
        for tool in ("gcc", "as", "objcopy"):
            self.assertIsNotNone(shutil.which(tool), f"Required test tool missing: {tool}")
        source = '''#include "asm/macros/asm.inc"
#include "constants/tms_hms.inc"
.section .data
.short ITEM_TM_FOCUS_PUNCH, ITEM_TM_OVERHEAT, ITEM_HM_CUT, ITEM_HM_DIVE
'''
        command = ["gcc", "-E", "-P", "-x", "assembler-with-cpp",
                   "-I", str(ROOT), "-I", str(ROOT / "include")]
        if portable_64bit:
            command.append("-DPORTABLE_64BIT=1")
        result = subprocess.run(command + ["-"], input=source, text=True,
                                capture_output=True, check=True)
        # LLVM rejects increments of a counter seeded by an undefined symbol.
        self.assertNotIn("enum_start ITEM_TM01", result.stdout)
        self.assertNotIn("enum_start ITEM_HM01", result.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            assembly = Path(tmp) / "ids.s"
            obj = Path(tmp) / "ids.o"
            binary = Path(tmp) / "ids.bin"
            assembly.write_text(result.stdout)
            subprocess.run(["as", "--64" if portable_64bit else "--32",
                            str(assembly), "-o", str(obj)],
                           capture_output=True, check=True)
            subprocess.run(["objcopy", "-O", "binary", "-j", ".data",
                            str(obj), str(binary)], capture_output=True, check=True)
            self.assertEqual(binary.read_bytes(), struct.pack("<4H", 289, 338, 339, 346))

    def test_tm_hm_ids_32bit(self):
        self.check_tm_hm_ids(False)

    def test_tm_hm_ids_64bit(self):
        self.check_tm_hm_ids(True)


if __name__ == "__main__":
    unittest.main()
