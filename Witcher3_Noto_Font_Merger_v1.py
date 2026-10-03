#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Witcher 3 Noto Font Merger v1

Purpose:
    Merge NotoSans-Regular.ttf + NotoSansCJKsc-Regular.otf into ONE full
    TrueType font. No language subsetting is done here.

Policy:
    - Latin Noto Sans is preferred for every Unicode character it contains.
    - Noto Sans CJK SC fills characters missing from Latin Noto Sans.
    - CFF/CFF2 cubic outlines are converted to TrueType quadratic outlines.
    - The resulting .ttf can later be subset by the bilingual Witcher tool.

Requires:
    py -m pip install fonttools

Usage:
    py Witcher3_Noto_Font_Merger_v1.py ^
       "NotoSans-Regular.ttf" ^
       "NotoSansCJKsc-Regular.otf" ^
       -o "NotoSans_Witcher3_Universal.ttf"

WARNING:
    The merged font can be large. That is intentional. Do NOT feed the whole
    merged font directly to the Witcher bundle builder; subset it first.
"""

import argparse
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.recordingPen import DecomposingRecordingPen


def cmap_of(font):
    cmap = {}
    for table in font["cmap"].tables:
        if table.isUnicode():
            cmap.update(table.cmap)
    return cmap


def outline_to_ttglyph(source_font, glyph_name):
    """Works for both TrueType and CFF/CFF2 sources."""
    glyph_set = source_font.getGlyphSet()
    rec = DecomposingRecordingPen(glyph_set)
    glyph_set[glyph_name].draw(rec)

    pen = TTGlyphPen(None)
    quad = Cu2QuPen(pen, max_err=1.0, reverse_direction=False)
    rec.replay(quad)
    return pen.glyph()


def get_metric(font, glyph_name):
    return font["hmtx"][glyph_name]


def build_merged(latin_path, cjk_path, output_path):
    latin_path = Path(latin_path)
    cjk_path = Path(cjk_path)
    output_path = Path(output_path)

    print("Loading fonts...")
    latin = TTFont(latin_path, lazy=False)
    cjk = TTFont(cjk_path, lazy=False)

    latin_upm = latin["head"].unitsPerEm
    cjk_upm = cjk["head"].unitsPerEm
    if latin_upm != cjk_upm:
        raise ValueError(
            f"UPM mismatch: Noto Sans={latin_upm}, Noto Sans CJK SC={cjk_upm}. "
            "This v1 intentionally refuses metric rescaling."
        )
    upm = latin_upm

    latin_cmap = cmap_of(latin)
    cjk_cmap = cmap_of(cjk)

    # BMP is the useful target for the Witcher/Scaleform DefineFont3 workflow.
    all_codepoints = sorted(
        cp for cp in (set(latin_cmap) | set(cjk_cmap))
        if 0 < cp <= 0xFFFF
    )

    latin_used = sum(cp in latin_cmap for cp in all_codepoints)
    cjk_fill = sum(cp not in latin_cmap and cp in cjk_cmap for cp in all_codepoints)

    print(f"Noto Sans Unicode BMP:        {sum(0 < cp <= 0xFFFF for cp in latin_cmap):,}")
    print(f"Noto Sans CJK SC Unicode BMP: {sum(0 < cp <= 0xFFFF for cp in cjk_cmap):,}")
    print(f"Merged BMP characters:        {len(all_codepoints):,}")
    print(f"  from Noto Sans:              {latin_used:,}")
    print(f"  filled by Noto Sans CJK SC:  {cjk_fill:,}")
    print("")
    print("Converting outlines...")

    glyph_order = [".notdef"]
    glyphs = {}
    metrics = {}
    out_cmap = {}

    # Prefer Latin .notdef because Latin Noto Sans is the primary font.
    glyphs[".notdef"] = outline_to_ttglyph(latin, ".notdef")
    metrics[".notdef"] = get_metric(latin, ".notdef")

    total = len(all_codepoints)
    for i, cp in enumerate(all_codepoints, 1):
        if cp in latin_cmap:
            src = latin
            old_name = latin_cmap[cp]
        else:
            src = cjk
            old_name = cjk_cmap[cp]

        new_name = f"uni{cp:04X}"
        glyph_order.append(new_name)
        glyphs[new_name] = outline_to_ttglyph(src, old_name)
        metrics[new_name] = get_metric(src, old_name)
        out_cmap[cp] = new_name

        if i % 1000 == 0 or i == total:
            print(f"Converted: {i:,}/{total:,}")

    # Use Latin vertical metrics because it is the primary font.
    hhea = latin["hhea"]
    os2 = latin["OS/2"]

    print("Building TrueType tables...")
    fb = FontBuilder(upm, isTTF=True)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(out_cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(
        ascent=hhea.ascent,
        descent=hhea.descent,
        lineGap=hhea.lineGap,
    )
    fb.setupNameTable({
        "familyName": "Noto Sans Witcher 3 Universal",
        "styleName": "Regular",
        "uniqueFontIdentifier": "NotoSansWitcher3Universal-Regular",
        "fullName": "Noto Sans Witcher 3 Universal Regular",
        "psName": "NotoSansWitcher3Universal-Regular",
    })
    fb.setupOS2(
        sTypoAscender=os2.sTypoAscender,
        sTypoDescender=os2.sTypoDescender,
        sTypoLineGap=os2.sTypoLineGap,
        usWinAscent=max(os2.usWinAscent, cjk["OS/2"].usWinAscent),
        usWinDescent=max(os2.usWinDescent, cjk["OS/2"].usWinDescent),
        sxHeight=getattr(os2, "sxHeight", 0),
        sCapHeight=getattr(os2, "sCapHeight", 0),
    )
    fb.setupPost()
    fb.setupMaxp()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fb.save(output_path)

    print("Verifying output...")
    check = TTFont(output_path, lazy=False)
    check_cmap = cmap_of(check)
    missing = [cp for cp in all_codepoints if cp not in check_cmap]
    if missing:
        raise RuntimeError(f"Verification failed: {len(missing):,} cmap entries missing.")

    print("")
    print("SUCCESS")
    print(f"Output: {output_path}")
    print(f"Size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"Unicode BMP characters: {len(check_cmap):,}")
    print("")
    print("This is the SOURCE font for the bilingual tool.")
    print("Subset it according to selected languages before building the Witcher font MOD.")


def main():
    ap = argparse.ArgumentParser(
        description="Merge NotoSans-Regular.ttf and NotoSansCJKsc-Regular.otf into one TrueType source font."
    )
    ap.add_argument("latin_font", help="NotoSans-Regular.ttf")
    ap.add_argument("cjk_font", help="NotoSansCJKsc-Regular.otf")
    ap.add_argument(
        "-o", "--output",
        default="NotoSans_Witcher3_Universal.ttf",
        help="Output merged TrueType font"
    )
    args = ap.parse_args()

    try:
        build_merged(args.latin_font, args.cjk_font, args.output)
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
