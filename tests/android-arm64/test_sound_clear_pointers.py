"""Exercise production SoundClear with native pointers and real channel layouts."""
from pathlib import Path
import os
import platform
import shutil
import subprocess
import tempfile
import unittest

from test_music_mixer_layout import PREFIX, extract_struct


def extract_function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


@unittest.skipUnless(shutil.which("gcc"), "requires GNU C compiler")
class SoundClearPointerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]
        self.temp = tempfile.TemporaryDirectory(prefix="sound-clear-pointers-")
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        header = (self.root / "include/gba/m4a_internal.h").read_text()
        self.definitions = "\n".join(extract_struct(header, name)
            for name in ("ToneData", "CgbChannel", "SoundChannel", "SoundInfo"))
        self.function = extract_function((self.root / "src/m4a.c").read_text(),
                                         "void SoundClear(void)")
        self.stubs = "\n#define ID_NUMBER 0x68736D53\nstatic struct SoundInfo *SOUND_INFO_PTR;\n"

    def compile(self, code, name, flags):
        source = self.out / (name + ".c")
        binary = self.out / name
        source.write_text(code)
        result = subprocess.run(["gcc", "-std=gnu11", *flags, str(source),
                                 "-o", str(binary)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return binary

    def test_clears_all_native_channels_without_changing_other_data(self):
        main = r"""
#include <assert.h>
static unsigned osc_count;
static void osc_off(u8 channel) { assert(channel == ++osc_count); }
int main(void) {
    struct SoundInfo *info = malloc(sizeof(*info));
    struct SoundInfo *expected = malloc(sizeof(*expected));
    struct CgbChannel *cgb = malloc(4 * sizeof(*cgb));
    struct CgbChannel expected_cgb[4];
    assert(info && expected && cgb);
    if (sizeof(void *) > 4) {
        assert((uintptr_t)info > UINT32_MAX);
        assert((uintptr_t)cgb > UINT32_MAX);
    }
    memset(info, 0xa5, sizeof(*info));
    memset(cgb, 0x5a, 4 * sizeof(*cgb));
    info->ident = ID_NUMBER;
    info->cgbChans = cgb;
    info->CgbOscOff = osc_off;
    memcpy(expected, info, sizeof(*info));
    memcpy(expected_cgb, cgb, sizeof(expected_cgb));
    for (unsigned i=0; i<MAX_DIRECTSOUND_CHANNELS; ++i)
        expected->chans[i].statusFlags = 0;
    for (unsigned i=0; i<4; ++i) expected_cgb[i].statusFlags = 0;
    SOUND_INFO_PTR = info;
    SoundClear();
    assert(osc_count == 4);
    assert(memcmp(info, expected, sizeof(*info)) == 0);
    assert(memcmp(cgb, expected_cgb, sizeof(expected_cgb)) == 0);

    // The locked-engine guard must leave both arrays and the identifier alone.
    info->ident = ID_NUMBER + 1;
    memcpy(expected, info, sizeof(*info));
    SoundClear();
    assert(osc_count == 4);
    assert(memcmp(info, expected, sizeof(*info)) == 0);
    assert(memcmp(cgb, expected_cgb, sizeof(expected_cgb)) == 0);

    // A mixer without PSG channels still clears every PCM channel.
    info->ident = ID_NUMBER;
    info->cgbChans = NULL;
    for (unsigned i=0; i<MAX_DIRECTSOUND_CHANNELS; ++i)
        info->chans[i].statusFlags = 0xff;
    memcpy(expected, info, sizeof(*info));
    for (unsigned i=0; i<MAX_DIRECTSOUND_CHANNELS; ++i)
        expected->chans[i].statusFlags = 0;
    SoundClear();
    assert(osc_count == 4);
    assert(memcmp(info, expected, sizeof(*info)) == 0);
    free(cgb);
    free(expected);
    free(info);
    return 0;
}
"""
        binary = self.compile(PREFIX + self.definitions + self.stubs + self.function + main,
                              "sound-clear-native", ("-O1", "-g", "-fsanitize=address",
                                                     "-fno-omit-frame-pointer"))
        result = subprocess.run([str(binary)], text=True, capture_output=True,
                                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sound_clear_still_compiles_for_32bit(self):
        if platform.machine() not in ("x86_64", "AMD64"):
            self.skipTest("requires x86 compiler -m32 support")
        # Use the existing declaration fixture without libc headers/libraries.
        prefix = PREFIX[PREFIX.index("typedef uint8_t"):]
        types = ("typedef __UINT8_TYPE__ uint8_t; typedef __INT8_TYPE__ int8_t;\n"
                 "typedef __UINT16_TYPE__ uint16_t; typedef __INT16_TYPE__ int16_t;\n"
                 "typedef __UINT32_TYPE__ uint32_t; typedef __INT32_TYPE__ int32_t;\n"
                 "typedef __UINT64_TYPE__ uint64_t;\n"
                 "typedef __INT_FAST8_TYPE__ int_fast8_t;\n"
                 "typedef __UINT_FAST8_TYPE__ uint_fast8_t;\n"
                 "typedef __INT_FAST16_TYPE__ int_fast16_t;\n"
                 "typedef __UINT_FAST16_TYPE__ uint_fast16_t;\n")
        checks = '_Static_assert(sizeof(void *) == 4, "expected 32-bit compiler");\n'
        self.compile(types + prefix + self.definitions + self.stubs + self.function + checks,
                     "sound-clear32", ("-m32", "-fsyntax-only", "-Werror"))


if __name__ == "__main__":
    unittest.main()
