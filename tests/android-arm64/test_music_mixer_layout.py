"""Check the native structs that alias the same audio state allocation."""
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

PREFIX = r"""
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8; typedef int8_t s8; typedef uint16_t u16; typedef int16_t s16;
typedef uint32_t u32; typedef int32_t s32; typedef uint64_t u64;
typedef volatile u8 vu8; typedef volatile u32 vu32;
typedef u8 bool8; typedef u16 bool16; typedef u32 bool32;
typedef int_fast8_t sf8; typedef uint_fast8_t uf8;
typedef int_fast16_t sf16; typedef uint_fast16_t uf16;
struct MusicPlayerInfo; struct MusicPlayerTrack; struct MP2KPlayerState;
struct MP2KTrack; struct WaveData2;
typedef void (*MPlayFunc)();
typedef void (*PlyNoteFunc)(u32,struct MusicPlayerInfo*,struct MusicPlayerTrack*);
typedef void (*CgbSoundFunc)(void); typedef void (*CgbOscOffFunc)(u8);
typedef u32 (*MidiKeyToCgbFreqFunc)(u8,u8,u8); typedef void (*ExtVolPitFunc)(void);
typedef void (*MPlayMainFunc)(struct MusicPlayerInfo*);
#define MAX_DIRECTSOUND_CHANNELS 12
#define MAX_SAMPLE_CHANNELS 12
#define PCM_DMA_BUF_SIZE 4907
#define MIXED_AUDIO_BUFFER_SIZE 4907
#define MIXER_UNLOCKED 0x68736D53
#define MIXER_LOCKED (MIXER_UNLOCKED+1)
#define VCOUNT_VBLANK 160
#define TOTAL_SCANLINES 228
#define REG_VCOUNT 0
"""

def extract_struct(text, name):
    """Use definitions from the headers rather than duplicating their layout."""
    start = re.search(r"(?m)^struct " + re.escape(name) + r"\b[^;{]*\{", text).start()
    brace = text.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:text.index(";", end) + 1]

