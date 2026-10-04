cmake_minimum_required(VERSION 3.22)
project(pokeemerald_android C ASM)

get_filename_component(ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../.." ABSOLUTE)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_program(HOST_MAKE make REQUIRED)
# Assemble and combine data with the same NDK toolchain as the game code.
get_filename_component(NDK_BIN "${CMAKE_C_COMPILER}" DIRECTORY)
find_program(NDK_LINKER ld.lld HINTS "${NDK_BIN}" NO_DEFAULT_PATH REQUIRED)
find_program(NDK_OBJCOPY llvm-objcopy HINTS "${NDK_BIN}" NO_DEFAULT_PATH REQUIRED)
set(GAME_DEFINES NONMATCHING PORTABLE PLATFORM_SDL2 RENDERER_EASY_DRAW MODERN=1 UBFIX)
set(ASSET_64BIT 0)
set(DATA_64BIT_ARGS)
if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    list(APPEND GAME_DEFINES PORTABLE_64BIT)
    set(ASSET_64BIT 1)
    list(APPEND DATA_64BIT_ARGS --portable-64bit)
endif()
set(CPP_DEFINES ${GAME_DEFINES})
list(TRANSFORM CPP_DEFINES PREPEND "-D")
string(JOIN " " CPP_DEFINE_FLAGS ${CPP_DEFINES})

# Generate incbins, map includes and MIDI sources before enumerating them.
# This path builds only host asset tools; no GBA objects enter the APK.
execute_process(COMMAND "${HOST_MAKE}" -f make_tools.mk
    WORKING_DIRECTORY "${ROOT}" COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND "${HOST_MAKE}" -f android/Makefile.assets "PORTABLE_64BIT=${ASSET_64BIT}"
    WORKING_DIRECTORY "${ROOT}" COMMAND_ERROR_IS_FATAL ANY)
set(SDL_STATIC ON CACHE BOOL "" FORCE)
set(SDL_SHARED ON CACHE BOOL "" FORCE)
set(SDL_TEST OFF CACHE BOOL "" FORCE)
add_subdirectory("${ROOT}/android/SDL2" "${CMAKE_BINARY_DIR}/SDL2")

file(GLOB_RECURSE GAME_C CONFIGURE_DEPENDS
    "${ROOT}/src/*.c"
    "${ROOT}/gflib/*.c")
list(FILTER GAME_C EXCLUDE REGEX "\\.inc\\.c$")
# Switch backend is not for Android (it includes <switch.h> unconditionally).
list(FILTER GAME_C EXCLUDE REGEX "src/platform/(switch|nx_sys)\\.c$")
file(GLOB_RECURSE C_INCLUDES CONFIGURE_DEPENDS
    "${ROOT}/include/*.h" "${ROOT}/gflib/*.h" "${ROOT}/src/*.h" "${ROOT}/src/*.inc.c")

set(GENERATED_C)
foreach(SOURCE IN LISTS GAME_C)
    file(RELATIVE_PATH RELATIVE_SOURCE "${ROOT}" "${SOURCE}")
    set(OUTPUT "${CMAKE_BINARY_DIR}/generated/${RELATIVE_SOURCE}")
    get_filename_component(OUTPUT_DIR "${OUTPUT}" DIRECTORY)
    add_custom_command(
        OUTPUT "${OUTPUT}"
        COMMAND "${CMAKE_COMMAND}" -E make_directory "${OUTPUT_DIR}"
        COMMAND /bin/sh -c "cd '${ROOT}' && '${CMAKE_C_COMPILER}' --target=${CMAKE_C_COMPILER_TARGET} --sysroot='${CMAKE_SYSROOT}' -E -std=gnu99 -iquote'${ROOT}/include' -iquote'${ROOT}/gflib' -I'${ROOT}/android/SDL2/include' ${CPP_DEFINE_FLAGS} '${SOURCE}' -o '${OUTPUT}.i' && '${ROOT}/tools/preproc/preproc' '${OUTPUT}.i' '${ROOT}/charmap.txt' > '${OUTPUT}'"
        DEPENDS "${SOURCE}" "${ROOT}/tools/preproc/preproc" "${ROOT}/charmap.txt" ${C_INCLUDES}
        VERBATIM)
    list(APPEND GENERATED_C "${OUTPUT}")
endforeach()

file(GLOB DATA_ASM CONFIGURE_DEPENDS "${ROOT}/data/*.s")
file(GLOB SONG_ASM CONFIGURE_DEPENDS "${ROOT}/sound/songs/*.s" "${ROOT}/sound/songs/midi/*.s")
set(GENERATED_ASM)
set(PREPARE_DATA "${CMAKE_CURRENT_LIST_DIR}/prepare_data.py")
# Includes affect data layout as well as source contents. Track them so a
# pointer macro or generated map include change also rebuilds data objects.
file(GLOB_RECURSE DATA_INCLUDES CONFIGURE_DEPENDS
    "${ROOT}/asm/*.inc" "${ROOT}/data/*.inc" "${ROOT}/include/*.h")
set(SPECIAL_IDS "${CMAKE_BINARY_DIR}/generated/special_ids.inc")
add_custom_command(
    OUTPUT "${SPECIAL_IDS}"
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${CMAKE_BINARY_DIR}/generated"
    COMMAND /bin/sh -c "awk '/^[[:space:]]+def_special[[:space:]]/ { printf \".set SPECIAL_%s, %d\\n\", $2, id++ }' '${ROOT}/data/specials.inc' > '${SPECIAL_IDS}'"
    DEPENDS "${ROOT}/data/specials.inc"
    VERBATIM)
foreach(SOURCE IN LISTS DATA_ASM SONG_ASM)
    file(RELATIVE_PATH RELATIVE_SOURCE "${ROOT}" "${SOURCE}")
    set(OUTPUT "${CMAKE_BINARY_DIR}/generated/${RELATIVE_SOURCE}.o")
    get_filename_component(OUTPUT_DIR "${OUTPUT}" DIRECTORY)
    if(SOURCE MATCHES "/sound/songs/")
        set(SOURCE_ARGS --song)
    else()
        set(SOURCE_ARGS --special-ids "${SPECIAL_IDS}")
    endif()
    add_custom_command(
        OUTPUT "${OUTPUT}"
        COMMAND "${Python3_EXECUTABLE}" "${PREPARE_DATA}"
            --root "${ROOT}" --source "${SOURCE}" --output "${OUTPUT}"
            --compiler "${CMAKE_C_COMPILER}" --target "${CMAKE_C_COMPILER_TARGET}"
            --sysroot "${CMAKE_SYSROOT}" ${DATA_64BIT_ARGS} ${SOURCE_ARGS}
        DEPENDS "${SOURCE}" "${PREPARE_DATA}" "${ROOT}/tools/preproc/preproc"
            "${ROOT}/charmap.txt" "${SPECIAL_IDS}" "${ROOT}/sound/MPlayDef.s" ${DATA_INCLUDES}
        VERBATIM)
    list(APPEND GENERATED_ASM "${OUTPUT}")
endforeach()

set(GAME_DATA_OBJECT "${CMAKE_BINARY_DIR}/generated/game_data.o")
add_custom_command(
    OUTPUT "${GAME_DATA_OBJECT}"
    COMMAND "${NDK_LINKER}" -r -o "${GAME_DATA_OBJECT}.tmp" ${GENERATED_ASM}
    COMMAND "${NDK_OBJCOPY}" --rename-section .rodata=.data,alloc,load,data,contents "${GAME_DATA_OBJECT}.tmp" "${GAME_DATA_OBJECT}"
    DEPENDS ${GENERATED_ASM}
    VERBATIM)
set_source_files_properties("${GAME_DATA_OBJECT}" PROPERTIES GENERATED TRUE EXTERNAL_OBJECT TRUE)

add_library(main SHARED ${GENERATED_C} "${GAME_DATA_OBJECT}")
target_include_directories(main PRIVATE
    "${ROOT}"
    "${ROOT}/sound"
    "${ROOT}/android/SDL2/include")
target_compile_definitions(main PRIVATE ${GAME_DEFINES})
target_compile_options(main PRIVATE
    -O3
    -fno-builtin
    -Wno-implicit-function-declaration
    "SHELL:-iquote '${ROOT}/include'"
    "SHELL:-iquote '${ROOT}/gflib'")
target_link_libraries(main PRIVATE SDL2::SDL2 m GLESv1_CM)
