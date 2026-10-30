#!/usr/bin/env bash
# Compila GENBand: deja build/genband.bin (la ROM) y build/genband.sym (los símbolos, para las pruebas).
#
#   ./build.sh
#
# Necesita m68k-elf-gcc (brew install m68k-elf-gcc m68k-elf-binutils) y SGDK en tools/sgdk (ver README).
# No usa el makefile de SGDK: ese pide herramientas que solo vienen compiladas para Windows (o Java, para
# los recursos); aquí no hay recursos (los gráficos se generan en src/gfx.c) y la librería ya viene hecha.
set -euo pipefail
cd "$(dirname "$0")"

GDK="${GDK:-tools/sgdk}"
PREFIX="${PREFIX:-m68k-elf-}"
OUT=build
ROM="$OUT/genband.bin"

if ! command -v "${PREFIX}gcc" >/dev/null; then
    echo "Falta ${PREFIX}gcc: brew install m68k-elf-gcc m68k-elf-binutils" >&2
    exit 1
fi
if [ ! -f "$GDK/lib/libmd.a" ]; then
    echo "Falta SGDK en $GDK: git clone --depth 1 --branch v2.11 https://github.com/Stephane-D/SGDK.git $GDK" >&2
    exit 1
fi

mkdir -p "$OUT/obj"
CFLAGS=(-DSGDK_GCC -m68000 -O2 -fomit-frame-pointer -Wall -Wextra -Wno-main -Wno-unused-parameter
        -Wno-unterminated-string-initialization -fno-builtin -ffunction-sections -fdata-sections
        -fms-extensions -Isrc -I"$GDK/inc" -I"$GDK/res")

# La lista de canciones: todas las de src/songs/, en orden alfabético por título
songs=()
while IFS= read -r line; do songs+=("$line"); done < <(
    for f in src/songs/*/song.c; do
        [ -f "$f" ] || continue
        title=$(sed -n 's#^// TITULO: ##p' "$f" | head -1)
        printf '%s\t%s\n' "$title" "$(basename "$(dirname "$f")")"
    done | LC_ALL=C sort | cut -f2)
if [ ${#songs[@]} -eq 0 ]; then
    echo "No hay canciones en src/songs/ (ver genband import-song en el README)" >&2
    exit 1
fi
{
    echo "// Generado por build.sh: la lista de canciones del menú"
    echo '#include "song.h"'
    for s in "${songs[@]}"; do echo "extern const Song song_$s;"; done
    echo "const Song *const song_list[] = {"
    for s in "${songs[@]}"; do echo "    &song_$s,"; done
    echo "};"
    echo "const u16 song_count = ${#songs[@]};"
} > "$OUT/song_list.c"

# Cabecera de la ROM (rom_head.c se convierte a binario y sega.s lo incluye)
"${PREFIX}gcc" "${CFLAGS[@]}" -c src/boot/rom_head.c -o "$OUT/obj/rom_head.o"
"${PREFIX}objcopy" -O binary "$OUT/obj/rom_head.o" "$OUT/rom_head.bin"
sed "s#out/rom_head.bin#$OUT/rom_head.bin#" src/boot/sega.s > "$OUT/sega.s"
"${PREFIX}gcc" -x assembler-with-cpp -Wa,--register-prefix-optional,--bitwise-or "${CFLAGS[@]}" \
    -c "$OUT/sega.s" -o "$OUT/obj/sega.o"

objs=()
for src in src/*.c src/*.s src/songs/*/song.c "$OUT/song_list.c"; do
    obj="$OUT/obj/$(echo "${src%.*}" | tr '/' '_').o"
    "${PREFIX}gcc" "${CFLAGS[@]}" -c "$src" -o "$obj"
    objs+=("$obj")
done

# La librería de SGDK viene compilada con LTO de otra versión de GCC: se enlaza su código normal (-fno-lto)
"${PREFIX}gcc" -m68000 -n -T "$GDK/md.ld" -nostdlib -fno-lto "$OUT/obj/sega.o" "${objs[@]}" \
    "$GDK/lib/libmd.a" -lgcc -o "$OUT/genband.elf" -Wl,--gc-sections
"${PREFIX}objcopy" -O binary "$OUT/genband.elf" "$ROM"
"${PREFIX}nm" -n "$OUT/genband.elf" > "$OUT/genband.sym"

# Rellenar a un múltiplo de 128 KB, anotar el fin de la ROM en la cabecera y la suma de verificación
python3 - "$ROM" <<'PY'
import struct, sys
path = sys.argv[1]
rom = bytearray(open(path, "rb").read())
size = -(-len(rom) // 0x20000) * 0x20000
rom += b"\xff" * (size - len(rom))
struct.pack_into(">I", rom, 0x1A4, size - 1)
checksum = sum(struct.unpack_from(f">{(size - 0x200) // 2}H", rom, 0x200)) & 0xFFFF
struct.pack_into(">H", rom, 0x18E, checksum)
open(path, "wb").write(rom)
print(f"{path}: {size // 1024} KB, ", end="")
PY
echo "${#songs[@]} canciones"
