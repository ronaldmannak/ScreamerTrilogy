#!/usr/bin/env python3
"""Decode original game loading artwork; no game code is executed or art generated."""
from pathlib import Path
import argparse
import binascii
import hashlib
import json
import struct
import zlib

ROOTS = {
    "screamer": Path("/Applications/Screamer.app/Contents/Resources/game"),
    "screamer2": Path("/Applications/Screamer 2.app/Contents/Resources/game"),
    "screamerrally": Path("/Applications/Screamer Rally.app/Contents/Resources/game/SR"),
}
SELECTED = {"screamer": "LOAD1H.PCX", "screamer2": "LOAD_1H.BKK", "screamerrally": "LOAD_1H.BKK"}

def lzw_decode(raw, wanted):
    width, next_code, old, bit = 9, 258, None, 0
    table = {i: bytes([i]) for i in range(256)}
    output = bytearray()
    while len(output) < wanted:
        if bit + width > len(raw) * 8:
            raise ValueError("LZW stream ended early")
        byte = bit // 8
        code = (int.from_bytes(raw[byte:byte+3], "little") >> (bit % 8)) & ((1 << width) - 1)
        bit += width
        if code == 256:
            width, next_code, old = 9, 258, None
            table = {i: bytes([i]) for i in range(256)}
            continue
        if code == 257:
            break
        if code in table:
            entry = table[code]
        elif old is not None and code == next_code:
            entry = old + old[:1]
        else:
            raise ValueError("Invalid LZW code")
        output.extend(entry)
        if old is not None and next_code < 4096:
            table[next_code] = old + entry[:1]
            next_code += 1
            if next_code >= (1 << width) and width < 12:
                width += 1
        old = entry
    if len(output) < wanted:
        raise ValueError("LZW output shorter than directory declaration")
    return bytes(output[:wanted])

def entries(path):
    data = path.read_bytes()
    directory_size = struct.unpack_from("<I", data, len(data)-4)[0]
    directory = data[-4-directory_size:-4]
    result = {}
    for at in range(0, len(directory)-31, 32):
        record = directory[at:at+32]
        name = bytes(x ^ 0x3a for x in record[:16]).split(b"\0")[0].decode("ascii")
        if not name:
            break
        offset, stored, size, flags = struct.unpack_from("<4I", record, 16)
        if offset + stored > len(data)-4-directory_size:
            raise ValueError("Archive entry extends into directory")
        payload = data[offset:offset+stored]
        if flags & 2:
            payload = lzw_decode(payload, size)
        result[name] = payload
    return result

def png_rgb(width, height, pixels):
    if len(pixels) != width*height*3:
        raise ValueError("Wrong RGB byte count")
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind+payload) & 0xffffffff)
    rows = b"".join(b"\0"+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))

def decode_pcx(data):
    if data[0] != 10 or data[2:4] != b"\x01\x08" or data[65] != 1:
        raise ValueError("Only original 8-bit, one-plane RLE PCX is supported")
    x0,y0,x1,y1 = struct.unpack_from("<4H", data, 4)
    width,height = x1-x0+1,y1-y0+1
    stride = struct.unpack_from("<H", data, 66)[0]
    if data[-769] != 12:
        raise ValueError("Missing PCX palette marker")
    palette = [data[-768+i*3:-768+i*3+3] if i < 255 else data[-3:] for i in range(256)]
    decoded = bytearray()
    at = 128
    while len(decoded) < stride*height:
        value = data[at]; at += 1
        if value & 0xc0 == 0xc0:
            count = value & 0x3f
            value = data[at]; at += 1
        else:
            count = 1
        decoded.extend(bytes([value])*count)
    indexes = b"".join(decoded[y*stride:y*stride+width] for y in range(height))
    return width,height,b"".join(palette[i] for i in indexes)

def decode_bkk(data):
    magic,count,width,height,pixel_count,_ = struct.unpack_from("<6I",data)
    if data[:4] != b"VK56" or count != 256 or pixel_count != width*height:
        raise ValueError("Unsupported original BKK format")
    colors = struct.unpack_from("<256H", data, 24)
    palette = []
    for color in colors:
        red,green,blue = (color >> 11)&31,(color >> 5)&63,color&31
        palette.append(bytes([(red<<3)|(red>>2),(green<<2)|(green>>4),(blue<<3)|(blue>>2)]))
    indexes = data[24+512:]
    if len(indexes) != width*height:
        raise ValueError("BKK size differs from dimensions")
    return width,height,b"".join(palette[i] for i in indexes)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--screamer-game", type=Path, default=ROOTS["screamer"])
    parser.add_argument("--screamer2-game", type=Path, default=ROOTS["screamer2"])
    parser.add_argument("--rally-game", type=Path, default=ROOTS["screamerrally"])
    args = parser.parse_args()
    roots = {"screamer":args.screamer_game, "screamer2":args.screamer2_game, "screamerrally":args.rally_game}
    manifest = []
    for key,root in roots.items():
        archive = root/"GFX"/("GRAF.DAT" if key == "screamer" else "GRAF2.DAT")
        items = entries(archive)
        for name,payload in items.items():
            if ("LOAD" not in name or (not name.endswith("H.PCX") and not name.endswith("H.BKK"))) and name != "LOGOH.BKK":
                continue
            if args.inspect:
                print(key, name, len(payload), payload[:32].hex(), struct.unpack_from("<6I", payload))
            if not args.inspect:
                width,height,rgb = decode_pcx(payload) if name.endswith(".PCX") else decode_bkk(payload)
                destination = args.output/key/(name[:-4]+".png")
                destination.parent.mkdir(parents=True,exist_ok=True)
                png = png_rgb(width,height,rgb)
                destination.write_bytes(png)
                if name == SELECTED[key]:
                    selected = args.output/key/"SelectionBackground.png"
                    selected.write_bytes(png)
                    manifest.append({"game":key, "source_archive":str(archive),
                                     "archive_sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
                                     "member":name, "member_sha256":hashlib.sha256(payload).hexdigest(),
                                     "output":str(selected.relative_to(args.output)),
                                     "png_sha256":hashlib.sha256(png).hexdigest(),
                                     "width":width,"height":height,
                                     "processing":"Original palette and pixels decoded to lossless PNG; no cropping, compositing, recoloring or AI generation."})
    if not args.inspect:
        (args.output/"provenance.json").write_text(json.dumps(manifest,indent=2)+"\n")
        print(json.dumps(manifest,indent=2))

if __name__ == "__main__":
    main()
