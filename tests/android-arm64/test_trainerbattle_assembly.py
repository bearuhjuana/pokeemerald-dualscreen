"""Optional trainer continuation labels must assemble without numeric comparisons."""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RECORDS = [(0, 2), (0, 2), (0, 2), (2, 3), (1, 3), (2, 3),
           (4, 3), (4, 3), (4, 3), (6, 4), (8, 4), (6, 4)]
COMMANDS = '''
.section .data
backward_script:
.byte 0xee
trainerbattle_single 1, intro, defeat
trainerbattle_single 2, intro, defeat, FALSE
trainerbattle_single 3, intro, defeat, 0
trainerbattle_single 4, intro, defeat, forward_script
trainerbattle_single 5, intro, defeat, forward_script, NO_MUSIC
trainerbattle_single 6, intro, defeat, backward_script
trainerbattle_double 7, intro, defeat, need_two
trainerbattle_double 8, intro, defeat, need_two, FALSE
trainerbattle_double 9, intro, defeat, need_two, 0
trainerbattle_double 10, intro, defeat, need_two, forward_script
trainerbattle_double 11, intro, defeat, need_two, forward_script, NO_MUSIC
trainerbattle_double 12, intro, defeat, need_two, backward_script
forward_script:
.byte 0xff
intro:
.byte 1
defeat:
.byte 2
need_two:
.byte 3
'''


def assembly_source(root=ROOT):
    events = (root / "asm/macros/event.inc").read_text()
    macros = []
    for name in ("event_ptr", "trainerbattle", "trainerbattle_single", "trainerbattle_double"):
        match = re.search(r"(?ms)^\s*\.macro " + name + r"(?=\s|$).*?^\s*\.endm\s*$", events)
        if not match:
            raise AssertionError(f"Production macro missing: {name}")
        macros.append(match[0])
    return '''
#include "constants/battle_setup.h"
#define FALSE 0
#define TRUE 1
#define LOCALID_NONE 0
#define SCR_OP_TRAINERBATTLE 0x5c
''' + "\n".join(macros) + "\nNO_MUSIC = FALSE\n" + COMMANDS


class TrainerBattleAssemblyTests(unittest.TestCase):
    def check_commands(self, portable_64bit):
        for tool in ("gcc", "as", "objcopy"):
            self.assertIsNotNone(shutil.which(tool), f"Required test tool missing: {tool}")
        command = ["gcc", "-E", "-P", "-x", "assembler-with-cpp", "-I", str(ROOT / "include")]
        if portable_64bit:
            command.append("-DPORTABLE_64BIT=1")
        result = subprocess.run(command + ["-"], input=assembly_source(), text=True,
                                capture_output=True, check=True)
        with tempfile.TemporaryDirectory() as tmp:
            assembly = Path(tmp) / "trainer.s"
            obj = Path(tmp) / "trainer.o"
            binary = Path(tmp) / "trainer.bin"
            assembly.write_text(result.stdout)
            subprocess.run(["as", "--64" if portable_64bit else "--32",
                            str(assembly), "-o", str(obj)], capture_output=True, check=True)
            subprocess.run(["objcopy", "-O", "binary", "-j", ".data", str(obj), str(binary)],
                           capture_output=True, check=True)
            data = binary.read_bytes()
            self.assertEqual(data[0], 0xee)
            offset = 1
            pointer_size = 8 if portable_64bit else 4
            for trainer, (kind, pointers) in enumerate(RECORDS, 1):
                self.assertEqual(data[offset:offset + 6], bytes([0x5c, kind, trainer, 0, 0, 0]))
                offset += 6 + pointers * pointer_size
            self.assertEqual(data[offset:], b"\xff\x01\x02\x03")
            # Assembly needs no Android headers or libraries. Exercise the actual
            # integrated assembler too when a target-capable clang is installed.
            clang = shutil.which("clang")
            if portable_64bit and clang:
                native = Path(tmp) / "trainer-aarch64.o"
                subprocess.run([clang, "--target=aarch64-linux-android21", "-c", "-x", "assembler",
                                str(assembly), "-o", str(native)], capture_output=True, check=True)
                elf = native.read_bytes()
                self.assertEqual(elf[:6], b"\x7fELF\x02\x01")
                self.assertEqual(int.from_bytes(elf[18:20], "little"), 183)

    def test_optional_trainer_scripts_32bit(self):
        self.check_commands(False)

    def test_optional_trainer_scripts_64bit(self):
        self.check_commands(True)


if __name__ == "__main__":
    unittest.main()
