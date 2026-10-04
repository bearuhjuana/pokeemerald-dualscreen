// Nintendo Switch (libnx) platform backend.
//
// Game-facing half: implements the Platform_* interface from platform.h,
// runs AgbMain on a worker thread, and presents frames through the software
// framebuffer. All direct libnx calls live in nx_sys.c (see nx_sys.h) — this
// file includes game headers only, because both worlds define u8/u16/u32.
//
// Build defines both PLATFORM_SDL2 (keeps the portable game-code feature
// gates: widescreen, option-menu entries, ...) and PLATFORM_SWITCH (selects
// this backend instead of sdl2.c/win32.c/dualscreen_bridge.c).
//
// Design decisions (Derek, 2026-10-03):
// - The dual-screen bottom UI is CUT for Switch ("saws-all"). The DualScreen
//   hooks below are stubs that force classic top-screen behavior.
// - Widescreen is the default: 288x160 fills the 16:9 display.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#include "global.h"
#include "gba/syscall.h"
#include "gba/flash_internal.h"
#include "gba/io_reg.h"
#include "cgb_audio.h"
#include "platform.h"
#include "platform/dma.h"
#include "platform/framedraw.h"
#include "platform/dualscreen.h"
#include "mods/mod_manager.h"

#include "nx_sys.h"

extern void AgbMain(void);

// ------------------------------------------------------------------ config ---

#define SAVE_DIR  "sdmc:/switch/pokeemerald-dualscreen"
#define SAVE_PATH SAVE_DIR "/pokeemerald.sav"

#define GAME_SAMPLE_RATE 42060
#define OUT_SAMPLE_RATE  48000
#define AUDIO_MAX_OUT_FRAMES 1024

// Matches sdl2.c defaults, except WIDESCREEN which defaults ON here:
// the bottom screen is cut, so 16:9 is the whole experience.
static u8 sPlatformSettings[PLATFORM_SETTING_COUNT] =
    {0, 4, 0, 1, 1, 10, 1, 1, 0, 0, 0, 0, 0, 0};

// Set for each game frame the catch-up loop runs; see Platform_SkipAudioFrame.
static bool8 sSkipAudioFrame = FALSE;
// Byte size of one resampled frame, learned from the first queued frame.
static u32 sAudioFrameBytes = 0;
// How much audio to keep buffered ahead while fast-forwarding.
#define AUDIO_QUEUE_TARGET_FRAMES 3

static FILE *sSaveFile = NULL;
static struct SiiRtcInfo sInternalClock;

// ------------------------------------------------------------------- video ---

static uint16_t sGbaImage[MAX_RENDER_WIDTH * DISPLAY_HEIGHT];

#define FB_W 1280
#define FB_H 720

static void PresentFrame(void)
{
    uint32_t stride = 0;
    uint32_t *fb = (uint32_t *)NX_BeginFrame(&stride);
    if (fb == NULL || stride == 0)
        return;

    memset(sGbaImage, 0, sizeof(sGbaImage));
    DrawFrame(sGbaImage);

    int w = gRenderWidth;
    int h = DISPLAY_HEIGHT;
    int scale = FB_W / w;
    if (FB_H / h < scale)
        scale = FB_H / h;
    if (scale < 1)
        scale = 1;
    int dw = w * scale;
    int dh = h * scale;
    int ox = (FB_W - dw) / 2;
    int oy = (FB_H - dh) / 2;

    // Letterbox.
    for (int y = 0; y < FB_H; y++)
    {
        uint32_t *row = (uint32_t *)((uint8_t *)fb + (uint32_t)y * stride);
        for (int x = 0; x < FB_W; x++)
            row[x] = 0xFF000000; // RGBA8 opaque black
    }

    for (int y = 0; y < h; y++)
    {
        for (int x = 0; x < w; x++)
        {
            uint16_t c = sGbaImage[y * w + x];
            uint32_t r = (c & 0x1F) * 255 / 31;
            uint32_t g = ((c >> 5) & 0x1F) * 255 / 31;
            uint32_t b = ((c >> 10) & 0x1F) * 255 / 31;
            uint32_t px = r | (g << 8) | (b << 16) | 0xFF000000; // RGBA8
            for (int sy = 0; sy < scale; sy++)
            {
                uint32_t *row = (uint32_t *)((uint8_t *)fb + (uint32_t)(oy + y * scale + sy) * stride);
                for (int sx = 0; sx < scale; sx++)
                    row[ox + x * scale + sx] = px;
            }
        }
    }

    NX_EndFrame();
}

