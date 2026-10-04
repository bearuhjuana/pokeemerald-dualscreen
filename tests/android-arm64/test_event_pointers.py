"""Check production event macros/readers with pointers above 4 GB and legacy operands.

These focused checks complement the full host smoke test. Only the selected
production functions are compiled, so they do not substitute for a game build.
"""

from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

repo = Path(__file__).resolve().parents[2]

def function(path, name):
    source = (repo / path).read_text()
    match = re.search(r'(?m)^(?:static inline |static )?[^\n]+\b' + name + r'\([^\n]*\)\n\{', source)
    assert match, name
    end = match.end()
    level = 1
    while level:
        level += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


@unittest.skipUnless(platform.machine() == "x86_64" and shutil.which("gcc"),
                     "requires native x86_64 GCC")
class EventPointerTests(unittest.TestCase):
    def run_command(self, cmd):
        result = subprocess.run(cmd, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0,
                         " ".join(str(arg) for arg in cmd) + "\n" + result.stdout + result.stderr)
        return result.stdout

    def test_event_pointer_commands(self):
        with tempfile.TemporaryDirectory(prefix="event-pointer-check-") as directory:
            work = Path(directory)
            source = '''
            #include <assert.h>
            #include <stdint.h>
            #include <stdio.h>
            #include <string.h>
            typedef uint8_t u8;
            typedef uint16_t u16;
            typedef uint32_t u32;
            typedef uint64_t u64;
            typedef u8 bool8;
            typedef u32 bool32;
            #define FALSE 0
            #define TRUE 1
            #include "script.h"
            const u8 test_text[] = "event pointer";
            extern const u8 test_loadword[], test_goto[], test_message[], test_setvaddress[], test_vgoto[];
            extern const u8 test_numeric[], test_trainer[];
            static uintptr_t sAddressOffset;
            static const u8 *shown;
            void ShowFieldMessage(const u8 *msg) { shown = msg; }
            '''
            for name in ['ScriptReadWord', 'ScriptReadPointer', 'ScriptJump']:
                source += function('src/script.c', name) + '\n'
            for name in ['ScrCmd_loadword', 'ScrCmd_goto', 'ScrCmd_message', 'ScrCmd_setvaddress', 'ScrCmd_vgoto']:
                source += function('src/scrcmd.c', name) + '\n'

            # Use the actual pointer-read macro and trainer argument decoder.
            global_source = (repo / 'include/global.h').read_text()
            start = global_source.index('#ifdef PORTABLE_64BIT\n#define BS_READ_PTR')
            end = global_source.index('#endif', start) + len('#endif')
            source += '''
            #define T1_READ_8(ptr) ((ptr)[0])
            #define T1_READ_16(ptr) ((ptr)[0] | ((ptr)[1] << 8))
            #define T1_READ_32(ptr) ((ptr)[0] | ((ptr)[1] << 8) | ((ptr)[2] << 16) | ((ptr)[3] << 24))
            #define T2_READ_32(ptr) T1_READ_32(ptr)
            '''
            source += global_source[start:end] + '\n'
            battle = (repo / 'src/battle_setup.c').read_text()
            start = battle.index('enum {\n    TRAINER_PARAM_LOAD_VAL_8BIT')
            end = battle.index('// this file', start)
            source += battle[start:end]
            for name in ['TrainerBattleLoadArg8', 'TrainerBattleLoadArg16', 'TrainerBattleLoadArg32', 'SetU8', 'SetU16', 'SetU32', 'SetPtr', 'TrainerBattleLoadArgs']:
                source += function('src/battle_setup.c', name) + '\n'
            source += '''
            int main(void)
            {
                struct ScriptContext ctx = {0};
            #ifdef PORTABLE_64BIT
                assert((uintptr_t)test_text > UINT32_MAX);
                assert(sizeof(ctx.data[0]) == 8);
            #else
                assert((uintptr_t)test_text <= UINT32_MAX);
                assert(sizeof(ctx.data[0]) == 4);
            #endif
                ctx.scriptPtr = test_loadword + 1;
                ScrCmd_loadword(&ctx);
                assert(ctx.data[0] == (uintptr_t)test_text);
                assert(*ctx.scriptPtr == 0xa5);
                ctx.scriptPtr = test_goto + 1;
                ScrCmd_goto(&ctx);
                assert(ctx.scriptPtr == test_text);
                ctx.scriptPtr = test_message + 1;
                ScrCmd_message(&ctx);
                assert(shown == test_text);
                assert(*ctx.scriptPtr == 0xb6);
                ctx.scriptPtr = test_setvaddress + 1;
                ScrCmd_setvaddress(&ctx);
                assert(sAddressOffset == 0);
                ctx.scriptPtr = test_vgoto + 1;
                ScrCmd_vgoto(&ctx);
                assert(ctx.scriptPtr == test_text);
                ctx.scriptPtr = test_numeric + 1;
                assert(ScriptReadWord(&ctx) == 0x89abcdef);
                assert(*ctx.scriptPtr == 0x12);
                struct { const u8 *pointer; uintptr_t guard; } loaded = {0, 0xcafebabe};
                const u8 *cleared = test_text;
                const u8 *returned = NULL;
                struct TrainerBattleParameter params[] = {
                    {&loaded.pointer, TRAINER_PARAM_LOAD_VAL_32BIT},
                    {&cleared, TRAINER_PARAM_CLEAR_VAL_32BIT},
                    {&returned, TRAINER_PARAM_LOAD_SCRIPT_RET_ADDR},
                };
                TrainerBattleLoadArgs(params, test_trainer);
                assert(loaded.pointer == test_text);
                assert(loaded.guard == 0xcafebabe);
                assert(cleared == NULL);
                assert(*returned == 0xc7);
                puts("PASS: assembled event operands, pointer reads/storage/jumps/messages, relative jumps, numeric word width, trainer pointer load/clear");
                return 0;
            }
            '''
            (work / 'check.c').write_text(source)

            asm = (repo / 'asm/macros/event.inc').read_text()
            # Expand the same assembler include before CPP as the project's preproc -ie does.
            table = (repo / 'data/script_cmd_table.inc').read_text()
            asm = asm.replace('.include "data/script_cmd_table.inc"', '\n' + table)
            asm = (repo / 'asm/macros/asm.inc').read_text() + asm
            asm = '\n'.join(line.split('@', 1)[0] for line in asm.splitlines())
            asm += '''
            .data
            .globl test_loadword, test_goto, test_message, test_setvaddress, test_vgoto, test_numeric, test_trainer
            test_loadword:
            loadword 0, test_text
            .byte 0xa5
            test_goto:
            goto test_text
            test_message:
            message 0
            .byte 0xb6
            test_setvaddress:
            setvaddress test_setvaddress
            test_vgoto:
            vgoto test_text
            test_numeric:
            addmoney 0x89abcdef, 0x12
            test_trainer:
            event_ptr test_text
            .byte 0xc7
            .section .note.GNU-stack,"",@progbits
            '''
            (work / 'check.S').write_text(asm)
            for name, flags in [('64bit', ['-DPORTABLE_64BIT', '-fPIE', '-pie']), ('32bit-operands', ['-fno-pie', '-no-pie'])]:
                out = work / name
                cmd = ['gcc', '-std=gnu11', '-O1', '-g', '-fsanitize=undefined', '-Wall', '-Wextra', '-Wno-unused-function', '-I', str(repo / 'include'), *flags, str(work / 'check.c'), str(work / 'check.S'), '-o', str(out)]
                with self.subTest(operand_mode=name):
                    self.run_command(cmd)
                    self.run_command([str(out)])

    @unittest.skipUnless(shutil.which("readelf") and shutil.which("nm"),
                         "requires GNU readelf and nm")
    def test_command_table_pointer_width(self):
        with tempfile.TemporaryDirectory(prefix="event-table-check-") as directory:
            work = Path(directory)
            source = (repo / "asm/macros/asm.inc").read_text()
            source += "\n.set ALLOCATE_SCRIPT_CMD_TABLE, 1\n.data\n"
            source += (repo / "data/script_cmd_table.inc").read_text()
            source = "\n".join(line.split("@", 1)[0] for line in source.splitlines())
            source = source.replace("::", ":")
            assembly = work / "table.S"
            assembly.write_text(source)
            for name, flags, relocation, width in [
                ("64bit", ["-DPORTABLE_64BIT"], "R_X86_64_64", 8),
                ("32bit-operands", [], "R_X86_64_32", 4),
            ]:
                with self.subTest(operand_mode=name):
                    obj = work / (name + ".o")
                    self.run_command(["gcc", "-x", "assembler-with-cpp", *flags,
                                      "-c", str(assembly), "-o", str(obj)])
                    relocations = self.run_command(["readelf", "-rW", str(obj)])
                    types = re.findall(r"R_X86_64_\w+", relocations)
                    self.assertEqual(len(types), 228)  # 227 opcodes plus sentinel.
                    self.assertEqual(set(types), {relocation})
                    symbols = self.run_command(["nm", "-n", str(obj)])
                    found = re.findall(r"^([0-9a-f]+) \w gScriptCmdTable(End)?$",
                                       symbols, re.M)
                    self.assertEqual(len(found), 2)
                    self.assertEqual(int(found[1][0], 16) - int(found[0][0], 16),
                                     227 * width)


if __name__ == "__main__":
    unittest.main()
