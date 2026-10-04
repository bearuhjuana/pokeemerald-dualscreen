"""Exercise the production voice-data include/preprocessor/object pipeline."""

import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def voice_object_metadata(path):
    elf = path.read_bytes()
    bits = 64 if elf[4] == 2 else 32
    if bits == 64:
        offset = struct.unpack_from("<Q", elf, 40)[0]
        entry_size, count, names_index = struct.unpack_from("<HHH", elf, 58)
        section_format = "<IIQQQQIIQQ"
    else:
        offset = struct.unpack_from("<I", elf, 32)[0]
        entry_size, count, names_index = struct.unpack_from("<HHH", elf, 46)
        section_format = "<IIIIIIIIII"
    sections = [struct.unpack_from(section_format, elf, offset + index * entry_size)
                for index in range(count)]

    def contents(section):
        return elf[section[4]:section[4] + section[5]]

    names = contents(sections[names_index])
    section_names = [names[section[0]:].split(b"\0", 1)[0] for section in sections]
    rodata_index = section_names.index(b".rodata")
    symtab = sections[section_names.index(b".symtab")]
    symbol_names = contents(sections[symtab[6]])
    symbols = []
    for position in range(symtab[4], symtab[4] + symtab[5], symtab[9]):
        if bits == 64:
            name, _, _, _, value, _ = struct.unpack_from("<IBBHQQ", elf, position)
        else:
            name, value, _, _, _, _ = struct.unpack_from("<IIIBBH", elf, position)
        symbols.append((symbol_names[name:].split(b"\0", 1)[0], value))
    values = dict(symbols)
    relocations = []
    for section in sections:
        if section[1] not in (4, 9) or section[7] != rodata_index:
            continue
        for position in range(section[4], section[4] + section[5], section[9]):
            if bits == 64:
                reloc_offset, info = struct.unpack_from("<QQ", elf, position)
                symbol_index, relocation_type = info >> 32, info & 0xFFFFFFFF
            else:
                reloc_offset, info = struct.unpack_from("<II", elf, position)
                symbol_index, relocation_type = info >> 8, info & 0xFF
            relocations.append((reloc_offset, relocation_type, symbols[symbol_index][0]))
    return bits, int.from_bytes(elf[18:20], "little"), values, contents(sections[rodata_index]), relocations


class ProductionVoiceDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="production-voice-data-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.fixture = Path(cls.directory.name)
        preproc = cls.fixture / "tools/preproc/preproc"
        preproc.parent.mkdir(parents=True)
        # CI runs unit tests before make_tools. Build the real tool in this
        # fixture, leaving the repository and its generated assets untouched.
        sources = sorted((ROOT / "tools/preproc").glob("*.cpp"))
        subprocess.run(["g++", "-std=c++14", "-O2", *map(str, sources), "-o", str(preproc)],
                       capture_output=True, check=True)
        files = ("charmap.txt", "data/sound_data.s", "asm/macros/m4a.inc",
                 "asm/macros/music_voice.inc", "sound/voicegroups/intro.inc")
        for name in files:
            target = cls.fixture / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        # Keep the production top-level file verbatim. Its voice-group include
        # loads the real intro bank; unrelated tables and PCM payloads are empty.
        (cls.fixture / "sound/voice_groups.inc").write_text(
            '.include "sound/voicegroups/intro.inc"\n'
            '.global fixture_intro_end\nfixture_intro_end:\n')
        for name in ("keysplit_tables.inc", "programmable_wave_data.inc",
                     "music_player_table.inc", "song_table.inc", "direct_sound_data.inc"):
            (cls.fixture / "sound" / name).write_text("\n")
        cls.gnu_compiler = cls.fixture / "gnu-compiler.py"
        cls.gnu_compiler.write_text(f"#!{sys.executable}\n" + '''import os
import sys
args = sys.argv[1:]
target = next(arg for arg in args if arg.startswith("--target="))
args = [arg for arg in args if not arg.startswith(("--target=", "--sysroot="))]
os.execvp("gcc", ["gcc", "-m32" if "i386" in target else "-m64", *args])
''')
        cls.gnu_compiler.chmod(0o755)

    def check_pipeline(self, compiler, target, portable_64bit, machine, pointer_relocation):
        output = self.fixture / ("voice-" + target + ("-64.o" if portable_64bit else "-32.o"))
        command = [sys.executable, str(ROOT / "android/app/src/main/cpp/prepare_data.py"),
                   "--root", str(self.fixture), "--source", str(self.fixture / "data/sound_data.s"),
                   "--output", str(output), "--compiler", str(compiler),
                   "--target", target, "--sysroot", str(self.fixture)]
        if portable_64bit:
            command.append("--portable-64bit")
        subprocess.run(command, capture_output=True, check=True)
        bits, actual_machine, symbols, rodata, relocations = voice_object_metadata(output)
        self.assertEqual(bits, 64 if portable_64bit else 32)
        self.assertEqual(actual_machine, machine)
        start = symbols[b"voicegroup_intro"]
        stride, pointer_offset = (24, 8) if portable_64bit else (12, 4)
        self.assertEqual(symbols[b"fixture_intro_end"] - start, 128 * stride)
        # Intro instrument 13 is a real PCM sample, not a scalar PSG union slot.
        record = start + 13 * stride
        self.assertEqual(rodata[record:record + 4], bytes.fromhex("00 3c 00 00"))
        self.assertIn((record + pointer_offset, pointer_relocation,
                       b"DirectSoundWaveData_sc88pro_xylophone"), relocations)

    def test_production_includes_32bit(self):
        self.check_pipeline(self.gnu_compiler, "i386-linux-gnu", False, 3, 1)

    def test_production_includes_64bit(self):
        self.check_pipeline(self.gnu_compiler, "x86_64-linux-gnu", True, 62, 1)

    @unittest.skipUnless(shutil.which("clang"), "clang required for Android assembler check")
    def test_production_includes_aarch64(self):
        self.check_pipeline(shutil.which("clang"), "aarch64-linux-android24", True, 183, 257)


if __name__ == "__main__":
    unittest.main()
