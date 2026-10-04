# Host 64-bit smoke test

Runs the real game on x86_64 Linux to validate the `PORTABLE_64BIT` portability
work (bigger save sectors, 8-byte pointers in assembly data, 64-bit struct
layouts). This is how the 64-bit fixes were developed and verified.

## Prerequisites

- GCC (x86_64), GNU as/ld, Python 3, libpng development headers, standard build tools
- Build the repo tools first: `make -f make_tools.mk` (from repo root)

## Run

From the repo root:

```
make -f tests/host-64bit/Makefile.host -j$(nproc)
./build/host-test/host_test
```

The harness (`host_harness.c`) provides stub `Platform_*` implementations
(no window/audio), runs `AgbMain()` for 1200 frames with software `DrawFrame`,
and prints `SURVIVED 1200 frames on 64-bit` on success. It exercises the full
init path: GPU, sound engine (`m4aSoundInit`), RTC, flash save, map loading,
and the software PPU.

## What it validates

- `SECTOR_DATA_SIZE` fits `SaveBlock1` (16280 bytes on 64-bit)
- 8-byte script pointers in `map_script`/`map_script_2`/`object_event`
- 32-byte `ObjectEventTemplate`, 24-byte `struct MusicPlayer`
- `VRAM` pointer not truncated to u32
- Flash sector geometry (`DUMMY_SAVE`) matches `save.h`

## Notes

- Battle script operands and native pointer tables use eight-byte pointers.
  The harness still links `-no-pie`; run the focused tests below as well to
  exercise relocated pointers above 4 GiB and preserved legacy operand widths:

  ```sh
  python3 -m unittest discover -s tests/android-arm64 -v
  ```
- The harness is not part of any shipping build; it's a dev tool.
