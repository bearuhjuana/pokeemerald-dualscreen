"""Exercise the title scanline DMA through the production portable DMA code."""

from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPILER = shutil.which("gcc") or shutil.which("cc")

# No system headers are needed by dma.c. This also allows the legacy -m32
# syntax check on hosts without a 32-bit C runtime installed.
GLOBAL_STUB = r"""
#ifndef TEST_GLOBAL_H
#define TEST_GLOBAL_H
typedef __UINT8_TYPE__ u8;
typedef u8 bool8;
typedef __UINT16_TYPE__ u16;
typedef __UINT32_TYPE__ u32;
typedef volatile u16 vu16;
typedef volatile u32 vu32;
typedef __UINTPTR_TYPE__ uintptr_t;
#define PORTABLE 1
#define DBGPRINTF(...) ((void)0)
#define ALIGNED(n) __attribute__((aligned(n)))
#include "gba/io_reg.h"
#endif
"""

HARNESS = r"""
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include "global.h"
#include "scanline_effect.h"
#include "src/platform/dma.c"

unsigned char REG_BASE[0x400] __attribute__((aligned(4)));

static void reset(void)
{
    memset(REG_BASE, 0, sizeof(REG_BASE));
    memset(DMAList, 0, sizeof(DMAList));
}

static void full_frame_16(void)
{
    u16 source[161];
    for (unsigned int i = 0; i < 161; ++i)
        source[i] = 100 + i;
    void *dest = (void *)REG_ADDR_BG1HOFS;
    assert((uintptr_t)dest > UINT32_MAX);
    assert(SCANLINE_EFFECT_DMACNT_16BIT == 0xa2600001u);
    DmaSet(0, source + 1, dest, SCANLINE_EFFECT_DMACNT_16BIT);
    assert(REG_BG1HOFS == 0);  /* HBlank DMA has not fired yet. */
    assert(REG_DMA0DAD == (u32)(uintptr_t)dest);
    for (unsigned int i = 0; i < 160; ++i)
    {
        RunDMAs(DMA_HBLANK);
        assert(REG_BG1HOFS == source[i + 1]);
        assert(REG_BG1VOFS == 0);
    }
    assert(DMAList[0].src16 == source + 161);
    assert(DMAList[0].dst == dest);
}

static void full_frame_32(void)
{
    u32 source[161];
    for (unsigned int i = 0; i < 161; ++i)
        source[i] = 0x12340000u + i;
    void *dest = (void *)REG_ADDR_BG1HOFS;
    assert((uintptr_t)dest > UINT32_MAX);
    DmaSet(0, source + 1, dest, SCANLINE_EFFECT_DMACNT_32BIT);
    for (unsigned int i = 0; i < 160; ++i)
    {
        RunDMAs(DMA_HBLANK);
        assert(*(vu32 *)dest == source[i + 1]);
        assert(REG_BG2HOFS == 0);
    }
    assert(DMAList[0].src32 == source + 161);
    assert(DMAList[0].dst == dest);
}

static void reconfigure_and_control(void)
{
    u16 sourceA[] = {1, 2, 3, 4};
    u16 sourceB[] = {11, 12, 13, 14};
    DmaSet(0, sourceA, (void *)REG_ADDR_BG1HOFS, SCANLINE_EFFECT_DMACNT_16BIT);
    RunDMAs(DMA_HBLANK);
    assert(REG_BG1HOFS == 1);
    DmaSet(0, sourceB, (void *)REG_ADDR_BG2HOFS, SCANLINE_EFFECT_DMACNT_16BIT);
    DmaSet(1, sourceA, (void *)REG_ADDR_BG3HOFS, SCANLINE_EFFECT_DMACNT_16BIT);
    RunDMAs(DMA_HBLANK);
    RunDMAs(DMA_HBLANK);
    assert(REG_BG1HOFS == 1);
    assert(REG_BG2HOFS == 12);
    assert(REG_BG3HOFS == 2);
    assert(DMAList[0].dst == (void *)REG_ADDR_BG2HOFS);
    assert(DMAList[1].dst == (void *)REG_ADDR_BG3HOFS);
    REG_DMA0CNT = 0;  /* Existing register-based DmaStop behavior. */
    REG_DMA1CNT = 0;
    RunDMAs(DMA_HBLANK);
    assert(REG_BG2HOFS == 12);
    assert(REG_BG3HOFS == 2);

    u32 once = (DMA_ENABLE | DMA_START_HBLANK | DMA_SRC_INC | DMA_DEST_RELOAD) << 16 | 1;
    DmaSet(2, sourceA, (void *)REG_ADDR_BG0HOFS, once);
    RunDMAs(DMA_HBLANK);
    RunDMAs(DMA_HBLANK);
    assert(REG_BG0HOFS == 1);
    assert(DMAList[2].src16 == sourceA + 1);

    u16 copy16[4] = {0};
    u32 src32[3] = {100, 200, 300}, copy32[3] = {0};
    DmaSet(3, sourceA, copy16, (DMA_ENABLE | DMA_START_NOW | DMA_SRC_INC | DMA_DEST_INC) << 16 | 4);
    assert(memcmp(sourceA, copy16, sizeof(copy16)) == 0);
    DmaSet(3, src32, copy32, (DMA_ENABLE | DMA_START_NOW | DMA_32BIT | DMA_SRC_INC | DMA_DEST_INC) << 16 | 3);
    assert(memcmp(src32, copy32, sizeof(copy32)) == 0);
}

static void legacy_register_reload(void)
{
#ifdef MAP_32BIT
    unsigned char *low = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
                             MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    assert(low != MAP_FAILED);
    assert((uintptr_t)low <= UINT32_MAX - 4096);
    u16 *src = (u16 *)low;
    u16 *dest = (u16 *)(low + 512);
    u16 *newDest = (u16 *)(low + 1024);
    src[0] = 5; src[1] = 6; src[2] = 7;
    DmaSet(0, src, dest, SCANLINE_EFFECT_DMACNT_16BIT);
    RunDMAs(DMA_HBLANK);
    assert(*dest == 5);
    /* The unmodified 32-bit fallback still honors DAD register updates. */
    REG_DMA0DAD = (u32)(uintptr_t)newDest;
    RunDMAs(DMA_HBLANK);
    RunDMAs(DMA_HBLANK);
    assert(*dest == 6);
    assert(*newDest == 7);
    munmap(low, 4096);
#else
    abort();
#endif
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    reset();
    if (!strcmp(argv[1], "16")) full_frame_16();
    else if (!strcmp(argv[1], "32")) full_frame_32();
    else if (!strcmp(argv[1], "control")) reconfigure_and_control();
    else if (!strcmp(argv[1], "legacy")) legacy_register_reload();
    else return 2;
    puts("PASS: production DMA transfer behavior");
    return 0;
}
"""


