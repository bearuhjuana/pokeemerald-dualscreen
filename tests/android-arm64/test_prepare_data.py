"""Check song ABI layouts with real native pointers and assembler relocations."""

import ctypes
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
import sys
from pathlib import Path


HELPER = Path(__file__).resolve().parents[2] / "android/app/src/main/cpp/prepare_data.py"
SPEC = importlib.util.spec_from_file_location("prepare_data", HELPER)
prepare_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_data)

SONG = """.section .data
.global tune
.align 2
tune_1:
.byte 0xb2
{pointer} tune_1
.align 2
tune:
.byte 1
.byte 0
.byte 5
.byte 50
{padding}{pointer} voice
{pointer} tune_1
.end
"""


@unittest.skipUnless(shutil.which("gcc") and shutil.which("as"), "host compiler/binutils required")
class SongLayoutTests(unittest.TestCase):
    def test_host_cli_emits_same_song_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "song.s"
            output = directory / "song64.s"
            text = SONG.format(pointer=".4byte", padding="")
            source.write_text(text)
            subprocess.run([sys.executable, str(HELPER), "--song-only", "--portable-64bit",
                            "--source", str(source), "--output", str(output)], check=True)
            self.assertEqual(output.read_text(), prepare_data.prepare_song(text, True))

    def test_native_song_header_and_unaligned_track_pointer(self):
        class Header(ctypes.Structure):
            _fields_ = [("tracks", ctypes.c_uint8), ("blocks", ctypes.c_uint8),
                        ("priority", ctypes.c_uint8), ("reverb", ctypes.c_uint8),
                        ("tone", ctypes.c_void_p), ("track", ctypes.c_void_p)]

        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 8)
        for pointer, padding in [(".int", ""), (".4byte", ""), (".8byte", ""),
                                 (".8byte", ".space 4\n")]:
            with self.subTest(pointer=pointer, padding=padding), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                assembly = directory / "song.s"
                assembly.write_text(prepare_data.prepare_song(SONG.format(pointer=pointer, padding=padding), True)
                                    + '.section .note.GNU-stack,"",@progbits\n')
                voice = directory / "voice.c"
                voice.write_text("unsigned char voice = 0;\n")
                library = directory / "song.so"
                subprocess.run(["gcc", "-shared", "-fPIC", str(assembly), str(voice), "-o", str(library)], check=True)
                native = ctypes.CDLL(str(library))
                header = Header.in_dll(native, "tune")
                self.assertEqual((header.tracks, header.blocks, header.priority, header.reverb), (1, 0, 5, 50))
                self.assertEqual(header.tone, ctypes.addressof(ctypes.c_uint8.in_dll(native, "voice")))
                self.assertEqual(ctypes.string_at(header.track, 1), b"\xb2")
                branch_pointer = int.from_bytes(ctypes.string_at(header.track + 1, 8), "little")
                self.assertEqual(branch_pointer, header.track)

    def test_32bit_song_keeps_legacy_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            assembly = directory / "song.s"
            assembly.write_text(prepare_data.prepare_song(SONG.format(pointer=".4byte", padding=""), False))
            obj = directory / "song.o"
            subprocess.run(["as", "--32", str(assembly), "-o", str(obj)], check=True)
            binary = directory / "song.bin"
            subprocess.run(["objcopy", "-O", "binary", str(obj), str(binary)], check=True)
            self.assertEqual(len(binary.read_bytes()), 20)
            self.assertEqual(binary.read_bytes()[8:12], bytes([1, 0, 5, 50]))

    def test_prepared_64bit_song_can_return_to_32bit(self):
        original = SONG.format(pointer=".4byte", padding="")
        native = prepare_data.prepare_song(original, True)
        legacy = prepare_data.prepare_song(native, False)
        binaries = []
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for label, text in [('original', original), ('converted', legacy)]:
                assembly = directory / (label + '.s')
                obj = directory / (label + '.o')
                binary = directory / (label + '.bin')
                assembly.write_text(prepare_data.prepare_song(text, False))
                subprocess.run(['as', '--32', str(assembly), '-o', str(obj)], check=True)
                subprocess.run(['objcopy', '-O', 'binary', str(obj), str(binary)], check=True)
                binaries.append(binary.read_bytes())
        self.assertEqual(binaries[0], binaries[1])
        self.assertEqual(len(binaries[1]), 20)

    def test_unknown_header_layout_fails(self):
        song = SONG.format(pointer=".int", padding="").replace(".byte 50", ".short 50")
        with self.assertRaisesRegex(ValueError, "Unexpected SongHeader"):
            prepare_data.prepare_song(song, True)


if __name__ == "__main__":
    unittest.main()
