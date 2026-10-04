"""Frontier string-buffer helpers must accept tokens and numeric indices."""

import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_stringvar_assembly import elf_data_section


ROOT = Path(__file__).resolve().parents[2]
COMMANDS = '''
.section .data
frontier_gettrainername STR_VAR_1
frontier_gettrainername STR_VAR_2
frontier_gettrainername 0
frontier_gettrainername 1
frontier_gettrainername 2
frontier_gettrainername 5
frontier_gettrainername (1 + 1)
apprentice_buff STR_VAR_1, APPRENTICE_BUFF_NAME
apprentice_buff STR_VAR_2, APPRENTICE_BUFF_LEVEL
apprentice_buff STR_VAR_3, APPRENTICE_BUFF_LEAD_MON_SPECIES
apprentice_buff 0, APPRENTICE_BUFF_NAME
apprentice_buff 1, APPRENTICE_BUFF_NAME
apprentice_buff 2, APPRENTICE_BUFF_NAME
apprentice_buff 5, APPRENTICE_BUFF_NAME
apprentice_buff (1 + 1), APPRENTICE_BUFF_NAME
apprentice_buff STR_VAR_1, VAR_0x8007
apprentice_buff 2, VAR_0x8007
'''


def expected_bytecode():
    # Field command IDs and operands are the same in both pointer layouts.
    def setvar(variable, value):
        return b"\x16" + struct.pack("<HH", variable, value)

    output = b""
    for string_id in (0, 1, 0, 1, 2, 5, 2):
        output += setvar(0x8004, 20) + setvar(0x8005, string_id) + b"\x25\x23\x01"
    for string_id, input_id in ((0, 6), (1, 8), (2, 9), (0, 6), (1, 6),
                                (2, 6), (5, 6), (2, 6), (0, 0x8007), (2, 0x8007)):
        output += setvar(0x8004, 16) + setvar(0x8005, string_id)
        if input_id == 0x8007:
            output += b"\x19" + struct.pack("<HH", 0x8006, input_id)
        else:
            output += setvar(0x8006, input_id)
        output += b"\x25\x24\x01"
    return output


EXPECTED = expected_bytecode()


def assembly_source(root=ROOT):
    macros = (root / "asm/macros/asm.inc").read_text()
    events = (root / "asm/macros/event.inc").read_text()
    table = (root / "data/script_cmd_table.inc").read_text()
    events = events.replace('.include "data/script_cmd_table.inc"', table)
    frontier = (root / "asm/macros/battle_frontier/frontier_util.inc").read_text()
    apprentice = (root / "asm/macros/battle_frontier/apprentice.inc").read_text()
    text = "\n".join(line.split("@", 1)[0] for line in (macros + events + frontier + apprentice).splitlines())
    prefix = '''#include "constants/vars.h"
#include "constants/apprentice.h"
#include "constants/frontier_util.h"
.set TRUE, 1
.set FALSE, 0
// Stable fixture IDs for these native function table entries.
.set SPECIAL_CallFrontierUtilFunc, 0x123
.set SPECIAL_CallApprenticeFunction, 0x124
'''
    return prefix + text + COMMANDS


def preprocess_assembly(portable_64bit, root=ROOT):
    command = ["gcc", "-E", "-P", "-x", "assembler-with-cpp", "-I", str(root / "include")]
    if portable_64bit:
        command.append("-DPORTABLE_64BIT=1")
    return subprocess.run(command + ["-"], input=assembly_source(root), text=True,
                          capture_output=True, check=True).stdout


class FrontierStringVarTests(unittest.TestCase):
    def check_bytecode(self, portable_64bit):
        with tempfile.TemporaryDirectory() as tmp:
            assembly = Path(tmp) / "frontier.s"
            obj = Path(tmp) / "frontier.o"
            binary = Path(tmp) / "frontier.bin"
            assembly.write_text(preprocess_assembly(portable_64bit))
            subprocess.run(["as", "--64" if portable_64bit else "--32",
                            str(assembly), "-o", str(obj)], capture_output=True, check=True)
            subprocess.run(["objcopy", "-O", "binary", "-j", ".data", str(obj), str(binary)],
                           capture_output=True, check=True)
            self.assertEqual(binary.read_bytes(), EXPECTED)

    def test_frontier_stringvars_32bit(self):
        self.check_bytecode(False)

    def test_frontier_stringvars_64bit(self):
        self.check_bytecode(True)

    @unittest.skipUnless(shutil.which("clang"), "clang required for LLVM assembler regression")
    def test_frontier_stringvars_llvm(self):
        for portable_64bit in (False, True):
            with self.subTest(portable_64bit=portable_64bit), tempfile.TemporaryDirectory() as tmp:
                assembly = Path(tmp) / "frontier.s"
                obj = Path(tmp) / "frontier-aarch64.o"
                assembly.write_text(preprocess_assembly(portable_64bit))
                subprocess.run([shutil.which("clang"), "--target=aarch64-linux-gnu", "-c",
                                "-x", "assembler", "-fPIC", str(assembly), "-o", str(obj)],
                               capture_output=True, check=True)
                elf = obj.read_bytes()
                self.assertEqual(elf[:6], b"\x7fELF\x02\x01")
                self.assertEqual(int.from_bytes(elf[18:20], "little"), 183)
                self.assertEqual(elf_data_section(elf), EXPECTED)


if __name__ == "__main__":
    unittest.main()
