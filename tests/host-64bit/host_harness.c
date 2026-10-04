// Host (x86_64) smoke-test harness for the Switch port.
//
// The Switch is 64-bit (aarch64) but this game's portable code has only ever
// run 32-bit (ARMv7 Android, 32-bit Linux/Windows). This harness runs the
// actual game logic natively on 64-bit Linux to shake out pointer-size and
// other 64-bit hazards BEFORE hardware testing. It exercises AgbMain, the
// software PPU (DrawFrame), the sound mixer, tasks, RTC and save code.
//
// Build: make -f Makefile.host   (in this directory)
// Run:   ./build-host/host_test  (exits 0 after 1200 frames)

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "global.h"
#include "gba/syscall.h"
#include "gba/flash_internal.h"
#include "cgb_audio.h"
#include "platform.h"
#include "platform/framedraw.h"
#include "platform/dualscreen.h"
#include "mods/mod_manager.h"

extern void AgbMain(void);
extern const u8 *gBattlescriptCurrInstr;

#define SURVIVE_FRAMES 1200

static u8 sSettings[PLATFORM_SETTING_COUNT] = {0};
static int sFrame = 0;
static uint16_t sGbaImage[MAX_RENDER_WIDTH * DISPLAY_HEIGHT];
static FILE *sSaveFile = NULL;
static struct SiiRtcInfo sClock;

u16 Platform_GetKeyInput(void)
{
    return 0; // no input: soaks the title screen
}

void Platform_QueueAudio(float *audioBuffer, s32 samplesPerFrame)
{
    (void)audioBuffer;
    (void)samplesPerFrame; // discarded; mixer still runs
}

bool32 Platform_SkipAudioFrame(void)
{
    return FALSE;
}

void Platform_StoreSaveFile(void)
{
    if (sSaveFile != NULL)
    {
        fseek(sSaveFile, 0, SEEK_SET);
        fwrite(FLASH_BASE, 1, sizeof(FLASH_BASE), sSaveFile);
        fflush(sSaveFile);
    }
}

void Platform_ReadFlash(u16 sectorNum, u32 offset, u8 *dest, u32 size)
{
    FILE *f = fopen("host_test.sav", "r+b");
    if (f == NULL)
        return;
    fseek(f, (sectorNum << gFlash->sector.shift) + offset, SEEK_SET);
    fread(dest, 1, size, f);
    fclose(f);
}

static u8 BinToBcd(u8 bin)
{
    u8 out = 0, place = 1;
    do { out |= (bin % 10) * place; place *= 16; } while ((bin /= 10) > 0);
    return out;
}

static void UpdateClock(void)
{
    time_t t = time(NULL);
    struct tm tmv;
    localtime_r(&t, &tmv);
    sClock.year = BinToBcd((u8)(tmv.tm_year - 100));
    sClock.month = BinToBcd((u8)(tmv.tm_mon + 1));
    sClock.day = BinToBcd((u8)tmv.tm_mday);
    sClock.dayOfWeek = BinToBcd((u8)tmv.tm_wday);
    sClock.hour = BinToBcd((u8)tmv.tm_hour);
    sClock.minute = BinToBcd((u8)tmv.tm_min);
    sClock.second = BinToBcd((u8)tmv.tm_sec);
}

void Platform_GetStatus(struct SiiRtcInfo *rtc) { UpdateClock(); *rtc = sClock; }
void Platform_SetStatus(struct SiiRtcInfo *rtc) { sClock = *rtc; }
void Platform_GetDateTime(struct SiiRtcInfo *rtc) { UpdateClock(); *rtc = sClock; }
void Platform_SetDateTime(struct SiiRtcInfo *rtc) { sClock = *rtc; }
void Platform_GetTime(struct SiiRtcInfo *rtc)
{
    UpdateClock();
    rtc->hour = sClock.hour; rtc->minute = sClock.minute; rtc->second = sClock.second;
}
void Platform_SetTime(struct SiiRtcInfo *rtc)
{
    sClock.hour = rtc->hour; sClock.minute = rtc->minute; sClock.second = rtc->second;
}
void Platform_SetAlarm(u8 *alarmData) { (void)alarmData; }

u8 Platform_GetSetting(enum PlatformSetting s)
{
    return (u32)s < PLATFORM_SETTING_COUNT ? sSettings[s] : 0;
}
void Platform_SetSetting(enum PlatformSetting s, u8 v)
{
    if ((u32)s < PLATFORM_SETTING_COUNT)
        sSettings[s] = v;
}
u8 Platform_GetBorderBackgroundCount(void) { return 0; }
u8 Platform_GetBorderBackground(void) { return 0; }
void Platform_SetBorderBackground(u8 s) { (void)s; }