@unittest.skipUnless(COMPILER, "C compiler unavailable")
class DmaPointerReloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="emerald-dma-test-")
        cls.build = Path(cls.temporary.name)
        (cls.build / "global.h").write_text(GLOBAL_STUB)
        (cls.build / "harness.c").write_text(HARNESS)
        # Game headers use quotes; keep them out of libc angle-include search.
        cls.common = [COMPILER, "-std=gnu11", "-O1", "-g", "-fPIE", "-pie",
                      "-iquote", str(cls.build), "-iquote", str(ROOT / "include"), "-iquote", str(ROOT)]
        cls.native = cls.build / "native-dma"
        result = subprocess.run(cls.common + ["-DPORTABLE_64BIT", str(cls.build / "harness.c"),
                                "-o", str(cls.native)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_native(self, mode):
        result = subprocess.run([str(self.native), mode], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_title_hblank_16bit_full_frame(self):
        self.run_native("16")

    def test_hblank_32bit_full_frame(self):
        self.run_native("32")

    def test_reprogram_channels_stop_and_immediate_copy(self):
        self.run_native("control")

    @unittest.skipUnless(platform.machine() in {"x86_64", "i386", "i686"},
                         "-m32 syntax check requires an x86 host")
    def test_legacy_32bit_compile(self):
        result = subprocess.run([COMPILER, "-std=gnu11", "-m32", "-fsyntax-only",
                                 "-iquote", str(self.build), "-iquote", str(ROOT / "include"),
                                 str(ROOT / "src/platform/dma.c")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(platform.machine() == "x86_64", "MAP_32BIT harness requires x86_64")
    def test_legacy_register_reload_behavior(self):
        binary = self.build / "legacy-dma"
        result = subprocess.run(self.common + [str(self.build / "harness.c"), "-o", str(binary)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(binary), "legacy"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
