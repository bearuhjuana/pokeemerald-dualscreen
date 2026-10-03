#ifndef GUARD_NX_SYS_H
#define GUARD_NX_SYS_H

// Bridge between the game (pokeemerald types) and libnx.
//
// This header is included by src/platform/switch.c, which also includes the
// game's headers. libnx and the decompilation both define u8/u16/u32/..., so
// this header deliberately uses only <stdint.h> types and void* — it must
// never include <switch.h>. The libnx side lives in nx_sys.c, which includes
// <switch.h> and never includes game headers. The linker joins them.

#include <stdint.h>

void NX_Init(void);
void NX_Exit(void);

// Returns 0 when the application should quit (HOME / hbmenu close).
int NX_ProcessEvents(void);

// Software framebuffer: 1280x720, RGBA8, linear layout.
// Pixels are packed R | G<<8 | B<<16 | A<<24.
void *NX_BeginFrame(uint32_t *outStrideBytes);
void NX_EndFrame(void);

// Input. Returns a bitmask using the NX_BTN_* values below, which mirror
// libnx's HidNpadButton bit positions (they are ABI-stable).
#define NX_BTN_A            (1ULL << 0)
#define NX_BTN_B            (1ULL << 1)
#define NX_BTN_X            (1ULL << 2)
#define NX_BTN_Y            (1ULL << 3)
#define NX_BTN_STICK_L      (1ULL << 4)
#define NX_BTN_STICK_R      (1ULL << 5)
#define NX_BTN_L            (1ULL << 6)
#define NX_BTN_R            (1ULL << 7)
#define NX_BTN_ZL           (1ULL << 8)
#define NX_BTN_ZR           (1ULL << 9)
#define NX_BTN_PLUS         (1ULL << 10)
#define NX_BTN_MINUS        (1ULL << 11)
#define NX_BTN_DLEFT        (1ULL << 12)
#define NX_BTN_DUP          (1ULL << 13)
#define NX_BTN_DRIGHT       (1ULL << 14)
#define NX_BTN_DDOWN        (1ULL << 15)
#define NX_BTN_STICK_L_LEFT (1ULL << 16)
#define NX_BTN_STICK_L_UP   (1ULL << 17)
#define NX_BTN_STICK_L_RIGHT (1ULL << 18)
#define NX_BTN_STICK_L_DOWN (1ULL << 19)
#define NX_BTN_STICK_R_LEFT (1ULL << 20)
#define NX_BTN_STICK_R_UP   (1ULL << 21)
#define NX_BTN_STICK_R_RIGHT (1ULL << 22)
#define NX_BTN_STICK_R_DOWN (1ULL << 23)

uint64_t NX_PollButtons(void);

// Audio: accepts 48000 Hz stereo int16, fire-and-forget. An internal pool of
// buffers is submitted to audout; released buffers are reclaimed on submit.
void NX_AudioSubmit(const int16_t *samples, uint32_t frameCount);
uint32_t NX_AudioQueuedFrames(void);

// Clock: POSIX timestamp in the console's local timezone.
uint64_t NX_LocalTimestamp(void);

// Runs fn(arg) on a new thread (2 MiB stack) for the game (AgbMain).
void NX_RunGameThread(void (*fn)(void *), void *arg);

// Frame handshake between the game thread and the main thread.
// Game thread: NX_GameFrameWait() implements VBlankIntrWait().
// Main thread: NX_MainFrameWait() blocks until the game finished a frame,
// then NX_MainFrameDone() releases the game thread for the next one.
void NX_GameFrameWait(void);
void NX_MainFrameWait(void);
void NX_MainFrameDone(void);

#endif // GUARD_NX_SYS_H
