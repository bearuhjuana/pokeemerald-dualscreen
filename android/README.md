# Experimental Android ARM64 + voxel build

The Android app builds `arm64-v8a` for devices such as the Pixel 9 Pro XL.
All C preprocessing, C compilation, assembly macros, and MIDI generation use
`PORTABLE_64BIT` when the selected NDK ABI has eight-byte pointers. Generated
data objects use NDK Clang, `ld.lld`, and `llvm-objcopy`.

## Build

Use Linux, JDK 17, Gradle 8.2.1, Python 3, GNU Make, GCC/G++, and libpng
development headers. Install Android SDK 36, NDK 26.3.11579264, and CMake 3.22.1.
From a complete repository checkout:

```sh
git submodule update --init --recursive
git -C android/SDL2 apply ../patches/sdl2-android-lifecycle.patch
sdkmanager 'platforms;android-36' 'build-tools;36.0.0' 'ndk;26.3.11579264' 'cmake;3.22.1'
gradle -p android --no-daemon :app:assembleDebug
```

Apply the SDL patch once per clean submodule checkout. CMake builds the host
asset tools and generates the required headers, graphics, maps, and songs
before compiling native game code. The APK is
`android/app/build/outputs/apk/debug/app-debug.apk`.

## Renderer selection

New Android ARM64 installations default to experimental voxel mode. Android
reads `voxelRenderer` from
`Android/data/com.pokeemerald.dualscreen/files/pokeemerald.cfg`:

```ini
voxelRenderer=1
```

Set it to `0` for classic 2D, then restart the app. Existing configurations
that already specify `0` keep classic mode. The public settings UI remains
unchanged. Voxel mode requests an SDL GLES 1.1 context with a depth buffer;
initialization failure falls back to classic rendering. The GLES compatibility
shim and voxel sources remain part of the Android native library.

The SDL2 backend is retained, with `switch.c` and `nx_sys.c` excluded. Selecting
`armeabi-v7a` in Gradle still uses the original four-byte layouts and default
classic renderer. The default APK contains only ARM64 libraries.

## Verification

```sh
python3 -m unittest discover -s tests/android-arm64 -v
make -f make_tools.mk
make -f tests/host-64bit/Makefile.host -j2
timeout 120s ./build/host-test/host_test
```

The targeted tests check native pointer relocations and packed bytecode,
including pointers above 4 GiB and legacy four-byte operands. They supplement
the full host smoke test and Android build; they do not establish device
runtime compatibility. The branch's `Android ARM64 and host smoke` workflow
builds both targets and uploads the debug APK and host smoke log.

Remaining Android-required pointer fixes cover field script operands and
command tables, generated map header/layout/group pointers, voice records,
field effect bytecode, and cry bytecode. Pip's battle operand readers, map
event layouts, save geometry, and VRAM fixes remain in place. Incoming Mystery
Event data retains its four-byte wire addresses while relocated pointers use
native width.

The release asset-hole tool also preserves the full native pointer width
around dynamic relocations. External GBA-format field-script payloads and
saved RAM scripts have four-byte event operands; their execution on ARM64
needs a separate format conversion. The incoming Mystery Event envelope
still uses four-byte addresses.
