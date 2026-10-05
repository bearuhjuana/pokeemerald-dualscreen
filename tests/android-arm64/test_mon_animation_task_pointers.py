"""Execute the production animation and cry task paths with native pointers."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def between(source, start, end):
    return source[source.index(start):source.index(end)]


@unittest.skipUnless(shutil.which("gcc"), "gcc is required for native task checks")
class MonAnimationTaskPointerTests(unittest.TestCase):
    def build_and_run(self, portable64):
        animation = (ROOT / "src/pokemon_animation.c").read_text()
        pokemon = (ROOT / "src/pokemon.c").read_text()
        ball = (ROOT / "src/pokeball.c").read_text()
        animation_block = between(animation, "#define tState  data[0]", "void SetSpriteCB_MonAnimDummy")
        delay_start = "#ifdef PORTABLE_64BIT\n#define READ_PTR_FROM_TASK" if "#ifdef PORTABLE_64BIT\n#define READ_PTR_FROM_TASK" in pokemon else "#define READ_PTR_FROM_TASK"
        delay_block = between(pokemon, delay_start, "void BattleAnimateFrontSprite")
        front_block = between(pokemon, "void DoMonFrontSpriteAnimation(", "void StopPokemonAnimationDelayTask")
        cry_block = between(ball, "#define tCryTaskSpecies", "static void SpriteCB_ReleaseMonFromBall(struct Sprite *sprite)\n{")
        start = ball.index("        taskId = CreateTask(Task_PlayCryWhenReleasedFromBall, 3);")
        end = ball.index("        gTasks[taskId].tCryTaskState = 0;", start)
        cry_store = ball[start:end] + "        gTasks[taskId].tCryTaskState = 0;\n"
        global_stub = r'''
#ifndef TEST_GLOBAL_H
#define TEST_GLOBAL_H
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <stdint.h>
#include "gba/types.h"
#define TRUE 1
#define FALSE 0
#define COMMON_DATA
#define ARRAY_COUNT(a) (sizeof(a)/sizeof((a)[0]))
#endif
'''
        preamble = r'''
#include "global.h"
#include "task.h"
#include "sprite.h"
#include "constants/species.h"
#include <sys/mman.h>
struct Sprite gSprites[MAX_SPRITES + 1];
struct Pokemon { u16 hp; };
static struct Pokemon gPlayerParty[4];
static u16 gBattlerPartyIndexes[4];
static u8 gBattlerSpriteIds[4];
static bool8 sIsSummaryAnim;
static void TestAnimation(struct Sprite *sprite) { sprite->data[3]++; }
void SpriteCallbackDummy(struct Sprite *sprite) { (void)sprite; }
static void SpriteCallbackDummy_2(struct Sprite *sprite) { (void)sprite; }
static void MonAnimDummySpriteCallback(struct Sprite *sprite) { (void)sprite; }
static SpriteCallback sMonAnimFunctions[] = { TestAnimation, TestAnimation, TestAnimation };
static const u8 sBackAnimNatureModTable[] = { 0, 1 };
static const u8 sBackAnimationIds[] = { 0, 1, 2, 0, 2, 1 };
static u8 GetNature(struct Pokemon *mon) { (void)mon; return 1; }
#define sDontFlip data[1]
#define SKIP_FRONT_ANIM 0x80
static const u8 sMonFrontAnimIdsTable[NUM_SPECIES] = { [SPECIES_LOTAD - 1] = 1, [SPECIES_BLASTOISE - 1] = 2 };
static const u8 sMonAnimationDelayTable[NUM_SPECIES] = { [SPECIES_BLASTOISE - 1] = 2 };
static int sNormalCryCalls;
static void PlayCry_Normal(u16 species, s8 pan) { (void)species; (void)pan; sNormalCryCalls++; }
static bool8 HasTwoFramesAnimation(u16 species) { (void)species; return TRUE; }
void StartSpriteAnim(struct Sprite *sprite, u8 anim) { sprite->animNum = anim; }
static u8 sSummaryDelayTaskId;
static void SummaryScreen_SetAnimDelayTaskId(u8 task) { sSummaryDelayTaskId = task; }
static void SetSpriteCB_MonAnimDummy(struct Sprite *sprite) { sprite->callback = MonAnimDummySpriteCallback; }
struct TestHealthBox { bool8 waitForCry; };
struct TestBattleSpriteData { struct TestHealthBox healthBoxesData[4]; };
static struct TestBattleSpriteData sBattleSpriteData;
static struct TestBattleSpriteData *gBattleSpritesDataPtr = &sBattleSpriteData;
static struct Pokemon *sExpectedMon;
static int sCheckedCryCalls;
static bool8 ShouldPlayNormalMonCry(struct Pokemon *mon) {
    assert(mon == sExpectedMon && mon->hp == 100);
    sCheckedCryCalls++;
    return TRUE;
}
#define CRY_MODE_NORMAL 0
#define CRY_MODE_WEAK 1
#define CRY_MODE_DOUBLES 2
#define CRY_MODE_WEAK_DOUBLES 3
static void PlayCry_ByMode(u16 species, s8 pan, u8 mode) { assert(species == SPECIES_LOTAD && pan == -25); (void)mode; }
static void PlayCry_ReleaseDouble(u16 species, s8 pan, u8 mode) { PlayCry_ByMode(species, pan, mode); }
static void StopCryAndClearCrySongs(void) {}
static bool8 IsCryPlayingOrClearCrySongs(void) { return FALSE; }
#define sBattler data[6]
'''
        cry_queue = "\nstatic u8 QueueCry(struct Pokemon *mon, u16 species, s8 pan, u8 wantedCryCase, u8 battler, struct Sprite *sprite)\n{\n    u8 taskId;\n" + cry_store + "    return taskId;\n}\n"
        main = r'''
static void CheckFrontOrBack(struct Sprite *sprite, bool8 back)
{
    u8 task;
    ResetTasks();
    memset(sprite, 0, sizeof(*sprite));
    sprite->data[0] = 3;
    sprite->data[2] = SPECIES_LOTAD;
    if (back) LaunchAnimationTaskForBackSprite(sprite, 1);
    else LaunchAnimationTaskForFrontSprite(sprite, 1);
    task = FindTaskIdByFunc(Task_HandleMonAnimation);
    assert(task != TASK_NONE);
    RunTasks();
    assert(sprite->data[0] == 0 && sprite->data[1] == TRUE);
    assert(sprite->callback == TestAnimation);
    sprite->callback(sprite);
    assert(sprite->data[3] == 1);
    sprite->callback = SpriteCallbackDummy;
    RunTasks();
    assert(!gTasks[task].isActive);
    assert(sprite->data[0] == 3 && sprite->data[2] == SPECIES_LOTAD && sprite->data[1] == 0);
}
int main(void)
{
    struct Sprite *sprite;
    struct Pokemon *mon;
    u8 task;
#ifdef PORTABLE_64BIT
    sprite = calloc(1, sizeof(*sprite));
    mon = calloc(1, sizeof(*mon));
    assert(sizeof(void *) == 8);
    assert((uintptr_t)sprite > UINT32_MAX && (uintptr_t)mon > UINT32_MAX);
#else
#ifdef MAP_32BIT
    void *region = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    assert(region != MAP_FAILED && (uintptr_t)region <= UINT32_MAX);
    sprite = region;
    mon = (void *)((u8 *)region + sizeof(*sprite));
#else
    return 77;
#endif
#endif
    CheckFrontOrBack(sprite, FALSE);
    CheckFrontOrBack(sprite, TRUE);
    ResetTasks();
    memset(sprite, 0, sizeof(*sprite));
    // Birch's route starts a cry and an immediate front animation together.
    DoMonFrontSpriteAnimation(sprite, SPECIES_LOTAD, FALSE, 0);
    assert(sNormalCryCalls == 1 && sprite->animNum == 1);
    RunTasks();
    assert(sprite->callback == TestAnimation);
    ResetTasks();
    memset(sprite, 0, sizeof(*sprite));
    DoMonFrontSpriteAnimation(sprite, SPECIES_BLASTOISE, FALSE, 0);
    assert(FindTaskIdByFunc(Task_AnimateAfterDelay) != TASK_NONE);
    RunTasks();
    assert(FindTaskIdByFunc(Task_HandleMonAnimation) == TASK_NONE);
    RunTasks();
    assert(sprite->callback == TestAnimation);
    ResetTasks();
    memset(sprite, 0, sizeof(*sprite));
    PokemonSummaryDoMonAnimation(sprite, SPECIES_BLASTOISE, FALSE);
    assert(sSummaryDelayTaskId != TASK_NONE);
    RunTasks();
    RunTasks();
    assert(sprite->callback == TestAnimation && sSummaryDelayTaskId == TASK_NONE && sIsSummaryAnim);
    ResetTasks();
    memset(sprite, 0, sizeof(*sprite));
    mon->hp = 100;
    sExpectedMon = mon;
    gSprites[0].affineAnimEnded = TRUE;
    task = QueueCry(mon, SPECIES_LOTAD, -25, 0, 0, sprite);
    RunTasks();
    RunTasks();
    assert(sCheckedCryCalls == 1 && !gTasks[task].isActive);
    task = QueueCry(mon, SPECIES_LOTAD, -25, 1, 0, sprite);
    for (int i = 0; i < 8; i++) RunTasks();
    assert(sCheckedCryCalls == 2 && !gTasks[task].isActive);
    task = QueueCry(mon, SPECIES_LOTAD, -25, 2, 0, sprite);
    for (int i = 0; i < 16; i++) RunTasks();
    assert(sCheckedCryCalls == 3 && !gTasks[task].isActive);
#ifdef PORTABLE_64BIT
    free(sprite);
    free(mon);
#else
#ifdef MAP_32BIT
    munmap(sprite, 4096);
#endif
#endif
    puts("front/back/delay/summary and cry task pointers passed");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            (temp / "global.h").write_text(global_stub)
            source = preamble + animation_block + delay_block + front_block + cry_block + cry_queue + main
            (temp / "paths.c").write_text(source)
            cmd = ["gcc", "-std=gnu11", "-O1", "-g", "-DPORTABLE", "-DMODERN=1", "-iquote", str(temp), "-iquote", str(ROOT / "include"), str(ROOT / "src/task.c"), str(temp / "paths.c"), "-o", str(temp / "paths")]
            if portable64:
                cmd += ["-DPORTABLE_64BIT", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
            built = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            env = os.environ.copy()
            env["ASAN_OPTIONS"] = "detect_leaks=0"
            result = subprocess.run([str(temp / "paths")], env=env, capture_output=True, text=True)
            if result.returncode == 77 and not portable64:
                self.skipTest("MAP_32BIT is unavailable for legacy pointer execution")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("task pointers passed", result.stdout)

    def test_native_followup_callbacks(self):
        # PIE keeps real function addresses above 32 bits; no invented callbacks.
        source = r"""
