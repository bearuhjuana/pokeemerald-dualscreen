#!/usr/bin/env python3
"""Preprocess game data for the ABI selected by Android's NDK toolchain."""

import argparse
import re
import subprocess
from pathlib import Path


def prepare_song(text, portable_64bit):
    # Song assembly contains bytecode and pointer directives, never numeric
    # 32-bit fields. Widen both checked-in .int songs and mid2agb .4byte songs.
    # Use line-anchored patterns to avoid mangling labels containing these
    # substrings (e.g. mus_abandoned_ship_8).
    pointer_op = ".8byte" if portable_64bit else ".int"
    text = re.sub(r"(?m)^(\s*)\.(?:4byte|8byte|word|int|long)\b", rf"\1{pointer_op}", text)
    text = re.sub(r"(?m)^(\s*)\.2byte\b", r"\1.short", text)
    text = re.sub(r"(?m)^\s*\.end\s*$", "", text)
    alignment = 8 if portable_64bit else 4
    text = re.sub(r"(?m)^(\s*)\.align\s+2\s*$", rf"\1.balign {alignment}", text)
    if not portable_64bit:
        text = re.sub(r"(?m)^(\s*)\.balign\s+8\s*$", r"\1.balign 4", text)

    # SongHeader has four bytes followed by an aligned native tone pointer.
    # Track branch operands remain unaligned bytecode pointers.
    globals_ = set(re.findall(r"(?m)^\s*\.global\s+(\w+)\s*$", text))
    lines = text.splitlines()
    headers = 0
    for index, line in enumerate(lines):
        label = re.fullmatch(r"\s*(\w+):\s*", line)
        if not label or label[1] not in globals_:
            continue
        header_bytes = 0
        padding_lines = []
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor].strip()
            if not candidate or candidate.startswith("#"):
                cursor += 1
                continue
            byte = re.fullmatch(r"\.byte\s+(.+)", candidate)
            padding = re.fullmatch(r"\.space\s+(\d+)", candidate)
            if byte:
                header_bytes += len(byte[1].split(","))
            elif padding:
                header_bytes += int(padding[1])
                padding_lines.append((cursor, int(padding[1])))
            elif candidate.startswith(pointer_op):
                if header_bytes == 4 and portable_64bit:
                    lines[cursor] = ".space 4\n" + lines[cursor]
                elif header_bytes == 8 and not portable_64bit and sum(size for _, size in padding_lines) == 4:
                    for padding_index, _ in padding_lines:
                        lines[padding_index] = ""
                elif header_bytes != (8 if portable_64bit else 4):
                    raise ValueError(f"Unexpected SongHeader layout for {label[1]}: {header_bytes} bytes")
                lines[index] = f".balign {alignment}\n" + lines[index]
                headers += 1
                break
            else:
                raise ValueError(f"Unexpected SongHeader directive for {label[1]}: {candidate}")
            cursor += 1
    if headers != 1:
        raise ValueError(f"Expected one exported SongHeader, found {headers}")
    return "\n".join(lines) + "\n"


def run(command, cwd, text=None):
    return subprocess.run(command, cwd=cwd, input=text, text=True,
                          stdout=subprocess.PIPE, check=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler")
    parser.add_argument("--target")
    parser.add_argument("--sysroot")
    parser.add_argument("--portable-64bit", action="store_true")
    parser.add_argument("--song", action="store_true")
    parser.add_argument("--song-only", action="store_true",
                        help="emit ABI-correct song assembly for the host harness")
    parser.add_argument("--special-ids", type=Path)
    args = parser.parse_args()
    if args.song_only:
        text = args.source.read_text()
        if re.search(r"(?m)^\s*\.include\s", text):
            root = args.root.resolve()
            text = run([str(root / "tools/preproc/preproc"), str(args.source.resolve()),
                        str(root / "charmap.txt")], root / "sound")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(prepare_song(text, args.portable_64bit))
        return
    if not (args.compiler and args.target and args.sysroot):
        parser.error("--compiler, --target and --sysroot are required for object generation")
    root = args.root.resolve()
    source = args.source.resolve()
    cwd = root / "sound" if args.song else root
    preproc = str(root / "tools/preproc/preproc")
    charmap = str(root / "charmap.txt")
    defines = ["MODERN=1", "PORTABLE=1", "UBFIX=1"]
    if args.portable_64bit:
        defines.append("PORTABLE_64BIT=1")
    text = run([preproc, str(source), charmap], cwd)
    compiler = [args.compiler, f"--target={args.target}", f"--sysroot={args.sysroot}"]
    text = run(compiler + ["-E", "-x", "assembler-with-cpp", f"-I{root / 'include'}"]
               + [f"-D{define}" for define in defines] + ["-"], cwd, text)
    text = run([preproc, "-ie", str(source), charmap], cwd, text)
    if args.song:
        text = prepare_song(text, args.portable_64bit)
    prefix = "".join(f".set {define.replace('=', ', ')}\n" for define in defines)
    if args.special_ids:
        prefix += f'.include "{args.special_ids.resolve()}"\n'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    asm = args.output.with_suffix(args.output.suffix + ".s")
    asm.write_text(prefix + text)
    # The integrated assembler emits the same target ELF as C compilation.
    # No GBA/ARMv7 object is ever passed to the arm64 linker.
    subprocess.run(compiler + ["-c", "-x", "assembler", "-fPIC", f"-I{root}",
                               f"-I{root / 'sound'}", str(asm), "-o", str(args.output)],
                   cwd=cwd, check=True)


if __name__ == "__main__":
    main()