// Dual-screen stubs: bottom screen cut, classic behavior.
void DualScreen_FrameHook(void) {}
const char *DualScreen_GetSnapshotJson(void) { return ""; }
u32 DualScreen_BattleUiActive(void) { return FALSE; }
u16 DualScreen_ConsumeVirtualKeys(void) { return 0; }
u32 DualScreen_TakeBattleTakeover(u32 m) { (void)m; return FALSE; }
void DualScreen_SetBattleMenuOpen(u32 a, u32 b, u32 c) { (void)a; (void)b; (void)c; }
void DualScreen_ClearBattleMenu(void) {}
u32 DualScreen_BattleMenuInfo(u32 *a, u32 *b, u32 *c, u32 *d)
    { (void)a; (void)b; (void)c; (void)d; return FALSE; }
u32 DualScreen_TakeBattleChoice(s32 *a, s32 *b) { (void)a; (void)b; return FALSE; }
void DualScreen_SetBattleMenuResult(u32 r) { (void)r; }
u32 DualScreen_BottomScreenLive(void) { return FALSE; }

void VBlankIntrWait(void)
{
    // Render the finished frame (exercises the software PPU on 64-bit).
    memset(sGbaImage, 0, sizeof(sGbaImage));
    DrawFrame(sGbaImage);
    if (++sFrame == 300)
    {
        // Battle-script 64-bit pointer validation.
        // Test 1: goto (0x28) with single 8-byte pointer.
        // Script: goto (0x28) -> end (0x3D). Layout: [0x28][8-byte ptr][0x3D]
        static u8 testScript[16];
        u8 *endCmd = &testScript[9];
        testScript[0] = 0x28;
        uintptr_t ptrVal = (uintptr_t)endCmd;
        for (int i = 0; i < 8; i++)
            testScript[1 + i] = (ptrVal >> (i * 8)) & 0xFF;
        testScript[9] = 0x3D;
        
        gBattlescriptCurrInstr = testScript;
        extern void (* const gBattleScriptingCommandsTable[])(void);
        gBattleScriptingCommandsTable[0x28](); // goto
        
        if (gBattlescriptCurrInstr == endCmd)
            printf("[Harness] PASS: goto 8-byte pointer works\n");
        else
            printf("[Harness] FAIL: goto pointer mismatch\n");
        fflush(stdout);
        
        // Test 2: jumpifbyte (0x29) with pointer-then-scalar-then-pointer.
        // Layout 64-bit: [0x29][ifflag:1][val_ptr:8][byte:1][jump_ptr:8] = 19 bytes
        // This validates BS_OFF interior offset fixes.
        static u8 testScript2[32];
        static u8 memByte = 42;
        u8 *end2 = &testScript2[19];
        testScript2[0] = 0x29; // jumpifbyte
        testScript2[1] = 0;    // CMP_EQUAL
        // val_ptr at +2 (8 bytes)
        ptrVal = (uintptr_t)&memByte;
        for (int i = 0; i < 8; i++)
            testScript2[2 + i] = (ptrVal >> (i * 8)) & 0xFF;
        testScript2[10] = 42;  // byte value at BS_OFF(6,1)=10
        // jump_ptr at +11 (8 bytes)
        ptrVal = (uintptr_t)end2;
        for (int i = 0; i < 8; i++)
            testScript2[11 + i] = (ptrVal >> (i * 8)) & 0xFF;
        testScript2[19] = 0x3D; // end
        
        gBattlescriptCurrInstr = testScript2;
        gBattleScriptingCommandsTable[0x29](); // jumpifbyte
        
        if (gBattlescriptCurrInstr == end2)
            printf("[Harness] PASS: jumpifbyte interior offsets work on 64-bit\n");
        else
            printf("[Harness] FAIL: jumpifbyte jumped to %p, expected %p\n",
                   (void*)gBattlescriptCurrInstr, (void*)end2);
        fflush(stdout);
        
        gBattleScriptingCommandsTable[0x3D](); // end
    }
    if (sFrame >= SURVIVE_FRAMES)
    {
        printf("SURVIVED %d frames on 64-bit\n", sFrame);
        if (sSaveFile != NULL)
            fclose(sSaveFile);
        exit(0);
    }
}

int main(void)
{
    ModManager_Init();
    cgb_audio_init(42060);
    sSaveFile = fopen("host_test.sav", "w+b");
    memset(FLASH_BASE, 0xFF, sizeof(FLASH_BASE));
    memset(&sClock, 0, sizeof(sClock));
    sClock.status = SIIRTCINFO_24HOUR;
    printf("running %d frames...\n", SURVIVE_FRAMES);
    fflush(stdout);
    AgbMain();
    return 0;
}

// GBA BIOS soft reset: on host, just exit.
void SoftReset(u32 resetFlags)
{
    (void)resetFlags;
    puts("SoftReset called. Exiting.");
    exit(0);
}
