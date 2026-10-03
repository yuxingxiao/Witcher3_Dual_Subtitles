#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The Witcher 3 Remastered v164 Dual Subtitles (Polish + Chinese)

Pure-Python reader/writer for version 164 .w3strings.
No CSV conversion and no w3stringsr.exe are required.

Default behaviour:
- source: pl.w3strings
- target: zh.w3strings
- output replaces zh.w3strings
- original Chinese file is backed up as zh_backup.w3strings
- Polish is shown first, Chinese second
- follows the old dual-subtitle rule:
    Chinese length > 20 -> "<br> "
    otherwise          -> " "
- if processing fails, the original zh.w3strings is restored automatically.

IMPORTANT:
This script intentionally supports v164 only.
"""

from __future__ import annotations

import os
import shutil
import struct
import sys
import traceback
import subprocess
import importlib.util
import tempfile
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext


VERSION = 164
SOURCE_LANG = "pl"
TARGET_LANG = "zh"
BACKUP_NAME = "zh_backup.w3strings"

# Witcher 3 language key/magic values used by PL and ZH.
LANGUAGES = {
    "ar": {"key": 0x00000000, "magic": 0x00000000},
    "br": {"key": 0x00000000, "magic": 0x00000000},
    "cn": {"key": 0x00000000, "magic": 0x00000000},
    "esmx": {"key": 0x00000000, "magic": 0x00000000},
    "kr": {"key": 0x00000000, "magic": 0x00000000},
    "tr": {"key": 0x00000000, "magic": 0x00000000},
    "ua": {"key": 0x00000000, "magic": 0x00000000},
    "pl": {"key": 0x83496237, "magic": 0x73946816},
    "en": {"key": 0x43975139, "magic": 0x79321793},
    "de": {"key": 0x75886138, "magic": 0x42791159},
    "it": {"key": 0x45931894, "magic": 0x12375973},
    "fr": {"key": 0x23863176, "magic": 0x75921975},
    "cz": {"key": 0x24987354, "magic": 0x21793217},
    "es": {"key": 0x18796651, "magic": 0x42387566},
    "zh": {"key": 0x18632176, "magic": 0x16875467},
    "ru": {"key": 0x63481486, "magic": 0x42386347},
    "hu": {"key": 0x42378932, "magic": 0x67823218},
    "jp": {"key": 0x54834893, "magic": 0x59825646},
}
LANGUAGE_CHOICES = ["ar", "br", "cn", "cz", "de", "en", "es", "esmx", "fr", "hu", "it", "jp", "kr", "pl", "ru", "tr", "ua", "zh"]
HISTORY_FILE = ".witcher3_dual_subtitles_history.txt"


@dataclass
class Block1:
    string_id: int
    offset: int
    length: int
    text: str


@dataclass
class Block2:
    key_hash: int
    string_id: int


@dataclass
class W3Strings:
    version: int
    key1: int
    key2: int
    language: str
    block1: list[Block1]
    block2: list[Block2]
    block3_count: int


def read_bit6(data: bytes, pos: int) -> tuple[int, int]:
    """Read the Witcher 3 variable-length integer used for block counts."""
    result = 0
    shift = 0
    i = 1

    while True:
        if pos >= len(data):
            raise ValueError("Unexpected end of file while reading BIT6 value")

        b = data[pos]
        pos += 1

        s = 6
        mask = 0xFF

        if b > 127:
            mask = 127
            s = 7
        elif b > 63 and i == 1:
            mask = 63

        result |= (b & mask) << shift
        shift += s

        if b < 64 or (i >= 3 and b < 128):
            break

        i += 1
        if i > 8:
            raise ValueError("Invalid BIT6 value")

    return result, pos


def write_bit6(value: int) -> bytes:
    """Write the Witcher 3 variable-length integer used for block counts."""
    if value < 0:
        raise ValueError("BIT6 value cannot be negative")

    if value == 0:
        return bytes([128])

    parts = []
    left = value
    i = 0

    while left > 0:
        if i == 0:
            parts.append(left & 63)
            left >>= 6
        else:
            parts.append(left & 255)
            left >>= 7
        i += 1

    out = bytearray()
    length = len(parts)

    for i, val in enumerate(parts):
        last = i == length - 1
        cleft = (length - 1) - i

        if not last:
            if cleft >= 1 and i >= 1:
                val |= 128
            elif val < 64:
                val |= 64
            else:
                val |= 128

        if val == 128:
            raise ValueError("Invalid BIT6 encoding")

        out.append(val & 0xFF)

    return bytes(out)


def detect_language(key1: int, key2: int) -> str:
    key = ((key1 & 0xFFFF) << 16) | (key2 & 0xFFFF)
    for handle, info in LANGUAGES.items():
        if info["key"] == key:
            return handle
    raise ValueError(f"Unsupported language key: 0x{key:08X}")


def decrypt_v164_string(enc: bytes, magic: int) -> str:
    """
    v164 stores encrypted UTF-8 bytes.
    Offset and length are byte-based, unlike the old UTF-16 layout.
    """
    length = len(enc)
    string_key = (magic >> 8) & 0xFFFF
    dec = bytearray()

    for value in enc:
        char_key = ((length + 1) * string_key) & 0xFFFF
        dec.append(value ^ (char_key & 0xFF))
        string_key = ((string_key << 1) | (string_key >> 15)) & 0xFFFF

    return dec.decode("utf-8")


def encrypt_v164_string(text: str, magic: int) -> bytes:
    raw = text.encode("utf-8")
    length = len(raw)
    string_key = (magic >> 8) & 0xFFFF
    enc = bytearray()

    for value in raw:
        char_key = ((length + 1) * string_key) & 0xFFFF
        enc.append(value ^ (char_key & 0xFF))
        string_key = ((string_key << 1) | (string_key >> 15)) & 0xFFFF

    return bytes(enc)


def read_w3strings(path: str | Path, expected_language: str | None = None) -> W3Strings:
    path = Path(path)
    data = path.read_bytes()

    if len(data) < 12:
        raise ValueError(f"{path.name}: file is too small")

    if data[:4] != b"RTSW":
        raise ValueError(f"{path.name}: invalid RTSW signature")

    version = struct.unpack_from("<I", data, 4)[0]
    if version != VERSION:
        raise ValueError(
            f"{path.name}: this script supports v164 only; found version {version}"
        )

    key1 = struct.unpack_from("<H", data, 8)[0]
    key2 = struct.unpack_from("<H", data, len(data) - 2)[0]
    raw_key = ((key1 & 0xFFFF) << 16) | (key2 & 0xFFFF)

    if expected_language:
        if expected_language not in LANGUAGES:
            raise ValueError(f"{path.name}: unsupported expected language {expected_language}")
        expected_key = LANGUAGES[expected_language]["key"]
        if raw_key != expected_key:
            detected = detect_language(key1, key2)
            raise ValueError(
                f"{path.name}: expected language {expected_language}, detected {detected}"
            )
        # Several languages intentionally use key/magic 0, so the binary header
        # alone cannot distinguish ar/br/cn/esmx/kr/tr/ua. The filename/selection
        # supplied by the caller is authoritative for those files.
        language = expected_language
    else:
        language = detect_language(key1, key2)

    magic = LANGUAGES[language]["magic"]
    pos = 10

    block1_count, pos = read_bit6(data, pos)
    block1_meta = []

    for _ in range(block1_count):
        if pos + 12 > len(data):
            raise ValueError(f"{path.name}: truncated block 1")

        hashed_id, offset, length = struct.unpack_from("<III", data, pos)
        pos += 12

        string_id = hashed_id ^ magic
        block1_meta.append((string_id, offset, length))

    block2_count, pos = read_bit6(data, pos)
    block2 = []

    for _ in range(block2_count):
        if pos + 8 > len(data):
            raise ValueError(f"{path.name}: truncated block 2")

        key_hash, hashed_id = struct.unpack_from("<II", data, pos)
        pos += 8

        string_id = hashed_id ^ magic
        block2.append(Block2(key_hash=key_hash, string_id=string_id))

    block3_count, pos = read_bit6(data, pos)
    string_start = pos

    # v164 block3_count is the byte size of the encrypted string buffer.
    if string_start + block3_count + 2 > len(data):
        raise ValueError(f"{path.name}: invalid string buffer size")

    block1 = []

    for string_id, offset, length in block1_meta:
        start = string_start + offset
        end = start + length

        if start < string_start or end > string_start + block3_count:
            raise ValueError(
                f"{path.name}: invalid string range for ID {string_id}"
            )

        encrypted = data[start:end]

        try:
            text = decrypt_v164_string(encrypted, magic)
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"{path.name}: UTF-8 decode failed for string ID {string_id}: {exc}"
            ) from exc

        block1.append(
            Block1(
                string_id=string_id,
                offset=offset,
                length=length,
                text=text,
            )
        )

    return W3Strings(
        version=version,
        key1=key1,
        key2=key2,
        language=language,
        block1=block1,
        block2=block2,
        block3_count=block3_count,
    )


def write_w3strings(path: str | Path, obj: W3Strings) -> None:
    """
    Write a v164 file.

    We preserve block1/block2 entry order from the target Chinese file.
    String offsets and byte lengths are rebuilt.
    Each encrypted v164 string is followed by one 0x00 separator byte.
    """
    if obj.version != VERSION:
        raise ValueError("Writer supports v164 only")

    language = obj.language
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported output language: {language}")

    info = LANGUAGES[language]
    magic = info["magic"]
    expected_key = info["key"]

    key1 = (expected_key >> 16) & 0xFFFF
    key2 = expected_key & 0xFFFF

    string_buffer = bytearray()
    rebuilt_block1 = []

    for entry in obj.block1:
        encrypted = encrypt_v164_string(entry.text, magic)
        offset = len(string_buffer)
        length = len(encrypted)

        rebuilt_block1.append(
            Block1(
                string_id=entry.string_id,
                offset=offset,
                length=length,
                text=entry.text,
            )
        )

        string_buffer.extend(encrypted)
        # Real v164 files use one byte between strings.
        string_buffer.append(0)

    out = bytearray()
    out.extend(b"RTSW")
    out.extend(struct.pack("<I", VERSION))
    out.extend(struct.pack("<H", key1))

    out.extend(write_bit6(len(rebuilt_block1)))

    for entry in rebuilt_block1:
        hashed_id = entry.string_id ^ magic
        out.extend(
            struct.pack(
                "<III",
                hashed_id & 0xFFFFFFFF,
                entry.offset,
                entry.length,
            )
        )

    out.extend(write_bit6(len(obj.block2)))

    for entry in obj.block2:
        hashed_id = entry.string_id ^ magic
        out.extend(
            struct.pack(
                "<II",
                entry.key_hash & 0xFFFFFFFF,
                hashed_id & 0xFFFFFFFF,
            )
        )

    out.extend(write_bit6(len(string_buffer)))
    out.extend(string_buffer)
    out.extend(struct.pack("<H", key2))

    Path(path).write_bytes(out)


def visible_length(text: str) -> int:
    """
    Approximate the old script's len(value) behaviour, but ignore CR/LF
    and low control characters when deciding whether Chinese is "long".
    """
    cleaned = "".join(
        ch for ch in text
        if ch not in "\r\n" and (ord(ch) >= 32 or ch == "\t")
    )
    return len(cleaned.strip())


def merge_text(text1: str, text2: str, use_separator=False, separator=" - ") -> str:
    """
    Language 1 first, Language 2 second.

    If use_separator is enabled, the user-supplied separator replaces the
    legacy automatic space/<br> join. Otherwise the original behaviour is kept.
    Vanilla trailing control characters are preserved after the combined text.
    """
    if not text1:
        return text2
    if not text2:
        return text1
    if text1 == text2:
        return text2

    suffix = ""
    body = text1
    while body and ord(body[-1]) < 32:
        suffix = body[-1] + suffix
        body = body[:-1]
    body = body.rstrip()

    if use_separator:
        delimiter = separator
    else:
        delimiter = "<br> " if visible_length(text2) > 20 else " "

    suffix_without_crlf = suffix.replace("\r", "").replace("\n", "")
    return body + delimiter + text2 + suffix_without_crlf

def merge_files(source_path, target_path, output_path, source_lang, target_lang, log=print, use_separator=False, separator=" - "):
    log(f"Reading language 1 ({source_lang.upper()}): {source_path}")
    source = read_w3strings(source_path, source_lang)
    log(f"  {source_lang.upper()} v{source.version}: block1={len(source.block1):,}, block2={len(source.block2):,}")

    log(f"Reading language 2 ({target_lang.upper()}): {target_path}")
    target = read_w3strings(target_path, target_lang)
    log(f"  {target_lang.upper()} v{target.version}: block1={len(target.block1):,}, block2={len(target.block2):,}")

    source_by_id = {entry.string_id: entry.text for entry in source.block1}
    matched = changed = missing = 0
    new_block1 = []

    for entry in target.block1:
        text1 = source_by_id.get(entry.string_id)
        if text1 is None:
            missing += 1
            new_text = entry.text
        else:
            matched += 1
            new_text = merge_text(text1, entry.text, use_separator, separator)
            if new_text != entry.text:
                changed += 1
        new_block1.append(Block1(entry.string_id, 0, 0, new_text))

    merged = W3Strings(VERSION, target.key1, target.key2, target_lang,
                       new_block1, target.block2, 0)

    log(f"Matched IDs: {matched:,}")
    log(f"Modified {target_lang.upper()} strings: {changed:,}")
    log(f"{target_lang.upper()} IDs without {source_lang.upper()} match: {missing:,}")
    log(f"Writing: {output_path}")
    write_w3strings(output_path, merged)

    check = read_w3strings(output_path, target_lang)
    expected = {e.string_id: e.text for e in new_block1}
    actual = {e.string_id: e.text for e in check.block1}
    if expected != actual:
        raise ValueError("Round-trip text verification failed")
    if [(e.key_hash,e.string_id) for e in target.block2] != [(e.key_hash,e.string_id) for e in check.block2]:
        raise ValueError("Round-trip block2 verification failed")
    log(f"Round-trip OK: {len(check.block1):,} strings, {len(check.block2):,} keys")
    return {"matched": matched, "changed": changed, "missing": missing,
            "block1": len(check.block1), "block2": len(check.block2)}


def history_path(game_folder):
    return Path(game_folder) / HISTORY_FILE


def load_history(game_folder):
    p = history_path(game_folder)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("|")
        if len(parts) == 3:
            rows.append(tuple(parts))
    return rows


def record_history(game_folder, source_lang, target_lang, backup_name):
    p = history_path(game_folder)
    rows = [r for r in load_history(game_folder) if r[1] != target_lang]
    rows.append((source_lang, target_lang, backup_name))
    p.write_text("\n".join("|".join(r) for r in rows) + "\n", encoding="utf-8")


def process_game_folder(game_folder, source_lang, target_lang, log=print, use_separator=False, separator=" - "):
    game_folder = Path(game_folder)
    if source_lang == target_lang:
        raise ValueError("Language 1 and Language 2 must be different.")
    if not game_folder.is_dir():
        raise ValueError("Selected game folder does not exist")

    source_name = f"{source_lang}.w3strings"
    target_name = f"{target_lang}.w3strings"
    backup_name = f"{target_lang}_backup_before_dual.w3strings"
    successes, failures = 0, []

    log(f"Game folder: {game_folder}")
    log(f"Mode: pure Python v164 / {source_lang.upper()} + {target_lang.upper()}")
    log(f"Target: {target_name}")
    log("Scanning...\n")

    for root, dirs, files in os.walk(game_folder):
        if source_name not in files or target_name not in files:
            continue
        root = Path(root)
        source_file, target_file = root/source_name, root/target_name
        backup, temp = root/backup_name, root/f"{target_lang}.dual_build.tmp.w3strings"
        log("="*72); log(f"Folder: {root}")
        try:
            read_w3strings(source_file, source_lang)
            read_w3strings(target_file, target_lang)
            if not backup.exists():
                shutil.copy2(target_file, backup)
                log(f"Backup created: {backup}")
            else:
                shutil.copy2(backup, target_file)
                log(f"Original {target_lang.upper()} restored from existing backup before rebuild.")
            if temp.exists(): temp.unlink()
            stats = merge_files(source_file, target_file, temp, source_lang, target_lang, log, use_separator, separator)
            os.replace(temp, target_file)
            read_w3strings(target_file, target_lang)
            successes += 1
            log("SUCCESS\n")
        except Exception as exc:
            failures.append((str(root), str(exc))); log(f"FAILED: {exc}")
            try:
                if temp.exists(): temp.unlink()
                if backup.exists():
                    shutil.copy2(backup, target_file); log("Restored original target after failure.")
            except Exception as rexc:
                log(f"WARNING: restore also failed: {rexc}")
            log("")
    if successes:
        record_history(game_folder, source_lang, target_lang, backup_name)
    log("="*72); log(f"Done. Successfully processed folders: {successes}"); log(f"Failures: {len(failures)}")
    return successes, failures


def restore_from_record(game_folder, target_lang, backup_name, log=print):
    game_folder = Path(game_folder)
    restored = 0
    for root, dirs, files in os.walk(game_folder):
        if backup_name in files:
            root = Path(root)
            backup, target = root/backup_name, root/f"{target_lang}.w3strings"
            read_w3strings(backup, target_lang)
            shutil.copy2(backup, target)
            restored += 1
            log(f"Restored: {target}")
    log(f"Restored {restored} {target_lang.upper()} file(s).")
    return restored


def copy_mod_folder(source_folder, game_folder, mod_name, log=print):
    source = Path(source_folder)
    if not source.is_dir():
        raise ValueError(f"UI patch folder not found: {source}")
    mods = Path(game_folder) / "Mods"
    mods.mkdir(parents=True, exist_ok=True)
    dest = mods / mod_name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    log(f"UI adaptation installed: {dest}")
    return dest



FONT_SAFETY_TEXT = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "0123456789 "
    r"""!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~"""
    "\n\r\t"
)

def app_base_dir():
    """Directory containing the script, or the frozen EXE when packaged later."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_assets_dir():
    return app_base_dir() / "assets"


