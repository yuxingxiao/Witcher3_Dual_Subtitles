#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Witcher 3 Universal Font Builder v0.6
Experimental single-file builder reconstructed from W3FontTool A/B samples.

Pipeline:
  TTF/OTF/TTC -> DefineFont3 -> replace fonts_cn main font in template SWF
  -> patch fixed POTATO70 bundle -> copy metadata.store -> MOD folder

IMPORTANT:
- This is the first game-test build, not a byte-identical W3FontTool clone.
- Keep the original W3FontTool MOD backed up.
- Uses the template bundle's fixed resource slot/header.
"""

import argparse
import hashlib
import json
import math
import shutil
import struct
import tempfile
import zlib
from pathlib import Path

from fontTools.ttLib import TTFont

VERSION = "0.6.4-universal"
SWF_FONT_NAME = "文鼎UD晶熙黑体G30_D"

OLD_BUNDLE_NAME = b"codebayin.bundle"
NEW_BUNDLE_NAME = b"bilingual.bundle"


# ------------------------- bit writer -------------------------

class BitWriter:
    def __init__(self):
        self.bits = []

    def ub(self, value, n):
        for i in range(n - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def sb(self, value, n):
        if value < 0:
            value = (1 << n) + value
        self.ub(value, n)

    def align(self):
        while len(self.bits) % 8:
            self.bits.append(0)

    def to_bytes(self):
        self.align()
        out = bytearray()
        for i in range(0, len(self.bits), 8):
            b = 0
            for bit in self.bits[i:i + 8]:
                b = (b << 1) | bit
            out.append(b)
        return bytes(out)


def signed_bits(*values):
    for n in range(2, 33):
        lo = -(1 << (n - 1))
        hi = (1 << (n - 1)) - 1
        if all(lo <= v <= hi for v in values):
            return n
    raise ValueError(f"Signed value too large: {values}")


def round_away(v):
    return int(math.floor(v + 0.5)) if v >= 0 else int(math.ceil(v - 0.5))


def rect_bytes(xmin, xmax, ymin, ymax):
    n = signed_bits(xmin, xmax, ymin, ymax)
    w = BitWriter()
    w.ub(n, 5)
    for v in (xmin, xmax, ymin, ymax):
        w.sb(v, n)
    return w.to_bytes()


# ------------------------- SWF shape records -------------------------

def emit_move(w, x, y, fill0=1):
    w.ub(0, 1)          # TypeFlag
    w.ub(0b00011, 5)    # StateMoveTo + StateFillStyle0
    n = signed_bits(x, y)
    w.ub(n, 5)
    w.sb(x, n)
    w.sb(y, n)
    w.ub(fill0, 1)


def emit_line(w, dx, dy):
    # Confirmed from W3FontTool samples: always GeneralLineFlag=1,
    # including horizontal and vertical edges.
    w.ub(1, 1)
    w.ub(1, 1)
    n = signed_bits(dx, dy)
    w.ub(n - 2, 4)
    w.ub(1, 1)          # GeneralLineFlag
    w.sb(dx, n)
    w.sb(dy, n)


def emit_curve(w, cdx, cdy, adx, ady):
    w.ub(1, 1)
    w.ub(0, 1)
    n = signed_bits(cdx, cdy, adx, ady)
    w.ub(n - 2, 4)
    for v in (cdx, cdy, adx, ady):
        w.sb(v, n)


def scaled_point(point, scale):
    return round_away(point[0] * scale), round_away(-point[1] * scale)


def contour_segments(points, oncurve, scale):
    pts = [scaled_point(p, scale) for p in points]
    ons = list(oncurve)
    if not pts:
        return None, []

    if ons[0]:
        start = pts[0]
        i = 1
    elif ons[-1]:
        start = pts[-1]
        i = 0
    else:
        start = (
            round_away((pts[-1][0] + pts[0][0]) / 2),
            round_away((pts[-1][1] + pts[0][1]) / 2),
        )
        i = 0

    current = start
    segments = []
    n = len(pts)
    consumed = 0

    while consumed < n:
        idx = i % n
        p = pts[idx]

        if ons[idx]:
            if p != current:
                segments.append(("L", p))
            current = p
            i += 1
            consumed += 1
        else:
            nxt = (idx + 1) % n
            q = pts[nxt]
            if ons[nxt]:
                end = q
                step = 2
            else:
                end = (
                    round_away((p[0] + q[0]) / 2),
                    round_away((p[1] + q[1]) / 2),
                )
                step = 1
            segments.append(("Q", p, end))
            current = end
            i += step
            consumed += step

    if current != start:
        segments.append(("L", start))

    return start, segments


def glyph_shape(font, glyph_name, scale):
    glyf = font["glyf"]
    glyph = glyf[glyph_name]
    coords, endpts, flags = glyph.getCoordinates(glyf)

    w = BitWriter()
    w.ub(1, 4)  # NumFillBits
    w.ub(0, 4)  # NumLineBits

    start_index = 0
    for end_index in endpts:
        points = [coords[i] for i in range(start_index, end_index + 1)]
        ons = [bool(flags[i] & 1) for i in range(start_index, end_index + 1)]
        start, segments = contour_segments(points, ons, scale)

        if start is not None:
            emit_move(w, *start)
            cur = start
            for item in segments:
                if item[0] == "L":
                    end = item[1]
                    emit_line(w, end[0] - cur[0], end[1] - cur[1])
                    cur = end
                else:
                    control, end = item[1], item[2]
                    emit_curve(
                        w,
                        control[0] - cur[0],
                        control[1] - cur[1],
                        end[0] - control[0],
                        end[1] - control[1],
                    )
                    cur = end

        start_index = end_index + 1

    w.ub(0, 1)
    w.ub(0, 5)  # EndShapeRecord
    return w.to_bytes()


# ------------------------- DefineFont3 -------------------------

def open_font(path):
    # TTC: W3FontTool behavior observed as first font.
    return TTFont(path, fontNumber=0)


def build_definefont3(font_path, codepoints):
    font = open_font(font_path)
    cmap = font.getBestCmap()
    if "glyf" not in font:
        raise RuntimeError(
            "v0.6 currently requires TrueType 'glyf' outlines. "
            "CFF/CFF2 OTF outlines are not implemented yet."
        )

    upm = font["head"].unitsPerEm
    scale = 20480.0 / upm
    cps = sorted({cp for cp in codepoints if 0 <= cp <= 0xFFFF and cp in cmap})

    if not cps:
        raise RuntimeError("No usable BMP glyphs found.")

    # DefineFont3 stores advances as signed 16-bit values. Very wide
    # Unicode punctuation can exceed that range after the 20.48x SWF scale.
    # Skip only those structurally unencodable glyphs and keep the rest of
    # the universal BMP font.
    bad_advances = []
    valid_cps = []
    for cp in cps:
        name = cmap[cp]
        advance, _ = font["hmtx"][name]
        scaled_advance = int(advance * scale)
        if not -32768 <= scaled_advance <= 32767:
            bad_advances.append((cp, name, advance, scaled_advance))
        else:
            valid_cps.append(cp)

    if bad_advances:
        print("")
        print("Skipping glyphs incompatible with DefineFont3 advance table:")
        for cp, name, advance, scaled in bad_advances:
            print(
                f"  U+{cp:04X} {chr(cp)!r} glyph={name!r} "
                f"source_advance={advance} scaled_advance={scaled}"
            )
        print(f"Skipped: {len(bad_advances):,}")
        print("")

    cps = valid_cps
    if not cps:
        raise RuntimeError("No glyphs remain after DefineFont3 compatibility filtering.")

    shapes, advances, bounds = [], [], []

    for cp in cps:
        name = cmap[cp]
        shapes.append(glyph_shape(font, name, scale))

        advance, _ = font["hmtx"][name]
        # Confirmed: W3FontTool truncates scaled advance toward zero.
        scaled_advance = int(advance * scale)
        if not -32768 <= scaled_advance <= 32767:
            ch = chr(cp)
            raise RuntimeError(
                "DefineFont3 advance exceeds signed 16-bit range:\n"
                f"  codepoint: U+{cp:04X}\n"
                f"  character: {ch!r}\n"
                f"  glyph: {name}\n"
                f"  source advance: {advance}\n"
                f"  unitsPerEm: {upm}\n"
                f"  SWF scale: {scale}\n"
                f"  scaled advance: {scaled_advance}\n"
                "This glyph cannot be encoded directly in DefineFont3."
            )
        advances.append(scaled_advance)

        g = font["glyf"][name]
        # Composite/empty glyphs may not carry cached xMin/xMax/yMin/yMax
        # until their bounds are recalculated.
        g.recalcBounds(font["glyf"])
        # Bounds quantization is not yet byte-identical to W3FontTool.
        # Empty glyphs (e.g. space) have no outline bounds.
        if hasattr(g, "xMin"):
            bounds.append((
                round_away(g.xMin * scale),
                round_away(g.xMax * scale),
                round_away(-g.yMax * scale),
                round_away(-g.yMin * scale),
            ))
        else:
            bounds.append((0, 0, 0, 0))

    name_bytes = SWF_FONT_NAME.encode("utf-8")
    flags = 0x80 | 0x08 | 0x04  # HasLayout | WideOffsets | WideCodes

    payload = bytearray()
    payload += struct.pack("<HBB", 1, flags, 0)
    payload += bytes([len(name_bytes)])
    payload += name_bytes
    payload += struct.pack("<H", len(cps))

    # Offsets are relative to start of OffsetTable.
    offset_table_size = 4 * len(cps) + 4
    offsets = []
    cursor = offset_table_size
    for shape in shapes:
        offsets.append(cursor)
        cursor += len(shape)
    code_table_offset = cursor

    for off in offsets:
        payload += struct.pack("<I", off)
    payload += struct.pack("<I", code_table_offset)

    for shape in shapes:
        payload += shape

    for cp in cps:
        payload += struct.pack("<H", cp)

    hhea = font["hhea"]
    ascent = round_away(hhea.ascent * scale)
    descent = round_away(-hhea.descent * scale)
    leading = round_away(hhea.lineGap * scale)
    payload += struct.pack("<hhh", ascent, descent, leading)

    for advance in advances:
        payload += struct.pack("<h", advance)

    for b in bounds:
        payload += rect_bytes(*b)

    # W3FontTool sample path currently indicates no generated kerning pairs
    # are required for our first replacement test.
    payload += struct.pack("<H", 0)

    meta = {
        "glyph_count": len(cps),
        "units_per_em": upm,
        "scale": scale,
        "definefont3_payload_bytes": len(payload),
        "first_codepoint": f"U+{cps[0]:04X}",
        "last_codepoint": f"U+{cps[-1]:04X}",
        "skipped_incompatible_advances": len(bad_advances),
        "skipped_codepoints": [f"U+{cp:04X}" for cp, _, _, _ in bad_advances],
    }
    return bytes(payload), meta


# ------------------------- SWF -------------------------

def extract_template_fws(bundle_path):
    raw = Path(bundle_path).read_bytes()
    off = raw.find(b"CWS")
    if off < 0:
        raise RuntimeError("No embedded CWS SWF found in template bundle.")

    version = raw[off + 3]
    declared = struct.unpack_from("<I", raw, off + 4)[0]
    obj = zlib.decompressobj()
    body = obj.decompress(raw[off + 8:])
    if not obj.eof:
        raise RuntimeError("Template CWS zlib stream is incomplete.")

    fws = b"FWS" + bytes([version]) + struct.pack("<I", declared) + body
    return fws, off


def first_tag_pos(swf):
    bit = 8 * 8

    def ub(n):
        nonlocal bit
        value = 0
        for _ in range(n):
            value = (value << 1) | ((swf[bit >> 3] >> (7 - (bit & 7))) & 1)
            bit += 1
        return value

    nbits = ub(5)
    bit += 4 * nbits
    bit = ((bit + 7) // 8) * 8
    return bit // 8 + 4  # FrameRate + FrameCount


def replace_first_definefont3(swf, new_payload):
    pos = first_tag_pos(swf)
    out = bytearray(swf[:pos])
    replaced = False

    while pos + 2 <= len(swf):
        tag_start = pos
        header = struct.unpack_from("<H", swf, pos)[0]
        pos += 2
        code = header >> 6
        length = header & 0x3F

        if length == 0x3F:
            length = struct.unpack_from("<I", swf, pos)[0]
            pos += 4

        payload_end = pos + length

        if code == 75 and not replaced:  # DefineFont3
            L = len(new_payload)
            if L < 0x3F:
                out += struct.pack("<H", (75 << 6) | L)
            else:
                out += struct.pack("<H", (75 << 6) | 0x3F)
                out += struct.pack("<I", L)
            out += new_payload
            replaced = True
        else:
            out += swf[tag_start:payload_end]

        pos = payload_end
        if code == 0:
            break

    if not replaced:
        raise RuntimeError("DefineFont3 tag not found.")

    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)


def make_cws(fws):
    return (
        b"CWS"
        + fws[3:4]
        + struct.pack("<I", len(fws))
        + zlib.compress(fws[8:], 9)
    )


# ------------------------- bundle/MOD -------------------------

def zlib_stream_end(raw, swf_offset):
    obj = zlib.decompressobj()
    obj.decompress(raw[swf_offset + 8:])
    if not obj.eof:
        raise RuntimeError("Could not find end of template CWS stream.")
    consumed_after_header = len(raw[swf_offset + 8:]) - len(obj.unused_data)
    return swf_offset + 8 + consumed_after_header


def patch_template_bundle(template_bundle, new_cws, output_bundle):
    raw = bytearray(Path(template_bundle).read_bytes())
    swf_offset = raw.find(b"CWS")
    if swf_offset < 0:
        raise RuntimeError("Template bundle has no CWS resource.")

    old_end = zlib_stream_end(bytes(raw), swf_offset)

    # A/B samples established a fixed-size bundle and zero-padded resource area.
    capacity = len(raw) - swf_offset
    if len(new_cws) > capacity:
        raise RuntimeError(
            f"Generated SWF is too large for this template resource slot: "
            f"{len(new_cws):,} > {capacity:,} bytes."
        )

    raw[swf_offset:] = b"\x00" * (len(raw) - swf_offset)
    raw[swf_offset:swf_offset + len(new_cws)] = new_cws
    Path(output_bundle).write_bytes(raw)

    return {
        "resource_offset": swf_offset,
        "old_cws_end": old_end,
        "new_cws_bytes": len(new_cws),
        "slot_capacity": capacity,
    }


def patch_metadata_bundle_name(metadata_store, output_path):
    raw = Path(metadata_store).read_bytes()
    if len(OLD_BUNDLE_NAME) != len(NEW_BUNDLE_NAME):
        raise RuntimeError("Bundle metadata rename must remain byte-length preserving.")

    count = raw.count(OLD_BUNDLE_NAME)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one {OLD_BUNDLE_NAME!r} entry in metadata.store, found {count}."
        )

    patched = raw.replace(OLD_BUNDLE_NAME, NEW_BUNDLE_NAME, 1)
    Path(output_path).write_bytes(patched)
    return {
        "metadata_bundle_name_old": OLD_BUNDLE_NAME.decode("ascii"),
        "metadata_bundle_name_new": NEW_BUNDLE_NAME.decode("ascii"),
        "metadata_bundle_name_offset": raw.find(OLD_BUNDLE_NAME),
        "metadata_bytes": len(patched),
    }


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def collect_codepoints(font_path, chars=None):
    font = open_font(font_path)
    cmap = font.getBestCmap()
    if chars is None:
        return sorted(cp for cp in cmap if cp <= 0xFFFF)
    return sorted({ord(ch) for ch in chars if ord(ch) <= 0xFFFF and ord(ch) in cmap})


def build_mod(font_path, template_bundle, metadata_store, output, chars=None):
    output = Path(output)
    content = output / "content"
    content.mkdir(parents=True, exist_ok=True)

    cps = collect_codepoints(font_path, chars)
    payload, font_meta = build_definefont3(font_path, cps)

    template_fws, _ = extract_template_fws(template_bundle)
    new_fws = replace_first_definefont3(template_fws, payload)
    new_cws = make_cws(new_fws)

    bundle_path = content / NEW_BUNDLE_NAME.decode("ascii")
    bundle_meta = patch_template_bundle(template_bundle, new_cws, bundle_path)

    # Keep metadata.store structurally identical, but rename the bundle
    # reference in-place. "codebayin.bundle" and "bilingual.bundle" are both
    # exactly 16 ASCII bytes, so all later offsets remain unchanged.
    metadata_path = content / "metadata.store"
    metadata_meta = patch_metadata_bundle_name(metadata_store, metadata_path)

    manifest = {
        "Owner": f"UniversalWitcherFont/{VERSION}",
        "Files": {
            "content/bilingual.bundle": sha256(bundle_path),
            "content/metadata.store": sha256(content / "metadata.store"),
        },
    }
    (output / "w3fonttool.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    report = {
        "version": VERSION,
        "font": str(Path(font_path).resolve()),
        **font_meta,
        "uncompressed_swf_bytes": len(new_fws),
        **bundle_meta,
        **metadata_meta,
        "bundle_bytes": bundle_path.stat().st_size,
        "metadata_sha256": sha256(metadata_path),
        "bundle_sha256": sha256(bundle_path),
        "status": "EXPERIMENTAL_FIRST_GAME_TEST",
    }
    (output / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main():
    ap = argparse.ArgumentParser(
        description="Witcher 3 universal BMP font MOD builder v0.6.3"
    )
    ap.add_argument("font", help="TTF/OTF/TTC input font")
    ap.add_argument("template_bundle", help="Known-good W3FontTool template bundle (usually codebayin.bundle)")
    ap.add_argument("metadata_store", help="Known-good W3FontTool metadata.store")
    ap.add_argument(
        "-o", "--output", default="modUniversalWitcherFont",
        help="Output MOD directory"
    )
    ap.add_argument(
        "--chars",
        help="Optional literal character set. If omitted, all available BMP cmap glyphs are used."
    )
    args = ap.parse_args()

    print(f"Witcher 3 Universal Font Builder v{VERSION}")
    print("Reading font...")
    report = build_mod(
        args.font,
        args.template_bundle,
        args.metadata_store,
        args.output,
        args.chars,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    print("Build complete:", Path(args.output).resolve())
    print("Universal build complete. Back up the existing font MOD before game testing.")


if __name__ == "__main__":
    main()
