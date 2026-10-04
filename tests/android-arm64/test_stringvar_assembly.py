"""String-buffer tokens and numeric indices must emit the same field bytecode."""

import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMANDS = '''
.section .data
stringvar STR_VAR_1
stringvar STR_VAR_2
stringvar STR_VAR_3
stringvar 0
stringvar 1
stringvar 2
stringvar 5
stringvar (1 + 1)
buffernumberstring STR_VAR_1, 0x8008
bufferspeciesname STR_VAR_2, 25
bufferitemname STR_VAR_3, 289
buffernumberstring 2, 0x8008
'''
EXPECTED = bytes.fromhex("00 01 02 00 01 02 05 02 83 00 08 80 7d 01 19 00 80 02 21 01 83 02 08 80")


def assembly_source(root=ROOT):
    # Match the game's assembly include expansion and comment stripping.
    macros = (root / "asm/macros/asm.inc").read_text()
    events = (root / "asm/macros/event.inc").read_text()
    table = (root / "data/script_cmd_table.inc").read_text()
    events = events.replace('.include "data/script_cmd_table.inc"', table)
    text = "\n".join(line.split("@", 1)[0] for line in (macros + events).splitlines())
    return text + COMMANDS


def preprocess_assembly(portable_64bit):
    command = ["gcc", "-E", "-P", "-x", "assembler-with-cpp"]
    if portable_64bit:
        command.append("-DPORTABLE_64BIT=1")
    return subprocess.run(command + ["-"], input=assembly_source(), text=True,
                          capture_output=True, check=True).stdout


def elf_data_section(elf):
    """Read .data from the AArch64 ELF64 little-endian object."""
    section_offset = struct.unpack_from("<Q", elf, 40)[0]
    section_size, section_count, names_index = struct.unpack_from("<HHH", elf, 58)
    sections = [struct.unpack_from("<IIQQQQIIQQ", elf, section_offset + index * section_size)
                for index in range(section_count)]
    strings = sections[names_index]
    names = elf[strings[4]:strings[4] + strings[5]]
    for section in sections:
        name = names[section[0]:].split(b"\0", 1)[0]
        if name == b".data":
            return elf[section[4]:section[4] + section[5]]
    raise AssertionError("AArch64 test object is missing .data")


class StringVarAssemblyTests(unittest.TestCase):
    def check_bytecode(self, portable_64bit):
        for tool in ("gcc", "as", "objcopy"):
            self.assertIsNotNone(shutil.which(tool), f"Required test tool missing: {tool}")
        with tempfile.TemporaryDirectory() as tmp:
            assembly = Path(tmp) / "buffers.s"
            obj = Path(tmp) / "buffers.o"
            binary = Path(tmp) / "buffers.bin"
            assembly.write_text(preprocess_assembly(portable_64bit))
            subprocess.run(["as", "--64" if portable_64bit else "--32",
                            str(assembly), "-o", str(obj)], capture_output=True, check=True)
            subprocess.run(["objcopy", "-O", "binary", "-j", ".data", str(obj), str(binary)],
                           capture_output=True, check=True)
            self.assertEqual(binary.read_bytes(), EXPECTED)

    def test_string_buffer_commands_32bit(self):
        self.check_bytecode(False)

    def test_string_buffer_commands_64bit(self):
        self.check_bytecode(True)

    @unittest.skipUnless(shutil.which("clang"), "clang required for LLVM assembler regression")
    def test_string_buffer_commands_llvm(self):
        # LLVM requires absolute expressions in .if; GNU as permits comparing
        # undefined symbol identities. No SDK is needed for this data fixture.
        for portable_64bit in (False, True):
            with self.subTest(portable_64bit=portable_64bit), tempfile.TemporaryDirectory() as tmp:
                assembly = Path(tmp) / "buffers.s"
                obj = Path(tmp) / "buffers-aarch64.o"
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