def bundled_ui_mod_dir():
    return bundled_assets_dir() / "modDualSubtitlesUI"


def bundled_font_mod_dir():
    return bundled_assets_dir() / "modUniversalWitcherFont"


def validate_bundled_assets(need_ui=False, need_font=False):
    problems = []
    if need_ui:
        p = bundled_ui_mod_dir()
        if not p.is_dir() or not (p / "content").is_dir():
            problems.append(
                f"Built-in UI MOD is missing or incomplete:\n  {p}\n"
                "Expected an assets\\modDualSubtitlesUI\\content folder."
            )
    if need_font:
        p = bundled_font_mod_dir()
        if not p.is_dir():
            problems.append(f"Built-in Universal Font MOD is missing:\n  {p}")
        else:
            bundle = p / "content" / "codebayin.bundle"
            metadata = p / "content" / "metadata.store"
            if not bundle.is_file() or not metadata.is_file():
                problems.append(
                    f"Built-in Universal Font MOD is incomplete:\n  {p}\n"
                    "Expected content\\bilingual.bundle and content\\metadata.store."
                )
    if problems:
        raise ValueError("\n\n".join(problems))


def install_prebuilt_font_mod(game_folder, source_mod, log=print):
    """Install a prebuilt, game-tested Universal Font MOD.

    No language scanning, font subsetting, fontTools processing, or runtime
    DefineFont3 generation is performed here.
    """
    game = Path(game_folder)
    source = Path(source_mod)
    if not source.is_dir():
        raise ValueError(f"Universal Font MOD folder not found: {source}")

    content = source / "content"
    if not content.is_dir():
        raise ValueError(
            "Selected Universal Font MOD folder has no 'content' directory."
        )

    # Our validated universal font MOD contains these files.  Requiring them
    # prevents accidentally selecting the parent Mods directory or another mod.
    bundle = content / "bilingual.bundle"
    metadata = content / "metadata.store"
    if not bundle.is_file() or not metadata.is_file():
        raise ValueError(
            "Selected folder is not the expected Universal Font MOD. "
            "Expected content\\bilingual.bundle and content\\metadata.store."
        )

    mods_dir = game / "Mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    dest = mods_dir / "modDualSubtitlesUniversalFont"

    # Avoid self-copy when the prepared MOD is already installed at destination.
    try:
        if source.resolve() == dest.resolve():
            log(f"Universal Font MOD already installed: {dest}")
            return dest
    except OSError:
        pass

    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(source, dest)
    log(f"Universal Font MOD installed: {dest}")
    return dest