// ------------------------------------------------------------------- input ---

u16 Platform_GetKeyInput(void)
{
    uint64_t b = NX_PollButtons();
    u16 keys = 0;

    if (b & NX_BTN_A)            keys |= A_BUTTON;
    if (b & NX_BTN_B)            keys |= B_BUTTON;
    if (b & NX_BTN_X)            keys |= A_BUTTON; // convenience
    if (b & NX_BTN_Y)            keys |= B_BUTTON; // convenience
    if (b & NX_BTN_PLUS)         keys |= START_BUTTON;
    if (b & NX_BTN_MINUS)        keys |= SELECT_BUTTON;
    if (b & (NX_BTN_L | NX_BTN_ZL)) keys |= L_BUTTON;
    if (b & (NX_BTN_R | NX_BTN_ZR)) keys |= R_BUTTON;
    if (b & (NX_BTN_DUP | NX_BTN_STICK_L_UP | NX_BTN_STICK_R_UP))
        keys |= DPAD_UP;
    if (b & (NX_BTN_DDOWN | NX_BTN_STICK_L_DOWN | NX_BTN_STICK_R_DOWN))
        keys |= DPAD_DOWN;
    if (b & (NX_BTN_DLEFT | NX_BTN_STICK_L_LEFT | NX_BTN_STICK_R_LEFT))
        keys |= DPAD_LEFT;
    if (b & (NX_BTN_DRIGHT | NX_BTN_STICK_L_RIGHT | NX_BTN_STICK_R_RIGHT))
        keys |= DPAD_RIGHT;

    return keys;
}

// ------------------------------------------------------------------- audio ---
// The game mixes float32 stereo at 42060 Hz; audout wants int16 stereo at
// 48000 Hz. Resample with linear interpolation on the way in.

static int16_t sResampled[AUDIO_MAX_OUT_FRAMES * 2];

void Platform_QueueAudio(float *audioBuffer, s32 samplesPerFrame)
{
    // NOTE: samplesPerFrame is actually a byte count (see sdl2.c).
    int floatCount = samplesPerFrame / (s32)sizeof(float);
    int inFrames = floatCount / 2; // stereo interleaved
    if (inFrames < 1)
        return;

    float volume = sPlatformSettings[PLATFORM_SETTING_VOLUME] / 10.0f;
    int outFrames = (inFrames * OUT_SAMPLE_RATE + GAME_SAMPLE_RATE / 2) / GAME_SAMPLE_RATE;
    if (outFrames > AUDIO_MAX_OUT_FRAMES)
        outFrames = AUDIO_MAX_OUT_FRAMES;

    for (int i = 0; i < outFrames; i++)
    {
        double srcPos = (double)i * inFrames / outFrames;
        int s0 = (int)srcPos;
        int s1 = (s0 + 1 < inFrames) ? s0 + 1 : s0;
        double frac = srcPos - s0;
        for (int ch = 0; ch < 2; ch++)
        {
            float s = (float)((1.0 - frac) * audioBuffer[s0 * 2 + ch]
                              + frac * audioBuffer[s1 * 2 + ch]) * volume;
            if (s > 1.0f)
                s = 1.0f;
            else if (s < -1.0f)
                s = -1.0f;
            sResampled[i * 2 + ch] = (int16_t)(s * 32767.0f);
        }
    }

    sAudioFrameBytes = (u32)(outFrames * 4);
    NX_AudioSubmit(sResampled, (uint32_t)outFrames);
}

bool32 Platform_SkipAudioFrame(void)
{
    return sSkipAudioFrame;
}

// -------------------------------------------------------------------- save ---

static void ReadSaveFile(void)
{
    mkdir(SAVE_DIR, 0777); // ignore errors; exists after first run
    sSaveFile = fopen(SAVE_PATH, "r+b");
    if (sSaveFile == NULL)
        sSaveFile = fopen(SAVE_PATH, "w+b");
    if (sSaveFile == NULL)
    {
        memset(FLASH_BASE, 0xFF, sizeof(FLASH_BASE));
        return;
    }

    fseek(sSaveFile, 0, SEEK_END);
    long fileSize = ftell(sSaveFile);
    fseek(sSaveFile, 0, SEEK_SET);

    long bytesToRead = fileSize < (long)sizeof(FLASH_BASE) ? fileSize : (long)sizeof(FLASH_BASE);
    long bytesRead = 0;
    if (bytesToRead > 0)
        bytesRead = fread(FLASH_BASE, 1, bytesToRead, sSaveFile);
    for (long i = bytesRead; i < (long)sizeof(FLASH_BASE); i++)
        FLASH_BASE[i] = 0xFF;
}