#include "global.h"
#include "task.h"
static int firstCalls, secondCalls;
static void First(u8 task) { firstCalls++; SwitchTaskToFollowupFunc(task); }
static void Second(u8 task) { secondCalls++; DestroyTask(task); }
int main(void) {
    assert((uintptr_t)First > UINT32_MAX && (uintptr_t)Second > UINT32_MAX);
    ResetTasks();
    u8 task = CreateTask(TaskDummy, 0);
    gTasks[task].data[14] = 123;
    gTasks[task].data[15] = 456;
    SetTaskFuncWithFollowupFunc(task, First, Second);
    assert(gTasks[task].followupFunc == Second);
    assert(gTasks[task].data[14] == 123 && gTasks[task].data[15] == 456);
    RunTasks(); RunTasks();
    assert(firstCalls == 1 && secondCalls == 1 && !gTasks[task].isActive);
    task = CreateTask(TaskDummy, 0);
    assert(gTasks[task].followupFunc == NULL);
    SetTaskFuncWithFollowupFunc(task, First, Second);
    ResetTasks();
    assert(gTasks[task].followupFunc == NULL);
    return 0;
}
"""
        stub = "#include <stdlib.h>\n#include <stdint.h>\n#include <string.h>\n#include <assert.h>\n#include \"gba/types.h\"\n#define COMMON_DATA\n#define TRUE 1\n#define FALSE 0\n"
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            (temp / "global.h").write_text(stub)
            (temp / "followup.c").write_text(source)
            cmd = ["gcc", "-std=gnu11", "-O1", "-DPORTABLE_64BIT", "-fsanitize=undefined", "-fno-sanitize-recover=all", "-fPIE", "-pie", "-iquote", str(temp), "-iquote", str(ROOT / "include"), str(ROOT / "src/task.c"), str(temp / "followup.c"), "-o", str(temp / "followup")]
            built = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(temp / "followup")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_native_pointer_task_paths(self):
        self.build_and_run(True)

    def test_legacy_pointer_task_paths(self):
        self.build_and_run(False)


if __name__ == "__main__":
    unittest.main()