class App:
    def __init__(self, root):
        self.root = root
        root.title("The Witcher 3 v164 Dual Subtitles + UI/Font v1.1")
        root.geometry("980x820")

        top = tk.Frame(root); top.pack(fill="x", padx=12, pady=12)
        tk.Label(top, text="The Witcher 3 game folder:", font=("Segoe UI",10,"bold")).pack(anchor="w")
        row=tk.Frame(top); row.pack(fill="x", pady=(6,8))
        self.folder_var=tk.StringVar(value=r"C:\SteamLibrary\steamapps\common\The Witcher 3")
        tk.Entry(row,textvariable=self.folder_var,font=("Consolas",10)).pack(side="left",fill="x",expand=True)
        tk.Button(row,text="Browse...",command=self.browse,width=12).pack(side="left",padx=(8,0))

        langrow=tk.Frame(top); langrow.pack(fill="x", pady=(4,6))
        tk.Label(langrow,text="Language 1 (first):").pack(side="left")
        self.lang1=tk.StringVar(value="pl")
        self.lang1_menu=tk.OptionMenu(langrow,self.lang1,*LANGUAGE_CHOICES)
        self.lang1_menu.pack(side="left",padx=(5,22))
        tk.Label(langrow,text="+   Language 2 (game/target):").pack(side="left")
        self.lang2=tk.StringVar(value="zh")
        self.lang2_menu=tk.OptionMenu(langrow,self.lang2,*LANGUAGE_CHOICES)
        self.lang2_menu.pack(side="left",padx=5)

        # Separator option
        sepframe=tk.LabelFrame(top,text="Bilingual separator",padx=8,pady=6)
        sepframe.pack(fill="x",pady=(4,6))
        self.use_separator=tk.BooleanVar(value=False)
        tk.Checkbutton(sepframe,text="Add a custom separator between Language 1 and Language 2",
                       variable=self.use_separator,command=self.update_separator_state).pack(side="left")
        tk.Label(sepframe,text="Separator:").pack(side="left",padx=(18,5))
        self.separator_var=tk.StringVar(value=" - ")
        self.separator_entry=tk.Entry(sepframe,textvariable=self.separator_var,width=14)
        self.separator_entry.pack(side="left")
        tk.Label(sepframe,text='Examples: " - "   " / "   " | "   " → "',
                 fg="#555555").pack(side="left",padx=(10,0))

        self.detected_var=tk.StringVar(value="Available languages: scanning...")
        tk.Label(top,textvariable=self.detected_var,justify="left",fg="#444444").pack(anchor="w",pady=(2,5))

        # UI adaptation
        uiframe=tk.LabelFrame(top,text="Bilingual menu adaptation",padx=8,pady=6)
        uiframe.pack(fill="x",pady=(4,6))
        self.install_ui=tk.BooleanVar(value=True)
        tk.Checkbutton(uiframe,text="Install built-in bilingual menu adaptation MOD",
                       variable=self.install_ui).pack(anchor="w")
        tk.Label(uiframe,
                 text="Built-in component: assets\\modDualSubtitlesUI  (no manual path selection required)",
                 fg="#555").pack(anchor="w",pady=(4,0))

        # Universal Font MOD
        fontframe=tk.LabelFrame(top,text="Universal font compatibility",padx=8,pady=6)
        fontframe.pack(fill="x",pady=(4,6))
        self.update_font=tk.BooleanVar(value=True)
        tk.Checkbutton(fontframe,text="Install built-in Universal Font MOD",
                       variable=self.update_font).pack(anchor="w")
        tk.Label(fontframe,
                 text="Built-in component: assets\\modUniversalWitcherFont  •  44,529 BMP glyphs  •  no runtime subsetting/rebuild",
                 fg="#555").pack(anchor="w",pady=(4,0))

        self.log_box=scrolledtext.ScrolledText(root,wrap="word",font=("Consolas",9))
        self.log_box.pack(fill="both",expand=True,padx=12,pady=(0,12))
        self.update_separator_state()
        self.log("Ready. Built-in UI/font components will be validated before Apply.")
        self.root.after(150, self.scan_languages)

    def browse(self):
        f=filedialog.askdirectory(title="Select The Witcher 3 game folder")
        if f:
            self.folder_var.set(f); self.scan_languages()

    def browse_ui(self):
        f=filedialog.askdirectory(title="Select prepared bilingual UI patch MOD folder")
        if f:self.ui_patch_var.set(f)


    def update_separator_state(self):
        self.separator_entry.config(state="normal" if self.use_separator.get() else "disabled")

    def set_menu_values(self, widget, variable, values):
        menu=widget["menu"]; menu.delete(0,"end")
        for value in values: menu.add_command(label=value,command=tk._setit(variable,value))

    def scan_languages(self):
        game=Path(self.folder_var.get().strip()); content0=game/"content"/"content0"
        if not content0.is_dir():
            self.detected_var.set(r"Available languages: default list (content\content0 not found)")
            self.set_menu_values(self.lang1_menu,self.lang1,LANGUAGE_CHOICES)
            self.set_menu_values(self.lang2_menu,self.lang2,LANGUAGE_CHOICES); return
        found=sorted(p.stem.lower() for p in content0.glob("*.w3strings")
                     if p.is_file() and "_backup" not in p.stem.lower() and ".dual_" not in p.stem.lower())
        ordered=[x for x in LANGUAGE_CHOICES if x in found]+[x for x in found if x not in LANGUAGE_CHOICES]
        if not ordered:
            ordered=LANGUAGE_CHOICES[:]; self.detected_var.set("Available languages: none detected; using default list")
        else:self.detected_var.set("Detected in content\\\\content0: "+", ".join(ordered))
        old1,old2=self.lang1.get(),self.lang2.get()
        self.set_menu_values(self.lang1_menu,self.lang1,ordered); self.set_menu_values(self.lang2_menu,self.lang2,ordered)
        if old1 not in ordered:self.lang1.set("pl" if "pl" in ordered else ordered[0])
        if old2 not in ordered:self.lang2.set("cn" if "cn" in ordered else ("zh" if "zh" in ordered else ordered[min(1,len(ordered)-1)]))

    def log(self,text):
        self.log_box.insert("end",str(text)+"\n"); self.log_box.see("end"); self.root.update_idletasks()
    def clear_log(self):self.log_box.delete("1.0","end")
    def set_busy(self,b):
        st="disabled" if b else "normal"; self.apply_btn.config(state=st); self.restore_btn.config(state=st); self.root.update_idletasks()

    def apply(self):
        self.scan_languages()
        folder=self.folder_var.get().strip(); l1=self.lang1.get(); l2=self.lang2.get()
        sep=self.separator_var.get()
        self.set_busy(True)
        try:
            self.log("="*72)
            self.log(f"Applying bilingual setup: {l1.upper()} + {l2.upper()}")
            if self.use_separator.get():
                self.log(f"Custom separator enabled: {sep!r}")
            else:self.log("Separator: legacy automatic space/<br> mode")

            # Validate optional built-in components before modifying any .w3strings files.
            validate_bundled_assets(self.install_ui.get(), self.update_font.get())

            ok,fail=process_game_folder(folder,l1,l2,self.log,self.use_separator.get(),sep)
            if ok==0 and not fail:
                raise RuntimeError(f"No folder containing both {l1}.w3strings and {l2}.w3strings was found.")
            if fail:
                raise RuntimeError(f"String merge completed with {len(fail)} failure(s).")

            if self.install_ui.get():
                copy_mod_folder(self.ui_patch_var.get().strip(),folder,"modDualSubtitlesUI",self.log)
            else:self.log("UI adaptation skipped by user.")

            if self.update_font.get():
                install_prebuilt_font_mod(folder, bundled_font_mod_dir(), self.log)
            else:self.log("Universal Font MOD installation skipped by user.")

            messagebox.showinfo("Success",
                f"Bilingual setup applied.\nProcessed string folders: {ok}\n"
                f"Set the game's text language to {l2.upper()}.")
        except Exception as e:
            self.log(traceback.format_exc()); messagebox.showerror("Error",str(e))
        finally:self.set_busy(False)

    def restore(self):
        folder=self.folder_var.get().strip(); rows=load_history(folder)
        if not rows:
            messagebox.showinfo("Restore","No recorded Apply operations were found for this game folder."); return
        win=tk.Toplevel(self.root); win.title("Restore from History"); win.geometry("520x300")
        tk.Label(win,text="Choose the previous string operation to restore:",font=("Segoe UI",10,"bold")).pack(anchor="w",padx=12,pady=(12,6))
        lb=tk.Listbox(win,font=("Consolas",10)); lb.pack(fill="both",expand=True,padx=12,pady=6)
        for l1,l2,bak in rows:lb.insert("end",f"{l1.upper()} + {l2.upper()}   → restore original {l2.upper()}")
        lb.selection_set(len(rows)-1)
        def do_restore():
            sel=lb.curselection()
            if not sel:return
            l1,l2,bak=rows[sel[0]]; win.destroy(); self.set_busy(True)
            try:
                n=restore_from_record(folder,l2,bak,self.log)
                messagebox.showinfo("Restore complete",f"Restored {n} {l2.upper()} file(s).\nUI/Universal Font MODs are left unchanged.")
            except Exception as e:
                self.log(traceback.format_exc()); messagebox.showerror("Error",str(e))
            finally:self.set_busy(False)
        tk.Button(win,text="Restore Selected",command=do_restore,height=2).pack(pady=(4,12))

def cli_test(source_path, target_path, output_path):
    source_lang = Path(source_path).stem.split(".")[0].lower()
    target_lang = Path(target_path).stem.split(".")[0].lower()
    stats = merge_files(source_path, target_path, output_path, source_lang, target_lang, print, False, " - ")
    print(stats)

def main():
    # Optional command-line test:
    # python witcher3_dual_subtitles_v164_pure.py pl.w3strings zh.w3strings out.w3strings
    if len(sys.argv) == 4:
        cli_test(sys.argv[1], sys.argv[2], sys.argv[3])
        return

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