static void StoreSaveFile(void)
{
    if (sSaveFile != NULL)
    {
        fseek(sSaveFile, 0, SEEK_SET);
        fwrite(FLASH_BASE, 1, sizeof(FLASH_BASE), sSaveFile);
        fflush(sSaveFile);
    }
}

void Platform_StoreSaveFile(void)
{
    StoreSaveFile();
}

void Platform_ReadFlash(u16 sectorNum, u32 offset, u8 *dest, u32 size)
{
    FILE *saveFile = fopen(SAVE_PATH, "r+b");
    if (saveFile == NULL)
        return;
    if (fseek(saveFile, (sectorNum << gFlash->sector.shift) + offset, SEEK_SET))
    {
        fclose(saveFile);
        return;
    }
    if (fread(dest, 1, size, saveFile) != size)
    {
        fclose(saveFile);
        return;
    }
    fclose(saveFile);
}

// --------------------------------------------------------------------- rtc ---

static u8 BinToBcd(u8 bin)
{
    u8 out = 0;
    u8 place = 1;
    do
    {
        out |= (bin % 10) * place;
        place *= 16;
    } while ((bin /= 10) > 0);
    return out;
}

static void UpdateInternalClock(void)
{
    time_t rawTime = (time_t)NX_LocalTimestamp();
    struct tm tmTime;
    gmtime_r(&rawTime, &tmTime);

    sInternalClock.year = BinToBcd((u8)(tmTime.tm_year - 100));
    sInternalClock.month = BinToBcd((u8)(tmTime.tm_mon + 1));
    sInternalClock.day = BinToBcd((u8)tmTime.tm_mday);
    sInternalClock.dayOfWeek = BinToBcd((u8)tmTime.tm_wday);
    sInternalClock.hour = BinToBcd((u8)tmTime.tm_hour);
    sInternalClock.minute = BinToBcd((u8)tmTime.tm_min);
    sInternalClock.second = BinToBcd((u8)tmTime.tm_sec);
}

void Platform_GetStatus(struct SiiRtcInfo *rtc)
{
    UpdateInternalClock();
    *rtc = sInternalClock;
}

void Platform_SetStatus(struct SiiRtcInfo *rtc)
{
    sInternalClock = *rtc;
}

void Platform_GetDateTime(struct SiiRtcInfo *rtc)
{
    UpdateInternalClock();
    rtc->year = sInternalClock.year;
    rtc->month = sInternalClock.month;
    rtc->day = sInternalClock.day;
    rtc->dayOfWeek = sInternalClock.dayOfWeek;
    rtc->hour = sInternalClock.hour;
    rtc->minute = sInternalClock.minute;
    rtc->second = sInternalClock.second;
}

void Platform_SetDateTime(struct SiiRtcInfo *rtc)
{
    Platform_SetStatus(rtc);
}

void Platform_GetTime(struct SiiRtcInfo *rtc)
{
    UpdateInternalClock();
    rtc->hour = sInternalClock.hour;
    rtc->minute = sInternalClock.minute;
    rtc->second = sInternalClock.second;
}

void Platform_SetTime(struct SiiRtcInfo *rtc)
{
    sInternalClock.hour = rtc->hour;
    sInternalClock.minute = rtc->minute;
    sInternalClock.second = rtc->second;
}

void Platform_SetAlarm(u8 *alarmData)
{
    (void)alarmData;
}

// ---------------------------------------------------------------- settings ---

u8 Platform_GetSetting(enum PlatformSetting setting)
{
    if ((u32)setting < PLATFORM_SETTING_COUNT)
        return sPlatformSettings[setting];
    return 0;
}

void Platform_SetSetting(enum PlatformSetting setting, u8 value)
{
    if ((u32)setting >= PLATFORM_SETTING_COUNT)
        return;
    sPlatformSettings[setting] = value;
    if (setting == PLATFORM_SETTING_WIDESCREEN)
    {
        gRenderMargin = value ? WIDESCREEN_MARGIN : 0;
        gRenderWidth = DISPLAY_WIDTH + 2 * gRenderMargin;
    }
}

u8 Platform_GetBorderBackgroundCount(void)
{
    return 0; // desktop artwork borders don't exist on Switch
}

