// libnx side of the Switch backend. Includes <switch.h> only — never any
// game headers (both define u8/u16/u32/...). Paired with nx_sys.h.

#include <switch.h>
#include <malloc.h>
#include <string.h>

#include "nx_sys.h"

// ---------------------------------------------------------------- video ---

#define FB_WIDTH  1280
#define FB_HEIGHT 720

static NWindow *sWindow;
static Framebuffer sFramebuffer;
static bool sVideoOk;

// ---------------------------------------------------------------- input ---

static PadState sPad;

// ---------------------------------------------------------------- audio ---
// audout only supports 48000 Hz / stereo / int16, so the game side
// resamples to that before calling NX_AudioSubmit.
//
// Buffer management: a ring of buffers submitted FIFO. The device also
// consumes FIFO, so when audoutGetAudioOutBufferCount() reports fewer than
// POOL buffers queued, the ring head (oldest submission) is guaranteed free.
// Queued-frame accounting for the fast-forward skip logic uses the device's
// played-sample counter, which is exact.

#define AUDIO_POOL_BUFFERS 8
#define AUDIO_POOL_FRAMES  1024 // stereo frames per buffer (4096 bytes)

static AudioOutBuffer sAudioPool[AUDIO_POOL_BUFFERS];
static int16_t *sAudioPoolData[AUDIO_POOL_BUFFERS];
static int sAudioHead;
static uint64_t sAudioSubmittedFrames;

// ------------------------------------------------------------ game thread ---

static Thread sGameThread;
static void *sGameStack;

static Mutex sFrameMutex;
static CondVar sFrameCond;
static bool sFrameAvailable;
static bool sFrameDone;

void NX_Init(void)
{
    fsdevMountSdmc();

    sWindow = nwindowGetDefault();
    if (R_SUCCEEDED(framebufferCreate(&sFramebuffer, sWindow, FB_WIDTH, FB_HEIGHT,
                                      PIXEL_FORMAT_RGBA_8888, 2))
        && R_SUCCEEDED(framebufferMakeLinear(&sFramebuffer)))
        sVideoOk = true;

    padConfigureInput(1, HidNpadStyleSet_NpadStandard);
    padInitializeDefault(&sPad);

    if (R_SUCCEEDED(audoutInitialize()))
        audoutStartAudioOut();
    for (int i = 0; i < AUDIO_POOL_BUFFERS; i++)
    {
        sAudioPoolData[i] = memalign(0x1000, AUDIO_POOL_FRAMES * 4);
        if (sAudioPoolData[i] != NULL)
            memset(sAudioPoolData[i], 0, AUDIO_POOL_FRAMES * 4);
        sAudioPool[i].next = NULL;
        sAudioPool[i].buffer = sAudioPoolData[i];
        sAudioPool[i].buffer_size = AUDIO_POOL_FRAMES * 4;
        sAudioPool[i].data_size = 0;
        sAudioPool[i].data_offset = 0;
    }

    mutexInit(&sFrameMutex);
    condvarInit(&sFrameCond);

    timeInitialize();
}

void NX_Exit(void)
{
    audoutExit();
    timeExit();
    if (sVideoOk)
        framebufferClose(&sFramebuffer);
}

int NX_ProcessEvents(void)
{
    return appletMainLoop() ? 1 : 0;
}

void *NX_BeginFrame(uint32_t *outStrideBytes)
{
    if (!sVideoOk)
    {
        if (outStrideBytes != NULL)
            *outStrideBytes = 0;
        return NULL;
    }
    return framebufferBegin(&sFramebuffer, outStrideBytes);
}

void NX_EndFrame(void)
{
    if (sVideoOk)
        framebufferEnd(&sFramebuffer);
}

uint64_t NX_PollButtons(void)
{
    padUpdate(&sPad);
    return padGetButtons(&sPad);
}

void NX_AudioSubmit(const int16_t *samples, uint32_t frameCount)
{
    if (samples == NULL || frameCount == 0 || frameCount > AUDIO_POOL_FRAMES)
        return;

    // How many of our buffers the device still holds. Both sides are FIFO,
    // so if fewer than POOL are queued, the ring head is free to reuse.
    uint32_t devQueued = 0;
    if (R_FAILED(audoutGetAudioOutBufferCount(&devQueued)))
        return; // unknown state: drop rather than clobber a live buffer
    if (devQueued >= AUDIO_POOL_BUFFERS)
        return; // device full; drop the frame (the skip logic should prevent this)

    int slot = sAudioHead;
    sAudioHead = (sAudioHead + 1) % AUDIO_POOL_BUFFERS;
    if (sAudioPoolData[slot] == NULL)
        return;

    memcpy(sAudioPoolData[slot], samples, frameCount * 4);
    sAudioPool[slot].data_size = frameCount * 4;
    sAudioPool[slot].data_offset = 0;
    if (R_SUCCEEDED(audoutAppendAudioOutBuffer(&sAudioPool[slot])))
        sAudioSubmittedFrames += frameCount;
}

uint32_t NX_AudioQueuedFrames(void)
{
    uint64_t playedSamples = 0;
    if (R_SUCCEEDED(audoutGetAudioOutPlayedSampleCount(&playedSamples)))
    {
        uint64_t playedFrames = playedSamples / 2; // stereo
        if (playedFrames >= sAudioSubmittedFrames)
            return 0;
        return (uint32_t)(sAudioSubmittedFrames - playedFrames);
    }
    return 0;
}

uint64_t NX_LocalTimestamp(void)
{
    uint64_t ts = 0;
    timeGetCurrentTime(TimeType_Default, &ts);
    return ts;
}

void NX_RunGameThread(void (*fn)(void *), void *arg)
{
    // libnx requires the stack to be page-aligned (it also holds TLS/reent).
    sGameStack = memalign(0x1000, 2 * 1024 * 1024);
    threadCreate(&sGameThread, (ThreadFunc)fn, arg, sGameStack, 2 * 1024 * 1024, 0x2C, -2);
    threadStart(&sGameThread);
}

void NX_GameFrameWait(void)
{
    mutexLock(&sFrameMutex);
    sFrameAvailable = true;
    condvarWakeAll(&sFrameCond);
    while (!sFrameDone)
        condvarWait(&sFrameCond, &sFrameMutex);
    sFrameAvailable = false;
    sFrameDone = false;
    mutexUnlock(&sFrameMutex);
}

void NX_MainFrameWait(void)
{
    mutexLock(&sFrameMutex);
    while (!sFrameAvailable)
        condvarWait(&sFrameCond, &sFrameMutex);
    mutexUnlock(&sFrameMutex);
}

void NX_MainFrameDone(void)
{
    mutexLock(&sFrameMutex);
    sFrameDone = true;
    condvarWakeAll(&sFrameCond);
    mutexUnlock(&sFrameMutex);
}
