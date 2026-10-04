"""Exercise production Mystery Event relocation with four-byte wire addresses."""

import ctypes
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


def production_function(path, name):
    source = (ROOT / path).read_text()
    match = re.search(
        r"^(?:static )?[\w ]+\b" + re.escape(name) + r"\([^\n]*\)\n\{",
        source,
        re.MULTILINE,
    )
    if match is None:
        raise AssertionError(f"Production function {name} was not found in {path}")
    cursor = source.index("{", match.start()) + 1
    depth = 1
    while depth:
        depth += (source[cursor] == "{") - (source[cursor] == "}")
        cursor += 1
    return source[match.start():cursor]


class MysteryEventPointerTests(unittest.TestCase):
    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8, "requires a 64-bit host")
    def test_wire_address_relocates_above_four_gib(self):
        compiler = shutil.which("cc") or shutil.which("gcc")
        if compiler is None:
            self.skipTest("a native C compiler is required")

        prefix = r"""
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef u8 bool8;
typedef u32 bool32;
#define FALSE 0
#define MEVENT_STATUS_LOAD_OK 0
#define MEVENT_STATUS_SUCCESS 2
#include "script.h"
#define mScriptBase data[0]
#define mOffset data[1]
#define mStatus data[2]
#define mValid data[3]

ScrCmdFunc gMysteryEventScriptCmdTable[1], gMysteryEventScriptCmdTableEnd[1];
struct SaveBlock2 {
    struct { unsigned char ereaderTrainer[16]; } frontier;
} save, *gSaveBlock2Ptr = &save;
u8 gStringVar4[16], gText_MysteryEventNewTrainer[16];
static int validated, expanded;

void InitScriptContext(struct ScriptContext *ctx, void *table, void *tableEnd)
{
    memset(ctx, 0, sizeof(*ctx));
}
u8 SetupBytecodeScript(struct ScriptContext *ctx, const u8 *script)
{
    ctx->scriptPtr = script;
    return 0;
}
void ValidateEReaderTrainer(void) { validated++; }
void StringExpandPlaceholders(u8 *dest, const u8 *src) { expanded++; }
"""
        suffix = r"""
int main(void)
{
    u8 payload[64] = {0};
    struct ScriptContext ctx;
    const u32 wireAddress = 0x02000010;
    for (int i = 0; i < 4; i++)
        payload[i] = (u8)(wireAddress >> (8 * i));
    for (int i = 0; i < 16; i++)
        payload[16 + i] = (u8)(i + 1);

    assert((uintptr_t)payload > UINT32_MAX);
    InitMysteryEventScript(&ctx, payload);
    assert(ctx.mScriptBase == (uintptr_t)payload);
    ctx.mOffset = 0x02000000;
    MEScrCmd_addtrainer(&ctx);
    assert(ctx.scriptPtr == payload + 4);
    assert(memcmp(save.frontier.ereaderTrainer, payload + 16, 16) == 0);
    assert(ctx.mStatus == MEVENT_STATUS_SUCCESS);
    assert(validated == 1 && expanded == 1);
    puts("PASS: four-byte wire address relocates above 4 GiB");
    return 0;
}
"""
        source = "\n".join([
            prefix,
            production_function("src/script.c", "ScriptReadWord"),
            production_function("src/mystery_event_script.c", "InitMysteryEventScript"),
            production_function("src/mystery_event_script.c", "MEScrCmd_addtrainer"),
            suffix,
        ])
        with tempfile.TemporaryDirectory(prefix="mystery-event-pointer-") as directory:
            temporary = Path(directory)
            source_path = temporary / "pointer_check.c"
            executable = temporary / "pointer_check"
            source_path.write_text(source)
            subprocess.run([
                compiler, "-std=gnu11", "-DPORTABLE_64BIT",
                "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
                "-iquote", str(ROOT / "include"), str(source_path), "-o", str(executable),
            ], check=True, capture_output=True, text=True)
            result = subprocess.run(
                [str(executable)], check=True, capture_output=True, text=True,
            )
            self.assertIn("PASS: four-byte wire address relocates above 4 GiB", result.stdout)


if __name__ == "__main__":
    unittest.main()