u8 Platform_GetBorderBackground(void)
{
    return 0;
}

void Platform_SetBorderBackground(u8 selection)
{
    (void)selection;
}

// ------------------------------------------------------- dual-screen stubs ---
// The bottom screen is cut on Switch: force classic top-screen behavior.

void DualScreen_FrameHook(void)
{
}

const char *DualScreen_GetSnapshotJson(void)
{
    return "";
}

u32 DualScreen_BattleUiActive(void)
{
    return FALSE;
}

u16 DualScreen_ConsumeVirtualKeys(void)
{
    return 0;
}

u32 DualScreen_TakeBattleTakeover(u32 mode)
{
    (void)mode;
    return FALSE;
}

void DualScreen_SetBattleMenuOpen(u32 mode, u32 caseId, u32 battler)
{
    (void)mode;
    (void)caseId;
    (void)battler;
}

void DualScreen_ClearBattleMenu(void)
{
}

u32 DualScreen_BattleMenuInfo(u32 *caseId, u32 *battler, u32 *result, u32 *seq)
{
    (void)caseId;
    (void)battler;
    (void)result;
    (void)seq;
    return FALSE;
}

u32 DualScreen_TakeBattleChoice(s32 *a, s32 *b)
{
    (void)a;
    (void)b;
    return FALSE;
}

void DualScreen_SetBattleMenuResult(u32 result)
{
    (void)result;
}

u32 DualScreen_BottomScreenLive(void)
{
    return FALSE;
}

// -------------------------------------------------------------------- main ---

void VBlankIntrWait(void)
{
    NX_GameFrameWait();
}

static void AgbMainThread(void *arg)
{
    (void)arg;
    AgbMain();
}

int main(int argc, char *argv[])
{
    (void)argc;
    (void)argv;

    NX_Init();
    ModManager_Init();

    // Widescreen default (see config note above).
    gRenderMargin = WIDESCREEN_MARGIN;
    gRenderWidth = DISPLAY_WIDTH + 2 * gRenderMargin;

    cgb_audio_init(GAME_SAMPLE_RATE);
    ReadSaveFile();

    memset(&sInternalClock, 0, sizeof(sInternalClock));
    sInternalClock.status = SIIRTCINFO_24HOUR;
    UpdateInternalClock();

    NX_RunGameThread(AgbMainThread, NULL);

    while (NX_ProcessEvents())
    {
        // Fast-forward: 1..4 game frames per presented frame.
        int steps = 1 + sPlatformSettings[PLATFORM_SETTING_FAST_FORWARD];
        for (int i = 0; i < steps; i++)
        {
            NX_MainFrameWait();

            // Emulate GBA VBlank interrupt (mirrors sdl2.c).
            // This is what advances the game state: VBlank callbacks,
            // buffered GPU register copies, DMA processing, audio, etc.
            REG_DISPSTAT |= INTR_FLAG_VBLANK;
            RunDMAs(DMA_HBLANK);
            if (REG_DISPSTAT & DISPSTAT_VBLANK_INTR)
            {
                gIntrTable[4]();
            }
            REG_DISPSTAT &= ~INTR_FLAG_VBLANK;

            // Keep the music at normal tempo while fast-forwarded: skip the
            // sound engine on frames where enough audio is already queued.
            // (Mirrors sdl2.c; sAudioFrameBytes is learned from the first
            // queued frame so the mixer can't starve before it runs once.)
            if (sPlatformSettings[PLATFORM_SETTING_FF_AUDIO] == 0
                && steps > 1 && sAudioFrameBytes != 0)
                sSkipAudioFrame = NX_AudioQueuedFrames() * 4
                    >= sAudioFrameBytes * AUDIO_QUEUE_TARGET_FRAMES;
            else
                sSkipAudioFrame = FALSE;

            if (i == steps - 1)
                PresentFrame();

            NX_MainFrameDone();
        }
    }

    StoreSaveFile();
    if (sSaveFile != NULL)
        fclose(sSaveFile);
    NX_Exit();
    return 0;
}

// GBA BIOS soft reset (A+B+Start+Select). On Switch, exit to the homebrew
// launcher; a full in-game reset would require re-running AgbMain.
void SoftReset(u32 resetFlags)
{
    (void)resetFlags;
    StoreSaveFile();
    if (sSaveFile != NULL)
        fclose(sSaveFile);
    NX_Exit();
    exit(0);
}
