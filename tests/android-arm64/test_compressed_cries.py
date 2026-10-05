"""Run the production BDPCM decoder and cry playback with bounded assets."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def function(source, signature):
    start = source.index(signature)
    # Skip the forward declaration and find the function definition.
    while source.find(';', start) < source.find('{', start):
        start = source.index(signature, start + len(signature))
    opening = source.index('{', start)
    depth = 1
    cursor = opening + 1
    while depth:
        depth += (source[cursor] == '{') - (source[cursor] == '}')
        cursor += 1
    return source[start:cursor]


@unittest.skipUnless(shutil.which('gcc'), 'GCC required')
class CompressedCryTests(unittest.TestCase):
    def run_native(self, main):
        source = (ROOT / 'src/sound_mixer.c').read_text()
        mixer_header = (ROOT / 'include/sound_mixer.h').read_text()
        tables = (ROOT / 'src/m4a_tables.c').read_text()
        channel = re.search(r'struct MixerSource \{.*?\n\};', mixer_header, re.S).group()
        wave = re.search(r'struct WaveData\n\{.*?\n\};', source, re.S).group()
        deltas = re.search(r'const s8 gDeltaEncodingTable\[\] =\n\{.*?\n\};', tables, re.S).group()
        program = '''
        #include <assert.h>
        #include <stdint.h>
        #include <stdlib.h>
        #include <string.h>
        typedef uint8_t u8; typedef int8_t s8;
        typedef uint16_t u16; typedef int16_t s16;
        typedef uint32_t u32; typedef int32_t s32;
        typedef int_fast16_t sf16;
        struct SoundMixerState { int unused; };
        #define DBGPRINTF(...) ((void)0)
        ''' + wave + channel + deltas + '''
        s8 gBDPCMBlockBuffer[64];
        static s8 sub_82DF758(struct MixerSource *, u32);
        ''' + function(source, 'static s8 sub_82DF758(') + '\n' + function(
            source, 'void GeneratePokemonSampleAudio(') + '''
        static struct WaveData *make_wave(u32 count) {
            u32 full = count / 64, tail = count % 64;
            u32 bytes = full * 33;
            if (tail) bytes += 1;
            if (tail > 1) bytes += 1 + (tail - 1) / 2;
            struct WaveData *wav = calloc(1, 16 + bytes);
            assert(wav != NULL);
            wav->type = 1;
            wav->size = count - 1; // aif2pcm includes a lookahead sample.
            for (u32 block = 0; block < full + (tail != 0); ++block)
                wav->data[block * 33] = 13;
            return wav;
        }
        ''' + main
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path = directory / 'cry.c'
            binary = directory / 'cry'
            path.write_text(program)
            subprocess.run(['gcc', '-std=gnu11', '-O1', '-g', '-DPORTABLE_64BIT',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-fno-pie', '-no-pie', str(path), '-o', str(binary)], check=True)
            # LeakSanitizer cannot run in ptrace-based build sandboxes.
            result = subprocess.run([str(binary)], capture_output=True, text=True,
                                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_full_and_partial_blocks_stay_in_asset(self):
        self.run_native('''
        int main(void) {
            const u32 counts[] = {1, 2, 3, 37, 38, 63, 64, 65, 66, 127, 128, 129, 2150};
            for (u32 test = 0; test < sizeof(counts) / sizeof(counts[0]); ++test) {
                u32 count = counts[test];
                struct WaveData *wav = make_wave(count);
                struct MixerSource chan = {.wav = wav, .blockCount = UINT32_MAX};
                for (u32 index = count; index-- != 0;)
                    assert(sub_82DF758(&chan, index) == 13);
                assert(sub_82DF758(&chan, count) == 0);
                assert(sub_82DF758(&chan, UINT32_MAX) == 0);
                free(wav);
            }
            return 0;
        }
        ''')

    def test_forward_and_reverse_partial_cry_playback(self):
        self.run_native('''
        int main(void) {
            for (u8 reversed = 0; reversed <= 1; ++reversed) {
                struct WaveData *wav = make_wave(2150); // Lotad's real sample count.
                struct MixerSource chan = {.wav = wav, .current = wav->data,
                    .ct = wav->size, .status = 3, .type = reversed ? 0x30 : 0x20,
                    .freq = 1};
                for (u32 frame = 0; frame < 200 && chan.status; ++frame) {
                    float out[38] = {0};
                    GeneratePokemonSampleAudio(NULL, &chan, chan.current, out,
                                               19, 1.0f, chan.ct, 127, 127, 0);
                }
                assert(chan.status == 0);
                free(wav);
            }
            return 0;
        }
        ''')

    def test_compressed_loop_keeps_sample_index(self):
        self.run_native('''
        int main(void) {
            struct WaveData *wav = make_wave(128);
            wav->loopStart = 5;
            struct MixerSource chan = {.wav = wav, .current = wav->data,
                .ct = wav->size, .status = 3, .type = 0x20, .freq = 1};
            for (u32 frame = 0; frame < 20; ++frame) {
                float out[64] = {0};
                GeneratePokemonSampleAudio(NULL, &chan, chan.current, out,
                                           32, 1.0f, chan.ct, 127, 127,
                                           wav->size - wav->loopStart);
                assert(chan.status != 0);
                assert((uintptr_t)chan.current <= wav->size);
                for (u32 index = 0; index < 64; ++index)
                    assert(out[index] == 13.0f * 127.0f / 32768.0f);
            }
            free(wav);
            return 0;
        }
        ''')


if __name__ == '__main__':
    unittest.main()