@unittest.skipUnless(shutil.which("gcc"), "requires GNU C compiler")
class MusicMixerLayoutTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]
        self.temp = tempfile.TemporaryDirectory(prefix="music-mixer-layout-")
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        old = (self.root / "include/gba/m4a_internal.h").read_text()
        new = (self.root / "include/sound_mixer.h").read_text()
        music = (self.root / "include/music_player.h").read_text()
        self.definitions = "".join(extract_struct(text, name) + "\n"
            for text, name in (
                (old, "ToneData"), (old, "CgbChannel"), (old, "SoundChannel"),
                (old, "SoundInfo"), (old, "MusicPlayerTrack"), (old, "MusicPlayerInfo"),
                (new, "MixerSource"), (new, "SoundMixerState"),
                (music, "MP2KInstrument"), (music, "MP2KTrack"),
                (music, "MP2KPlayerState")))

    def compile(self, text, name, flags=()):
        source = self.out / (name + ".c")
        binary = self.out / name
        source.write_text(text)
        result = subprocess.run(["gcc", "-std=gnu11", *flags, str(source),
                                 "-o", str(binary)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return binary

    def test_audio_aliases_share_native_offsets_and_sizes(self):
        pairs = (
            ("SoundInfo", "SoundMixerState", "chans", "chans"),
            ("SoundInfo", "SoundMixerState", "pcmBuffer", "outBuffer"),
            ("SoundInfo", "SoundMixerState", "plynote", "mp2kEventNxxFunc"),
            ("SoundInfo", "SoundMixerState", "MPlayJumpTable", "mp2kEventFuncTable"),
            ("ToneData", "MP2KInstrument", "wav", "wav"),
            ("ToneData", "MP2KInstrument", "attack", "attack"),
            ("SoundChannel", "MixerSource", "frequency", "freq"),
            ("SoundChannel", "MixerSource", "wav", "wav"),
            ("SoundChannel", "MixerSource", "track", "track"),
            ("CgbChannel", "MixerSource", "wavePointer", "newCgb3Sample"),
            ("CgbChannel", "MixerSource", "track", "track"),
            ("MusicPlayerTrack", "MP2KTrack", "tone", "instrument"),
            ("MusicPlayerTrack", "MP2KTrack", "cmdPtr", "cmdPtr"),
            ("MusicPlayerInfo", "MP2KPlayerState", "tracks", "tracks"),
            ("MusicPlayerInfo", "MP2KPlayerState", "tone", "voicegroup"),
            ("MusicPlayerInfo", "MP2KPlayerState", "ident", "lockStatus"),
        )
        checks = "".join(
            f'_Static_assert(offsetof(struct {a},{x}) == offsetof(struct {b},{y}),'
            f'"{a}.{x} differs from {b}.{y}");\n' for a,b,x,y in pairs)
        for a,b in (("SoundInfo","SoundMixerState"), ("ToneData","MP2KInstrument"),
                    ("SoundChannel","MixerSource"), ("CgbChannel","MixerSource"),
                    ("MusicPlayerTrack","MP2KTrack"), ("MusicPlayerInfo","MP2KPlayerState")):
            checks += (f'_Static_assert(sizeof(struct {a}) == sizeof(struct {b}),'
                       f'"{a}/{b} size differs");\n')
        self.compile(PREFIX + self.definitions + checks + "int main(void){return 0;}",
                     "audio-layout")

    def test_32bit_audio_layout_remains_compatible(self):
        if platform.machine() not in ("x86_64", "AMD64"):
            self.skipTest("requires x86 compiler -m32 support")
        # No system headers or linker libraries are needed for this syntax check.
        prefix = PREFIX[PREFIX.index("typedef uint8_t"):]
        types = ("#define offsetof(T,F) __builtin_offsetof(T,F)\n"
                 "typedef __UINT8_TYPE__ uint8_t; typedef __INT8_TYPE__ int8_t;\n"
                 "typedef __UINT16_TYPE__ uint16_t; typedef __INT16_TYPE__ int16_t;\n"
                 "typedef __UINT32_TYPE__ uint32_t; typedef __INT32_TYPE__ int32_t;\n"
                 "typedef __UINT64_TYPE__ uint64_t;\n"
                 "typedef __INT_FAST8_TYPE__ int_fast8_t;\n"
                 "typedef __UINT_FAST8_TYPE__ uint_fast8_t;\n"
                 "typedef __INT_FAST16_TYPE__ int_fast16_t;\n"
                 "typedef __UINT_FAST16_TYPE__ uint_fast16_t;\n")
        checks = r"""
_Static_assert(sizeof(void*) == 4,"expected 32-bit compiler");
_Static_assert(sizeof(((struct SoundInfo*)0)->gap2) == 16,"legacy gap differs");
_Static_assert(offsetof(struct SoundInfo,chans) == 80,"legacy channel offset differs");
_Static_assert(offsetof(struct SoundMixerState,chans) == 80,"legacy mixer offset differs");
_Static_assert(sizeof(struct SoundInfo) == sizeof(struct SoundMixerState),"legacy sizes differ");
"""
        self.compile(types + prefix + self.definitions + checks,
                     "audio-layout32", ("-m32", "-fsyntax-only"))

    def test_mixer_frame_fits_the_sound_info_allocation(self):
        mixer = (self.root / "src/sound_mixer.c").read_text()
        bodies = mixer[mixer.index("void RunMixerFrame(void)"):
                       mixer.index("// Returns TRUE if channel")]
        stubs = r"""
static struct SoundInfo *allocated;
#define SOUND_INFO_PTR allocated
static inline bool32 TickEnvelope(struct MixerSource*c,struct WaveData2*w){return 0;}
static inline void GenerateAudio(struct SoundMixerState*m,struct MixerSource*c,
 struct WaveData2*w,float*b,u16 s,float f){}
void SampleMixer(struct SoundMixerState*,u32,u16,float*,u8,u16);
static void noop(void){}
"""
        main = r"""
int main(void) {
 allocated=malloc(sizeof(*allocated));
 memset(allocated,0,sizeof(*allocated));
 allocated->ident=MIXER_UNLOCKED;
 // Match the portable production geometry: seven frames of 701 samples.
 allocated->pcmSamplesPerVBlank=701;
 allocated->pcmDmaPeriod=PCM_DMA_BUF_SIZE / allocated->pcmSamplesPerVBlank;
 allocated->CgbSound=noop;
 for (u8 counter=allocated->pcmDmaPeriod; counter!=0; --counter) {
  allocated->pcmDmaCounter=counter;
  RunMixerFrame();
 }
 free(allocated);
 return 0;
}
"""
        binary = self.compile(PREFIX + self.definitions + stubs + bodies + main,
                              "mixer-frame", ("-O1", "-g", "-fsanitize=address",
                                              "-fno-omit-frame-pointer"))
        result = subprocess.run([str(binary)], text=True, capture_output=True,
                                env={**os.environ, "ASAN_OPTIONS":"detect_leaks=0"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == "__main__":
    unittest.main()
