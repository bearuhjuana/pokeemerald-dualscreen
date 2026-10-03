#include "global.h"
#include "gba/gba.h"
#include "gba/flash_internal.h"
#include <stdio.h>

const u16 dummyMaxTime[] =
{
      10, 65469, TIMER_ENABLE | TIMER_INTR_ENABLE | TIMER_256CLK,
      10, 65469, TIMER_ENABLE | TIMER_INTR_ENABLE | TIMER_256CLK,
    2000, 65469, TIMER_ENABLE | TIMER_INTR_ENABLE | TIMER_256CLK,
    2000, 65469, TIMER_ENABLE | TIMER_INTR_ENABLE | TIMER_256CLK,
};

const struct FlashSetupInfo DUMMY_SAVE =
{
    ProgramFlashByte_DUMMY,
    ProgramFlashSector_DUMMY,
    EraseFlashChip_DUMMY,
    EraseFlashSector_DUMMY,
    WaitForFlashWrite_DUMMY,
    dummyMaxTime,
    {
#ifdef PORTABLE_64BIT
        // 64-bit: sectors are 8192 bytes (SECTOR_SIZE in include/save.h),
        // because SECTOR_DATA_SIZE is 8064. Must match save.h.
        262144, // ROM size (32 * 8192)
        {
            8192, // sector size
              13, // bit shift to multiply by sector size (8192 == 1 << 13)
              32, // number of sectors
               0  // appears to be unused
        },
#else
        131072, // ROM size
        {
            4096, // sector size
              12, // bit shift to multiply by sector size (4096 == 1 << 12)
              32, // number of sectors
               0  // appears to be unused
        },
#endif
        { 3, 1 }, // wait state setup data
        { { 0xCC, 0xCC } } // ID
    }
};

u16 WaitForFlashWrite_DUMMY(u8 phase, u8 *addr, u8 lastData)
{
    // stub
    return 0;
}

u16 EraseFlashChip_DUMMY(void)
{
    memset(FLASH_BASE, 0xFF, sizeof(FLASH_BASE));
    return 0;
}

u16 EraseFlashSector_DUMMY(u16 sectorNum)
{
#ifdef PORTABLE_64BIT
    u8 clearBuffer[0x2000] = { 0xFF }; // 8192-byte sectors
#else
    u8 clearBuffer[0x1000] = { 0xFF }; // 4096-byte sectors
#endif
    return ProgramFlashSector_DUMMY(sectorNum, &clearBuffer[0]);
}

u16 ProgramFlashByte_DUMMY(u16 sectorNum, u32 offset, u8 data)
{
    FLASH_BASE[(sectorNum << gFlash->sector.shift) + offset] = data;
    return 0;
}


u16 ProgramFlashSector_DUMMY(u16 sectorNum, u8 *src)
{
    // Use the geometry from DUMMY_SAVE (differs under PORTABLE_64BIT).
    memcpy(&FLASH_BASE[sectorNum << gFlash->sector.shift], src, gFlash->sector.size);
    return 0;
}
