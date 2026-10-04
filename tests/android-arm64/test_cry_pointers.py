"""Exercise packed cry bytecode and the production XCMD wave decoder."""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('gcc'), 'GCC required')
class CryPointerTests(unittest.TestCase):
    def test_native_pointer_has_no_opcode_padding(self):
        header = (ROOT / 'include/gba/m4a_internal.h').read_text()
        declaration = re.search(r'struct PokemonCrySong\n\{.*?\n\};', header, re.S).group()
        source = (ROOT / 'src/m4a.c').read_text()
        decoder = re.search(r'void ply_xwave\([^\n]*\)\n\{.*?\n\}', source, re.S).group()
        program = '''
        #include <assert.h>
        #include <stddef.h>
        #include <stdint.h>
        #include <string.h>
        typedef uint8_t u8;
        typedef uint16_t u16;
        typedef uint32_t u32;
        struct WaveData { u8 byte; };
        struct ToneData { struct WaveData *wav; };
        struct MusicPlayerInfo { int unused; };
        struct MusicPlayerTrack { struct ToneData tone; u8 *cmdPtr; };
        ''' + declaration + '\n' + decoder + '''
        int main(void) {
            static struct PokemonCrySong cry;
            assert(offsetof(struct PokemonCrySong, gotoTarget) ==
                   offsetof(struct PokemonCrySong, gotoCmd) + 1);
            assert(offsetof(struct PokemonCrySong, part1) ==
                   offsetof(struct PokemonCrySong, gotoTarget) + sizeof(cry.gotoTarget));
            assert(offsetof(struct PokemonCrySong, unkCmd0DParam) ==
                   offsetof(struct PokemonCrySong, unkCmd0D) + 2);
            assert(sizeof(cry.unkCmd0DParam) == 4);
            cry.gotoTarget = (uintptr_t)cry.cont;
            uintptr_t decoded = 0;
            memcpy(&decoded, (u8 *)&cry.gotoCmd + 1, sizeof(cry.gotoTarget));
            assert(decoded == (uintptr_t)cry.cont);
            u8 bytes[sizeof(uintptr_t) + 1];
            uintptr_t pointer = (uintptr_t)cry.cont;
            memcpy(bytes, &pointer, sizeof(cry.gotoTarget));
            struct MusicPlayerTrack track = {.cmdPtr = bytes};
            ply_xwave(NULL, &track);
            assert(track.tone.wav == (void *)cry.cont);
            assert(track.cmdPtr == bytes + sizeof(cry.gotoTarget));
        }
        '''
        # Legacy READ_XCMD_BYTE is intentionally unchanged; provide its
        # production definition when compiling that decoder branch.
        macro = re.search(r'#define READ_XCMD_BYTE\(var, n\).*?\n\}', source, re.S).group()
        program = macro + '\n' + program
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            c = directory / 'check.c'
            c.write_text(program)
            for label, flags in [('native', ['-DPORTABLE_64BIT', '-fPIE', '-pie']),
                                 ('legacy', ['-DUBFIX', '-fno-pie', '-no-pie'])]:
                with self.subTest(label=label):
                    binary = directory / label
                    subprocess.run(['gcc', '-std=gnu11', '-fsanitize=undefined', '-fno-sanitize-recover=undefined',
                                    '-Wno-int-to-pointer-cast', *flags,
                                    str(c), '-o', str(binary)], check=True)
                    subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
