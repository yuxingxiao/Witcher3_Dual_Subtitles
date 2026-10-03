#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The Witcher 3 Dual Subtitles v1.0.0

Pure-Python reader/writer for version 164 .w3strings.
No CSV conversion and no w3stringsr.exe are required.

Release build:
- Pure-Python v164 .w3strings reader/writer.
- One-click language scan, bilingual merge, UI MOD install, dynamic Universal Font MOD install.
- Transaction rollback on Apply failure and persistent Restore support.
- English / Simplified Chinese / Polish application UI.

IMPORTANT:
This release intentionally supports The Witcher 3 .w3strings version 164 only.
"""

from __future__ import annotations

import zlib
import os
import json
import shutil
import struct
import sys
import traceback
import tempfile
import webbrowser
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk


VERSION = 164
APP_VERSION = "1.0.0"
APP_NAME = "The Witcher 3 Dual Subtitles"
# Set this before publishing.
GITHUB_URL = "https://github.com/yuxingxiao/Witcher3_Dual_Subtitles"

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


COMPONENT_STATE_FILE = ".witcher3_dual_subtitles_components.json"
PERSISTENT_BACKUP_DIR = ".witcher3_dual_subtitles_backups"


def component_state_path(game_folder):
    return Path(game_folder) / COMPONENT_STATE_FILE


def load_component_state(game_folder):
    p = component_state_path(game_folder)
    if not p.exists():
        return {"mods": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"mods": {}}
        data.setdefault("mods", {})
        return data
    except Exception:
        return {"mods": {}}


def save_component_state(game_folder, state):
    p = component_state_path(game_folder)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def remember_original_mod(game_folder, mod_name, log=print):
    """Persist the state that existed before this tool first managed a MOD."""
    game = Path(game_folder)
    state = load_component_state(game)
    mods_state = state.setdefault("mods", {})
    if mod_name in mods_state:
        return

    dest = game / "Mods" / mod_name
    backup = game / PERSISTENT_BACKUP_DIR / "mods" / mod_name
    existed = dest.is_dir()

    if existed:
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(dest, backup)
        log(f"Saved pre-existing MOD backup: {backup}")

    mods_state[mod_name] = {
        "existed_before": existed,
        "backup": str(backup.relative_to(game)) if existed else None,
    }
    save_component_state(game, state)


def restore_managed_mod(game_folder, mod_name, log=print):
    """Restore the MOD state from before this tool first installed it."""
    game = Path(game_folder)
    state = load_component_state(game)
    info = state.get("mods", {}).get(mod_name)
    dest = game / "Mods" / mod_name

    if info is None:
        # No ownership record: do not delete an unknown user's MOD.
        log(f"No managed-state record for {mod_name}; left unchanged.")
        return False

    if dest.exists():
        shutil.rmtree(dest)

    if info.get("existed_before"):
        rel = info.get("backup")
        backup = game / rel if rel else None
        if not backup or not backup.is_dir():
            raise RuntimeError(f"Original backup for {mod_name} is missing: {backup}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(backup, dest)
        log(f"Restored pre-existing MOD: {dest}")
    else:
        log(f"Removed tool-installed MOD: {dest}")

    # Once restored, this component is no longer managed. A later Apply will
    # establish a fresh baseline from the then-current state.
    state["mods"].pop(mod_name, None)
    save_component_state(game, state)
    return True


class ApplyTransaction:
    """Exact pre-Apply snapshot used only for rollback if Apply fails."""

    def __init__(self, game_folder, target_lang, mod_names, log=print):
        self.game = Path(game_folder)
        self.target_lang = target_lang
        self.mod_names = list(mod_names)
        self.log = log
        self.tmp = None
        self.string_files = []
        self.mod_existed = {}

    def begin(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w3dual_txn_"))
        strings_dir = self.tmp / "strings"
        mods_dir = self.tmp / "mods"
        strings_dir.mkdir()
        mods_dir.mkdir()

        target_name = f"{self.target_lang}.w3strings"
        i = 0
        for root, dirs, files in os.walk(self.game):
            # Do not snapshot our own persistent backup area.
            rootp = Path(root)
            if PERSISTENT_BACKUP_DIR in rootp.parts:
                continue
            if target_name in files:
                src = rootp / target_name
                rel = src.relative_to(self.game)
                snap = strings_dir / f"{i:05d}.w3strings"
                shutil.copy2(src, snap)
                self.string_files.append((rel, snap))
                i += 1

        for mod_name in self.mod_names:
            src = self.game / "Mods" / mod_name
            existed = src.is_dir()
            self.mod_existed[mod_name] = existed
            if existed:
                shutil.copytree(src, mods_dir / mod_name)

        self.log(
            f"Transaction snapshot created: {len(self.string_files)} target string file(s), "
            f"{len(self.mod_names)} managed MOD slot(s)."
        )

    def rollback(self):
        if not self.tmp:
            return
        self.log("Apply failed; rolling back to the exact pre-Apply state...")
        for rel, snap in self.string_files:
            dest = self.game / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snap, dest)

        for mod_name in self.mod_names:
            dest = self.game / "Mods" / mod_name
            if dest.exists():
                shutil.rmtree(dest)
            snap = self.tmp / "mods" / mod_name
            if self.mod_existed.get(mod_name) and snap.is_dir():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(snap, dest)

        self.log("Rollback complete.")

    def close(self):
        if self.tmp and self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp = None


def copy_mod_folder(source_folder, game_folder, mod_name, log=print):
    source = Path(source_folder)
    if not source.is_dir():
        raise ValueError(f"MOD source folder not found: {source}")
    remember_original_mod(game_folder, mod_name, log)
    mods = Path(game_folder) / "Mods"
    mods.mkdir(parents=True, exist_ok=True)
    dest = mods / mod_name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    log(f"MOD installed: {dest}")
    return dest




# ---------------------------------------------------------------------------
# Dynamic multi-language Universal Font MOD
# ---------------------------------------------------------------------------

# Dedicated Scaleform font libraries. Other supported Latin languages in the
# game's fonts.xml resolve to EN, so they use the EN slot.
DIRECT_FONT_SLOTS = {"cn", "zh", "jp", "kr", "ar", "ru", "ua", "en"}

def font_slot_for_language(lang):
    lang = (lang or "").strip().lower()
    return lang if lang in DIRECT_FONT_SLOTS else "en"


def app_base_dir():
    """Directory containing the user-visible EXE, or the source script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_resource_dir():
    """Read-only bundled-resource root.

    Source mode: directory containing this script.
    PyInstaller onedir/onefile: sys._MEIPASS, where --add-data resources live.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent


def bundled_assets_dir():
    return bundled_resource_dir() / "assets"


def bundled_ui_mod_dir():
    return bundled_assets_dir() / "modDualSubtitlesUI"


def bundled_font_base_dir():
    # User supplies the already-tested Universal CN MOD here.
    return bundled_assets_dir() / "modDualSubtitlesFontBase"


def bundled_font_templates_dir():
    # Original fonts_xx.swf files exported from REDkit.
    return bundled_assets_dir() / "font_templates"


def _read_swf_rect_end(data, start_bit=64):
    """Return byte offset immediately after the SWF RECT field."""
    bit = start_bit

    def ub(n):
        nonlocal bit
        v = 0
        for _ in range(n):
            byte_i = bit >> 3
            if byte_i >= len(data):
                raise ValueError("Truncated SWF RECT.")
            v = (v << 1) | ((data[byte_i] >> (7 - (bit & 7))) & 1)
            bit += 1
        return v

    nbits = ub(5)
    bit += 4 * nbits
    bit = ((bit + 7) // 8) * 8
    return bit // 8


def _swf_first_tag_pos(fws):
    # Header (8) + RECT + FrameRate UI16 + FrameCount UI16.
    return _read_swf_rect_end(fws) + 4


def _swf_to_fws(raw):
    if raw[:3] == b"FWS":
        return raw
    if raw[:3] != b"CWS":
        raise ValueError("Expected an FWS/CWS SWF.")
    if len(raw) < 8:
        raise ValueError("Truncated CWS.")
    declared = struct.unpack_from("<I", raw, 4)[0]
    body = zlib.decompress(raw[8:])
    fws = b"FWS" + raw[3:4] + struct.pack("<I", declared) + body
    if len(fws) != declared:
        raise ValueError(
            f"SWF decompression length mismatch: declared={declared}, actual={len(fws)}"
        )
    return fws


def _swf_to_cws(fws):
    if fws[:3] != b"FWS":
        raise ValueError("Expected FWS.")
    raw = bytearray(fws)
    struct.pack_into("<I", raw, 4, len(raw))
    return b"CWS" + bytes(raw[3:4]) + struct.pack("<I", len(raw)) + zlib.compress(bytes(raw[8:]), 9)


def _iter_swf_tags(fws):
    pos = _swf_first_tag_pos(fws)
    while pos + 2 <= len(fws):
        start = pos
        header = struct.unpack_from("<H", fws, pos)[0]
        pos += 2
        code = header >> 6
        length = header & 0x3F
        if length == 0x3F:
            if pos + 4 > len(fws):
                raise ValueError("Truncated long SWF tag.")
            length = struct.unpack_from("<I", fws, pos)[0]
            pos += 4
        payload_start = pos
        end = pos + length
        if end > len(fws):
            raise ValueError("Truncated SWF tag payload.")
        yield code, fws[payload_start:end], start, end
        pos = end
        if code == 0:
            break


def _first_definefont3(fws):
    # DefineFont3 tag code = 75.
    for code, payload, start, end in _iter_swf_tags(fws):
        if code == 75:
            if len(payload) < 6:
                raise ValueError("Malformed DefineFont3.")
            font_id = struct.unpack_from("<H", payload, 0)[0]
            name_len = payload[4]
            if 5 + name_len + 2 > len(payload):
                raise ValueError("Malformed DefineFont3 font name.")
            name_bytes = payload[5:5 + name_len]
            return {
                "font_id": font_id,
                "name_bytes": name_bytes,
                "payload": payload,
                "start": start,
                "end": end,
            }
    raise ValueError("No DefineFont3 found in SWF.")


def _retarget_definefont3_payload(universal_payload, target_font_id, target_name_bytes):
    """Keep the Universal glyph data but preserve target SWF FontID/name.

    DefineFont3 begins:
      UI16 FontID
      UI8  FontFlags
      UI8  LanguageCode
      UI8  FontNameLen
      UI8[] FontName
      UI16 NumGlyphs
      ...
    Everything from NumGlyphs onward is copied unchanged from the already
    game-tested Universal DefineFont3.
    """
    if len(universal_payload) < 7:
        raise ValueError("Universal DefineFont3 is malformed.")
    old_name_len = universal_payload[4]
    tail = universal_payload[5 + old_name_len:]
    if len(target_name_bytes) > 255:
        raise ValueError("Target embedded font name is too long.")
    return (
        struct.pack("<H", target_font_id)
        + universal_payload[2:4]
        + bytes([len(target_name_bytes)])
        + target_name_bytes
        + tail
    )


def _replace_first_definefont3(fws, new_payload):
    pos = _swf_first_tag_pos(fws)
    out = bytearray(fws[:pos])
    replaced = False

    while pos + 2 <= len(fws):
        start = pos
        header = struct.unpack_from("<H", fws, pos)[0]
        pos += 2
        code = header >> 6
        length = header & 0x3F
        if length == 0x3F:
            length = struct.unpack_from("<I", fws, pos)[0]
            pos += 4
        end = pos + length

        if code == 75 and not replaced:
            n = len(new_payload)
            out += struct.pack("<H", (75 << 6) | (n if n < 0x3F else 0x3F))
            if n >= 0x3F:
                out += struct.pack("<I", n)
            out += new_payload
            replaced = True
        else:
            out += fws[start:end]

        pos = end
        if code == 0:
            break

    if not replaced:
        raise ValueError("Target SWF has no DefineFont3 to replace.")

    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)


def _extract_embedded_cws_from_bundle(bundle_bytes):
    """Extract the first CWS stream from a POTATO70 bundle.

    zlib.decompressobj().unused_data lets us identify the exact compressed
    stream length even when the bundle reserves a larger zero-padded slot.
    """
    off = bundle_bytes.find(b"CWS")
    if off < 0:
        raise ValueError("No embedded CWS found in bilingual.bundle.")
    if off + 8 > len(bundle_bytes):
        raise ValueError("Truncated embedded CWS.")

    dec = zlib.decompressobj()
    compressed_tail = bundle_bytes[off + 8:]
    body = dec.decompress(compressed_tail)
    body += dec.flush()
    consumed_after_header = len(compressed_tail) - len(dec.unused_data)
    cws_len = 8 + consumed_after_header
    cws = bundle_bytes[off:off + cws_len]

    declared = struct.unpack_from("<I", cws, 4)[0]
    fws = b"FWS" + cws[3:4] + struct.pack("<I", declared) + body
    if len(fws) != declared:
        raise ValueError(
            f"Embedded SWF length mismatch: declared={declared}, actual={len(fws)}"
        )
    return off, cws_len, fws


def _patch_same_length_ascii(raw, old, new, label):
    if len(old) != len(new):
        raise ValueError(f"{label} length differs: {old!r} -> {new!r}")
    count = raw.count(old)
    if count < 1:
        raise ValueError(f"{label} not found in base resource: {old!r}")
    return raw.replace(old, new), count


def _build_dynamic_font_mod(target_lang, output_mod_dir, log=print):
    """Build modDualSubtitlesFont for the language actually loaded by the game.

    The base bilingual.bundle already contains the game-tested 44,529-glyph
    Universal DefineFont3 in fonts_cn.redswf. We extract that DefineFont3 and
    transplant it into the original target-language SWF, preserving that SWF's
    FontID, embedded font name, and all other tags.

    The release uses the prepared Universal font data already embedded in the base bundle.
    """
    slot = font_slot_for_language(target_lang)
    base_dir = bundled_font_base_dir()
    templates = bundled_font_templates_dir()

    base_bundle_path = base_dir / "content" / "bilingual.bundle"
    base_meta_path = base_dir / "content" / "metadata.store"
    target_swf_path = templates / f"fonts_{slot}.swf"

    if not base_bundle_path.is_file():
        raise ValueError(
            f"Missing tested base bundle:\n  {base_bundle_path}\n"
            "Put your working bilingual.bundle there."
        )
    if not base_meta_path.is_file():
        raise ValueError(
            f"Missing tested base metadata:\n  {base_meta_path}"
        )
    if not target_swf_path.is_file():
        raise ValueError(
            f"Missing original font template for {slot.upper()}:\n  {target_swf_path}"
        )

    bundle = base_bundle_path.read_bytes()
    swf_off, old_cws_len, universal_fws = _extract_embedded_cws_from_bundle(bundle)
    universal_font = _first_definefont3(universal_fws)

    target_fws = _swf_to_fws(target_swf_path.read_bytes())
    target_font = _first_definefont3(target_fws)

    new_font_payload = _retarget_definefont3_payload(
        universal_font["payload"],
        target_font["font_id"],
        target_font["name_bytes"],
    )
    new_target_fws = _replace_first_definefont3(target_fws, new_font_payload)
    new_target_cws = _swf_to_cws(new_target_fws)

    # The proven bundle reserves everything from the embedded SWF offset to EOF
    # for the SWF slot. Keep total bundle size and zero-fill unused capacity.
    capacity = len(bundle) - swf_off
    if len(new_target_cws) > capacity:
        raise ValueError(
            f"{slot.upper()} Universal SWF does not fit the tested bundle slot: "
            f"{len(new_target_cws):,} > {capacity:,} bytes."
        )

    old_resource = b"gameplay\\gui_new\\swf\\witcher3\\fonts_cn.redswf"
    new_resource = (
        f"gameplay\\gui_new\\swf\\witcher3\\fonts_{slot}.redswf"
    ).encode("ascii")

    patched_bundle, bundle_path_hits = _patch_same_length_ascii(
        bundle, old_resource, new_resource, "bundle resource path"
    )
    patched_bundle = bytearray(patched_bundle)
    patched_bundle[swf_off:] = b"\x00" * capacity
    patched_bundle[swf_off:swf_off + len(new_target_cws)] = new_target_cws

    metadata = base_meta_path.read_bytes()
    patched_meta, meta_path_hits = _patch_same_length_ascii(
        metadata, old_resource, new_resource, "metadata resource path"
    )

    out = Path(output_mod_dir)
    if out.exists():
        shutil.rmtree(out)
    content = out / "content"
    content.mkdir(parents=True, exist_ok=True)

    (content / "bilingual.bundle").write_bytes(patched_bundle)
    (content / "metadata.store").write_bytes(patched_meta)

    # Preserve optional sidecars such as info.json from the base MOD.
    for p in base_dir.iterdir():
        if p.name == "content":
            continue
        if p.is_file():
            shutil.copy2(p, out / p.name)
    base_content = base_dir / "content"
    if base_content.is_dir():
        for p in base_content.iterdir():
            if p.name in ("bilingual.bundle", "metadata.store"):
                continue
            if p.is_file():
                shutil.copy2(p, content / p.name)

    try:
        uname = universal_font["name_bytes"].decode("utf-8", "replace")
        tname = target_font["name_bytes"].decode("utf-8", "replace")
    except Exception:
        uname = repr(universal_font["name_bytes"])
        tname = repr(target_font["name_bytes"])

    log(
        f"Dynamic Universal Font: Language {target_lang.upper()} -> "
        f"{slot.upper()} font slot"
    )
    log(
        f"Universal DefineFont3: FontID={universal_font['font_id']}, "
        f"name={uname!r}"
    )
    log(
        f"Target DefineFont3 preserved identity: FontID={target_font['font_id']}, "
        f"name={tname!r}"
    )
    log(
        f"Generated target CWS: {len(new_target_cws):,} bytes / "
        f"bundle slot {capacity:,} bytes"
    )
    log(
        f"Resource path patched: bundle={bundle_path_hits} occurrence(s), "
        f"metadata={meta_path_hits} occurrence(s)"
    )
    return out


def validate_bundled_assets(need_ui=False, need_font=False, game_folder=None, target_lang=None):
    problems = []
    if need_ui:
        p = bundled_ui_mod_dir()
        if not p.is_dir() or not (p / "content").is_dir():
            problems.append(
                f"Built-in UI MOD is missing or incomplete:\n  {p}\n"
                "Expected assets\\modDualSubtitlesUI\\content."
            )

    if need_font:
        slot = font_slot_for_language(target_lang)
        base = bundled_font_base_dir()
        bundle = base / "content" / "bilingual.bundle"
        meta = base / "content" / "metadata.store"
        template = bundled_font_templates_dir() / f"fonts_{slot}.swf"
        if not bundle.is_file():
            problems.append(f"Missing base Universal bundle:\n  {bundle}")
        if not meta.is_file():
            problems.append(f"Missing base metadata.store:\n  {meta}")
        if not template.is_file():
            problems.append(
                f"Missing {slot.upper()} font template:\n  {template}"
            )

    if problems:
        raise ValueError("\n\n".join(problems))


def install_dynamic_font_mod(game_folder, target_lang, log=print):
    """Generate the correct language font resource and install it transactionally."""
    game = Path(game_folder)
    mod_name = "modDualSubtitlesFont"
    remember_original_mod(game_folder, mod_name, log)

    tmp_root = Path(tempfile.mkdtemp(prefix="w3dual_font_"))
    try:
        generated = tmp_root / mod_name
        _build_dynamic_font_mod(target_lang, generated, log)

        mods_dir = game / "Mods"
        mods_dir.mkdir(parents=True, exist_ok=True)
        dest = mods_dir / mod_name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(generated, dest)
        log(f"Universal Font MOD installed: {dest}")
        return dest
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Release UI
# ---------------------------------------------------------------------------

UI_TEXT = {
    "en": {
        "ui_name": "English",
        "title": "The Witcher 3 Dual Subtitles v1.0.0",
        "game_folder": "The Witcher 3 game folder",
        "browse": "Browse…",
        "lang1": "Language 1 (first)",
        "lang2": "Language 2 (game / target)",
        "separator_group": "Bilingual separator",
        "separator_check": "Use a custom separator between Language 1 and Language 2",
        "separator": "Separator",
        "separator_examples": 'Examples: " - "   " / "   " | "   " → "',
        "scanning": "Available languages: scanning…",
        "default_languages": r"Available languages: default list (content\content0 not found)",
        "none_detected": "Available languages: none detected; using default list",
        "detected": r"Detected in content\content0: {langs}",
        "ui_group": "Bilingual menu adaptation",
        "ui_check": "Install bilingual menu adaptation MOD",
        "ui_desc": r"Built-in component: assets\modDualSubtitlesUI",
        "font_group": "Universal font compatibility",
        "font_check": "Install Universal Font MOD",
        "font_desc": "Automatically builds the correct font slot for Language 2",
        "apply": "Apply",
        "restore": "Restore",
        "clear": "Clear Log",
        "ready": "Ready. Components will be validated before Apply.",
        "select_game": "Select The Witcher 3 game folder",
        "success": "Success",
        "success_body": "Bilingual setup applied.\nProcessed string folders: {count}\nSet the game's text language to {lang}.",
        "error": "Error",
        "restore_title": "Restore",
        "restore_changes": "Restore bilingual changes",
        "restore_desc": "Restore the selected original language file and return UI/font MODs to their pre-tool state.",
        "restore_none": "No recorded string operations or managed UI/font components were found for this game folder.",
        "restore_original": "{a} + {b}   → restore original {b}",
        "restore_button": "Restore selected + UI / Font",
        "restore_done": "Restore complete",
        "restore_done_body": "Restored string files: {strings}\nRestored/removed managed UI/font MODs: {mods}",
        "ui_language": "Interface",
        "cn_label": "cn (Simplified Chinese)",
        "zh_label": "zh (Traditional Chinese)",
        "footer": "Dev. Yuxing Łódź",
        "unofficial": "Unofficial fan-made tool • Not approved or endorsed by CD PROJEKT RED",
    },
    "zh": {
        "ui_name": "中文",
        "title": "The Witcher 3 Dual Subtitles v1.0.0",
        "game_folder": "《巫师 3》游戏目录",
        "browse": "浏览…",
        "lang1": "语言 1（显示在前）",
        "lang2": "语言 2（游戏 / 目标语言）",
        "separator_group": "双语分隔符",
        "separator_check": "在语言 1 和语言 2 之间使用自定义分隔符",
        "separator": "分隔符",
        "separator_examples": '示例：" - "   " / "   " | "   " → "',
        "scanning": "可用语言：正在扫描…",
        "default_languages": r"可用语言：默认列表（未找到 content\content0）",
        "none_detected": "未检测到语言文件；使用默认列表",
        "detected": r"content\content0 中检测到：{langs}",
        "ui_group": "双语菜单适配",
        "ui_check": "安装双语菜单适配 MOD",
        "ui_desc": r"内置组件：assets\modDualSubtitlesUI",
        "font_group": "通用字体兼容",
        "font_check": "安装 Universal Font MOD",
        "font_desc": "根据语言 2 自动构建正确的游戏字体槽",
        "apply": "应用",
        "restore": "恢复",
        "clear": "清空日志",
        "ready": "就绪。应用前会自动验证所需组件。",
        "select_game": "选择《巫师 3》游戏目录",
        "success": "完成",
        "success_body": "双语设置已应用。\n处理字符串目录：{count}\n请把游戏文本语言设置为 {lang}。",
        "error": "错误",
        "restore_title": "恢复",
        "restore_changes": "恢复双语修改",
        "restore_desc": "恢复所选语言的原始文件，并将 UI / 字体 MOD 恢复到本工具介入前的状态。",
        "restore_none": "此游戏目录没有记录到可恢复的字符串操作或 UI / 字体组件。",
        "restore_original": "{a} + {b}   → 恢复原始 {b}",
        "restore_button": "恢复所选语言 + UI / 字体",
        "restore_done": "恢复完成",
        "restore_done_body": "已恢复字符串文件：{strings}\n已恢复/移除 UI / 字体 MOD：{mods}",
        "ui_language": "界面语言",
        "cn_label": "cn（简体中文）",
        "zh_label": "zh（繁體中文）",
        "footer": "Dev. Yuxing Łódź",
        "unofficial": "非官方玩家工具 • 未经 CD PROJEKT RED 批准或认可",
    },
    "pl": {
        "ui_name": "Polski",
        "title": "The Witcher 3 Dual Subtitles v1.0.0",
        "game_folder": "Folder gry The Witcher 3",
        "browse": "Przeglądaj…",
        "lang1": "Język 1 (pierwszy)",
        "lang2": "Język 2 (język gry / docelowy)",
        "separator_group": "Separator napisów dwujęzycznych",
        "separator_check": "Użyj własnego separatora między językiem 1 i 2",
        "separator": "Separator",
        "separator_examples": 'Przykłady: " - "   " / "   " | "   " → "',
        "scanning": "Dostępne języki: skanowanie…",
        "default_languages": r"Dostępne języki: lista domyślna (brak content\content0)",
        "none_detected": "Nie wykryto plików językowych; używam listy domyślnej",
        "detected": r"Wykryto w content\content0: {langs}",
        "ui_group": "Dostosowanie menu dwujęzycznego",
        "ui_check": "Zainstaluj MOD dostosowujący menu dwujęzyczne",
        "ui_desc": r"Wbudowany komponent: assets\modDualSubtitlesUI",
        "font_group": "Zgodność czcionki uniwersalnej",
        "font_check": "Zainstaluj Universal Font MOD",
        "font_desc": "Automatycznie buduje właściwy slot czcionki dla języka 2",
        "apply": "Zastosuj",
        "restore": "Przywróć",
        "clear": "Wyczyść log",
        "ready": "Gotowe. Komponenty zostaną sprawdzone przed zastosowaniem zmian.",
        "select_game": "Wybierz folder gry The Witcher 3",
        "success": "Gotowe",
        "success_body": "Konfiguracja dwujęzyczna została zastosowana.\nPrzetworzone foldery: {count}\nUstaw język tekstu gry na {lang}.",
        "error": "Błąd",
        "restore_title": "Przywracanie",
        "restore_changes": "Przywróć zmiany dwujęzyczne",
        "restore_desc": "Przywróć oryginalny plik wybranego języka oraz stan MOD-ów UI/czcionek sprzed użycia narzędzia.",
        "restore_none": "Brak zapisanych operacji lub zarządzanych komponentów UI/czcionek dla tego folderu gry.",
        "restore_original": "{a} + {b}   → przywróć oryginalny {b}",
        "restore_button": "Przywróć wybrane + UI / czcionkę",
        "restore_done": "Przywracanie zakończone",
        "restore_done_body": "Przywrócone pliki językowe: {strings}\nPrzywrócone/usunięte MOD-y UI/czcionek: {mods}",
        "ui_language": "Język interfejsu",
        "cn_label": "cn (chiński uproszczony)",
        "zh_label": "zh (chiński tradycyjny)",
        "footer": "Dev. Yuxing Łódź",
        "unofficial": "Nieoficjalne narzędzie fanowskie • Bez aprobaty ani poparcia CD PROJEKT RED",
    },
}

DARK = {
    "bg": "#15181d",
    "panel": "#1d2229",
    "panel2": "#232a33",
    "entry": "#101318",
    "fg": "#eef2f6",
    "muted": "#9da7b3",
    "accent": "#c9a66b",
    "accent_hover": "#e0bd7d",
    "border": "#343c47",
    "button": "#2a313b",
    "button_hover": "#353e4a",
    "danger": "#d06b6b",
}

class App:
    def __init__(self, root):
        self.root = root
        self.ui_lang = tk.StringVar(value="en")
        self.widgets = {}
        self._configure_theme()

        root.title(f"{APP_NAME} v{APP_VERSION}")
        root.geometry("1000x840")
        root.minsize(900, 680)
        root.configure(bg=DARK["bg"])

        outer = ttk.Frame(root, style="App.TFrame")
        outer.pack(fill="both", expand=True, padx=18, pady=16)

        # Header
        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 12))
        self.widgets["header_title"] = ttk.Label(
            header, text=f"{APP_NAME}  v{APP_VERSION}", style="Title.TLabel"
        )
        self.widgets["header_title"].pack(side="left")

        langbox = ttk.Frame(header, style="App.TFrame")
        langbox.pack(side="right")

        # Small built-in translation icon. Drawn at runtime so the release
        # does not need to ship a third-party icon file.
        self.translate_icon = tk.Canvas(
            langbox, width=29, height=25, bg=DARK["bg"],
            highlightthickness=0, bd=0, cursor="hand2"
        )
        self.translate_icon.pack(side="left", padx=(0, 7))
        self._draw_translate_icon()
        self.translate_icon.bind("<Button-1>", self._cycle_ui_language)

        self.widgets["ui_language"] = ttk.Label(langbox, style="Muted.TLabel")
        self.widgets["ui_language"].pack(side="left", padx=(0, 7))
        self.ui_menu = ttk.Combobox(
            langbox, state="readonly", width=11,
            values=["English", "中文", "Polski"]
        )
        self.ui_menu.current(0)
        self.ui_menu.pack(side="left")
        self.ui_menu.bind("<<ComboboxSelected>>", self._change_ui_language)

        # Game folder card
        game_card = ttk.LabelFrame(outer, style="Card.TLabelframe")
        game_card.pack(fill="x", pady=(0, 10))
        self.widgets["game_card"] = game_card
        row = ttk.Frame(game_card, style="Card.TFrame")
        row.pack(fill="x", padx=12, pady=12)
        self.folder_var = tk.StringVar(value=r"C:\SteamLibrary\steamapps\common\The Witcher 3")
        self.folder_entry = ttk.Entry(row, textvariable=self.folder_var, style="Dark.TEntry")
        self.folder_entry.pack(side="left", fill="x", expand=True)
        self.widgets["browse"] = ttk.Button(row, command=self.browse, style="Secondary.TButton")
        self.widgets["browse"].pack(side="left", padx=(10, 0))

        # Languages
        langrow = ttk.Frame(outer, style="App.TFrame")
        langrow.pack(fill="x", pady=(2, 10))
        self.widgets["lang1"] = ttk.Label(langrow, style="Body.TLabel")
        self.widgets["lang1"].pack(side="left")
        # Keep raw language codes internally. The Comboboxes use localized
        # display labels so CN/ZH are easy for players to identify.
        self.lang1 = tk.StringVar(value="pl")
        self.lang1_menu = ttk.Combobox(
            langrow, values=LANGUAGE_CHOICES,
            state="readonly", width=23
        )
        self.lang1_menu.pack(side="left", padx=(7, 24))
        self.lang1_menu.bind("<<ComboboxSelected>>", self._lang1_selected)

        self.widgets["lang2"] = ttk.Label(langrow, style="Body.TLabel")
        self.widgets["lang2"].pack(side="left")
        self.lang2 = tk.StringVar(value="cn")
        self.lang2_menu = ttk.Combobox(
            langrow, values=LANGUAGE_CHOICES,
            state="readonly", width=23
        )
        self.lang2_menu.pack(side="left", padx=(7, 0))
        self.lang2_menu.bind("<<ComboboxSelected>>", self._lang2_selected)
        self.refresh_language_menus(LANGUAGE_CHOICES)

        # Separator
        self.sepframe = ttk.LabelFrame(outer, style="Card.TLabelframe")
        self.sepframe.pack(fill="x", pady=(0, 10))
        seprow = ttk.Frame(self.sepframe, style="Card.TFrame")
        seprow.pack(fill="x", padx=12, pady=10)
        self.use_separator = tk.BooleanVar(value=False)
        self.widgets["separator_check"] = ttk.Checkbutton(
            seprow, variable=self.use_separator, command=self.update_separator_state,
            style="Dark.TCheckbutton"
        )
        self.widgets["separator_check"].pack(side="left")
        self.widgets["separator"] = ttk.Label(seprow, style="Muted.TLabel")
        self.widgets["separator"].pack(side="left", padx=(18, 6))
        self.separator_var = tk.StringVar(value=" - ")
        self.separator_entry = ttk.Entry(
            seprow, textvariable=self.separator_var, width=14, style="Dark.TEntry"
        )
        self.separator_entry.pack(side="left")
        self.widgets["separator_examples"] = ttk.Label(seprow, style="Muted.TLabel")
        self.widgets["separator_examples"].pack(side="left", padx=(10, 0))

        self.detected_var = tk.StringVar()
        self.detected_label = ttk.Label(
            outer, textvariable=self.detected_var, style="Muted.TLabel"
        )
        self.detected_label.pack(anchor="w", pady=(0, 10))

        # Options cards
        options = ttk.Frame(outer, style="App.TFrame")
        options.pack(fill="x", pady=(0, 10))
        options.columnconfigure(0, weight=1)
        options.columnconfigure(1, weight=1)

        self.uiframe = ttk.LabelFrame(options, style="Card.TLabelframe")
        self.uiframe.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.install_ui = tk.BooleanVar(value=True)
        self.widgets["ui_check"] = ttk.Checkbutton(
            self.uiframe, variable=self.install_ui, style="Dark.TCheckbutton"
        )
        self.widgets["ui_check"].pack(anchor="w", padx=12, pady=(10, 4))
        self.widgets["ui_desc"] = ttk.Label(
            self.uiframe, style="Muted.TLabel", wraplength=410
        )
        self.widgets["ui_desc"].pack(anchor="w", padx=12, pady=(0, 10))

        self.fontframe = ttk.LabelFrame(options, style="Card.TLabelframe")
        self.fontframe.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.update_font = tk.BooleanVar(value=True)
        self.widgets["font_check"] = ttk.Checkbutton(
            self.fontframe, variable=self.update_font, style="Dark.TCheckbutton"
        )
        self.widgets["font_check"].pack(anchor="w", padx=12, pady=(10, 4))
        self.widgets["font_desc"] = ttk.Label(
            self.fontframe, style="Muted.TLabel", wraplength=410
        )
        self.widgets["font_desc"].pack(anchor="w", padx=12, pady=(0, 10))

        # Actions
        actionbar = ttk.Frame(outer, style="App.TFrame")
        actionbar.pack(fill="x", pady=(0, 10))
        self.apply_btn = ttk.Button(actionbar, command=self.apply, style="Accent.TButton")
        self.apply_btn.pack(side="left")
        self.restore_btn = ttk.Button(actionbar, command=self.restore, style="Secondary.TButton")
        self.restore_btn.pack(side="left", padx=(8, 0))
        self.widgets["clear"] = ttk.Button(
            actionbar, command=self.clear_log, style="Secondary.TButton"
        )
        self.widgets["clear"].pack(side="left", padx=(8, 0))

        # Footer is packed BEFORE the expanding log so it always reserves
        # its own height and remains visible even at the normal window size.
        footer = ttk.Frame(outer, style="App.TFrame")
        footer.pack(side="bottom", fill="x", pady=(8, 0))
        self.widgets["unofficial"] = ttk.Label(footer, style="Tiny.TLabel")
        self.widgets["unofficial"].pack(side="left")

        self.github_label = tk.Label(
            footer, text="", bg=DARK["bg"], fg=DARK["accent"],
            activeforeground=DARK["accent_hover"], cursor="hand2",
            font=("Segoe UI", 8, "underline")
        )
        self.github_label.pack(side="right")
        self.github_label.bind("<Button-1>", lambda _e: self.open_github())

        # Log takes only the space left above the reserved footer.
        log_frame = tk.Frame(
            outer, bg=DARK["border"], highlightthickness=0, bd=0
        )
        log_frame.pack(fill="both", expand=True)
        self.log_box = scrolledtext.ScrolledText(
            log_frame, wrap="word", font=("Consolas", 9),
            bg=DARK["entry"], fg="#d7dde5", insertbackground=DARK["fg"],
            selectbackground="#485565", relief="flat", borderwidth=0,
            padx=10, pady=9
        )
        self.log_box.pack(fill="both", expand=True, padx=1, pady=1)

        self.apply_translations()
        self.update_separator_state()
        self.log(self.t("ready"))
        self.root.after(150, self.scan_languages)

    def _configure_theme(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=DARK["bg"], foreground=DARK["fg"], font=("Segoe UI", 9))
        style.configure("App.TFrame", background=DARK["bg"])
        style.configure("Card.TFrame", background=DARK["panel"])
        style.configure("Title.TLabel", background=DARK["bg"], foreground=DARK["fg"], font=("Segoe UI Semibold", 16))
        style.configure("Body.TLabel", background=DARK["bg"], foreground=DARK["fg"])
        style.configure("Muted.TLabel", background=DARK["bg"], foreground=DARK["muted"])
        style.configure("Tiny.TLabel", background=DARK["bg"], foreground=DARK["muted"], font=("Segoe UI", 8))
        style.configure("Card.TLabelframe", background=DARK["panel"], bordercolor=DARK["border"], relief="solid")
        style.configure("Card.TLabelframe.Label", background=DARK["panel"], foreground=DARK["fg"], font=("Segoe UI Semibold", 9))
        style.configure("Dark.TCheckbutton", background=DARK["panel"], foreground=DARK["fg"])
        style.map("Dark.TCheckbutton", background=[("active", DARK["panel"])], foreground=[("disabled", DARK["muted"])])
        style.configure("Dark.TEntry", fieldbackground=DARK["entry"], foreground=DARK["fg"], insertcolor=DARK["fg"], bordercolor=DARK["border"])
        style.configure("TCombobox", fieldbackground=DARK["entry"], background=DARK["button"], foreground=DARK["fg"], arrowcolor=DARK["fg"])
        style.map("TCombobox", fieldbackground=[("readonly", DARK["entry"])], foreground=[("readonly", DARK["fg"])])
        style.configure("Accent.TButton", background=DARK["accent"], foreground="#111317", padding=(18, 8), borderwidth=0, font=("Segoe UI Semibold", 9))
        style.map("Accent.TButton", background=[("active", DARK["accent_hover"]), ("disabled", "#665a46")])
        style.configure("Secondary.TButton", background=DARK["button"], foreground=DARK["fg"], padding=(16, 8), borderwidth=0)
        style.map("Secondary.TButton", background=[("active", DARK["button_hover"]), ("disabled", DARK["panel2"])])

    def t(self, key):
        return UI_TEXT[self.ui_lang.get()].get(key, UI_TEXT["en"].get(key, key))

    def _draw_translate_icon(self):
        """Draw a compact original translation symbol (A / 文 speech cards)."""
        c = self.translate_icon
        c.delete("all")
        # rear card
        c.create_rectangle(10, 3, 27, 18, outline=DARK["muted"], width=1)
        c.create_polygon(20, 18, 24, 22, 24, 18, fill=DARK["bg"], outline=DARK["muted"])
        c.create_text(18.5, 10.5, text="文", fill=DARK["muted"],
                      font=("Microsoft YaHei UI", 8, "bold"))
        # front card
        c.create_rectangle(2, 7, 19, 22, fill=DARK["panel2"],
                           outline=DARK["accent"], width=1)
        c.create_polygon(6, 22, 6, 25, 10, 22,
                         fill=DARK["panel2"], outline=DARK["accent"])
        c.create_text(10.5, 14.5, text="A", fill=DARK["accent"],
                      font=("Segoe UI", 9, "bold"))

    def _cycle_ui_language(self, _event=None):
        order = ["English", "中文", "Polski"]
        current = self.ui_menu.get()
        try:
            index = order.index(current)
        except ValueError:
            index = 0
        self.ui_menu.set(order[(index + 1) % len(order)])
        self._change_ui_language()

    def _change_ui_language(self, _event=None):
        selected = self.ui_menu.get()
        mapping = {"English": "en", "中文": "zh", "Polski": "pl"}
        self.ui_lang.set(mapping.get(selected, "en"))
        self.apply_translations()
        self.scan_languages()

    def apply_translations(self):
        self.root.title(self.t("title"))
        self.widgets["ui_language"].config(text=self.t("ui_language"))
        self.widgets["game_card"].config(text=self.t("game_folder"))
        self.widgets["browse"].config(text=self.t("browse"))
        self.widgets["lang1"].config(text=self.t("lang1") + ":")
        self.widgets["lang2"].config(text="+   " + self.t("lang2") + ":")
        self.sepframe.config(text=self.t("separator_group"))
        self.widgets["separator_check"].config(text=self.t("separator_check"))
        self.widgets["separator"].config(text=self.t("separator") + ":")
        self.widgets["separator_examples"].config(text=self.t("separator_examples"))
        self.uiframe.config(text=self.t("ui_group"))
        self.widgets["ui_check"].config(text=self.t("ui_check"))
        self.widgets["ui_desc"].config(text=self.t("ui_desc"))
        self.fontframe.config(text=self.t("font_group"))
        self.widgets["font_check"].config(text=self.t("font_check"))
        self.widgets["font_desc"].config(text=self.t("font_desc"))
        self.apply_btn.config(text=self.t("apply"))
        self.restore_btn.config(text=self.t("restore"))
        self.widgets["clear"].config(text=self.t("clear"))
        self.widgets["unofficial"].config(text=self.t("unofficial"))
        self.github_label.config(text=self.t("footer"))

    def open_github(self):
        if "YOUR_GITHUB_USERNAME" in GITHUB_URL:
            messagebox.showinfo(
                self.t("title"),
                "Set GITHUB_URL near the top of the source file before publishing."
            )
            return
        webbrowser.open_new_tab(GITHUB_URL)

    def browse(self):
        f = filedialog.askdirectory(title=self.t("select_game"))
        if f:
            self.folder_var.set(f)
            self.scan_languages()

    def update_separator_state(self):
        self.separator_entry.config(state="normal" if self.use_separator.get() else "disabled")

    def language_display(self, code):
        """Localized display text; internal language identifiers remain unchanged."""
        code = (code or "").strip().lower()
        if code == "cn":
            return self.t("cn_label")
        if code == "zh":
            return self.t("zh_label")
        return code

    def language_code_from_display(self, text):
        """Convert a localized Combobox label back to the raw game language code."""
        text = (text or "").strip()
        for code in LANGUAGE_CHOICES:
            if text == self.language_display(code):
                return code
        # Also tolerate a plain code for unknown/dynamically detected languages.
        return text.split(" ", 1)[0].split("（", 1)[0].strip().lower()

    def refresh_language_menus(self, values=None):
        """Refresh localized labels without changing the selected language codes."""
        values = list(values if values is not None else LANGUAGE_CHOICES)
        labels = [self.language_display(code) for code in values]
        self.lang1_menu["values"] = labels
        self.lang2_menu["values"] = labels

        l1 = self.lang1.get()
        l2 = self.lang2.get()
        if l1 not in values and values:
            l1 = values[0]
            self.lang1.set(l1)
        if l2 not in values and values:
            l2 = values[0]
            self.lang2.set(l2)

        self.lang1_menu.set(self.language_display(l1) if l1 else "")
        self.lang2_menu.set(self.language_display(l2) if l2 else "")

    def _lang1_selected(self, _event=None):
        self.lang1.set(self.language_code_from_display(self.lang1_menu.get()))

    def _lang2_selected(self, _event=None):
        self.lang2.set(self.language_code_from_display(self.lang2_menu.get()))

    def scan_languages(self):
        game = Path(self.folder_var.get().strip())
        content0 = game / "content" / "content0"
        if not content0.is_dir():
            self.detected_var.set(self.t("default_languages"))
            self.refresh_language_menus(LANGUAGE_CHOICES)
            return

        found = sorted(
            p.stem.lower() for p in content0.glob("*.w3strings")
            if p.is_file()
            and "_backup" not in p.stem.lower()
            and ".dual_" not in p.stem.lower()
        )
        ordered = [x for x in LANGUAGE_CHOICES if x in found] + [x for x in found if x not in LANGUAGE_CHOICES]
        if not ordered:
            ordered = LANGUAGE_CHOICES[:]
            self.detected_var.set(self.t("none_detected"))
        else:
            self.detected_var.set(self.t("detected").format(langs=", ".join(ordered)))

        old1, old2 = self.lang1.get(), self.lang2.get()
        if old1 in ordered:
            self.lang1.set(old1)
        elif "pl" in ordered:
            self.lang1.set("pl")
        elif ordered:
            self.lang1.set(ordered[0])

        if old2 in ordered:
            self.lang2.set(old2)
        elif "cn" in ordered:
            self.lang2.set("cn")
        elif "zh" in ordered:
            self.lang2.set("zh")
        elif ordered:
            self.lang2.set(ordered[0])

        self.refresh_language_menus(ordered)

    def log(self, text):
        self.log_box.insert("end", str(text) + "\n")
        self.log_box.see("end")
        self.root.update_idletasks()

    def clear_log(self):
        self.log_box.delete("1.0", "end")

    def set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.apply_btn.config(state=state)
        self.restore_btn.config(state=state)
        self.root.update_idletasks()

    def apply(self):
        self.scan_languages()
        folder = self.folder_var.get().strip()
        l1, l2 = self.lang1.get(), self.lang2.get()
        sep = self.separator_var.get()
        self.set_busy(True)
        tx = None
        try:
            self.log("=" * 72)
            self.log(f"Applying bilingual setup: {l1.upper()} + {l2.upper()}")
            self.log(
                f"Custom separator enabled: {sep!r}"
                if self.use_separator.get()
                else "Separator: legacy automatic space/<br> mode"
            )

            validate_bundled_assets(
                self.install_ui.get(), self.update_font.get(), folder, l2
            )

            managed_mods = []
            if self.install_ui.get():
                managed_mods.append("modDualSubtitlesUI")
            if self.update_font.get():
                managed_mods.append("modDualSubtitlesFont")

            tx = ApplyTransaction(folder, l2, managed_mods, self.log)
            tx.begin()

            ok, fail = process_game_folder(
                folder, l1, l2, self.log,
                self.use_separator.get(), sep
            )
            if ok == 0 and not fail:
                raise RuntimeError(
                    f"No folder containing both {l1}.w3strings and {l2}.w3strings was found."
                )
            if fail:
                raise RuntimeError(
                    f"String merge completed with {len(fail)} failure(s)."
                )

            if self.install_ui.get():
                copy_mod_folder(
                    bundled_ui_mod_dir(), folder,
                    "modDualSubtitlesUI", self.log
                )
            else:
                self.log("UI adaptation skipped by user.")

            if self.update_font.get():
                install_dynamic_font_mod(folder, l2, self.log)
            else:
                self.log("Universal Font MOD installation skipped by user.")

            messagebox.showinfo(
                self.t("success"),
                self.t("success_body").format(count=ok, lang=l2.upper())
            )
        except Exception as e:
            if tx is not None:
                try:
                    tx.rollback()
                except Exception as rollback_error:
                    self.log("ROLLBACK ERROR:")
                    self.log(traceback.format_exc())
                    self.log(f"Rollback also failed: {rollback_error}")
            self.log(traceback.format_exc())
            messagebox.showerror(self.t("error"), str(e))
        finally:
            if tx is not None:
                tx.close()
            self.set_busy(False)

    def restore(self):
        folder = self.folder_var.get().strip()
        rows = load_history(folder)
        state = load_component_state(folder)
        has_components = bool(state.get("mods"))

        if not rows and not has_components:
            messagebox.showinfo(self.t("restore_title"), self.t("restore_none"))
            return

        win = tk.Toplevel(self.root)
        win.title(self.t("restore_title"))
        win.geometry("650x390")
        win.configure(bg=DARK["bg"])
        win.transient(self.root)
        win.grab_set()

        frame = ttk.Frame(win, style="App.TFrame")
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        ttk.Label(
            frame, text=self.t("restore_changes"),
            style="Title.TLabel"
        ).pack(anchor="w", pady=(0, 6))
        ttk.Label(
            frame, text=self.t("restore_desc"),
            style="Muted.TLabel", wraplength=610
        ).pack(anchor="w", pady=(0, 10))

        lb = tk.Listbox(
            frame, font=("Consolas", 10),
            bg=DARK["entry"], fg=DARK["fg"],
            selectbackground="#485565", relief="flat",
            highlightbackground=DARK["border"],
            highlightthickness=1
        )
        lb.pack(fill="both", expand=True, pady=(0, 10))
        for l1, l2, bak in rows:
            lb.insert(
                "end",
                self.t("restore_original").format(
                    a=l1.upper(), b=l2.upper()
                )
            )
        if rows:
            lb.selection_set(len(rows) - 1)

        def do_restore():
            sel = lb.curselection()
            selected = rows[sel[0]] if sel else None
            win.destroy()
            self.set_busy(True)
            try:
                restored_strings = 0
                if selected:
                    l1, l2, bak = selected
                    restored_strings = restore_from_record(
                        folder, l2, bak, self.log
                    )

                restored_components = 0
                for mod_name in (
                    "modDualSubtitlesUI",
                    "modDualSubtitlesFont",
                ):
                    if restore_managed_mod(folder, mod_name, self.log):
                        restored_components += 1

                messagebox.showinfo(
                    self.t("restore_done"),
                    self.t("restore_done_body").format(
                        strings=restored_strings,
                        mods=restored_components
                    )
                )
            except Exception as e:
                self.log(traceback.format_exc())
                messagebox.showerror(self.t("error"), str(e))
            finally:
                self.set_busy(False)

        ttk.Button(
            frame, text=self.t("restore_button"),
            command=do_restore, style="Accent.TButton"
        ).pack(anchor="e")


def cli_test(source_path, target_path, output_path):
    source_lang = Path(source_path).stem.split(".")[0].lower()
    target_lang = Path(target_path).stem.split(".")[0].lower()
    stats = merge_files(
        source_path, target_path, output_path,
        source_lang, target_lang, print, False, " - "
    )
    print(stats)



def resource_path(filename):
    """Return a resource path that works in source mode and PyInstaller."""
    if getattr(sys, "frozen", False):
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, filename)


def main():
    # Optional developer test:
    # python Witcher3_Dual_Subtitles.py pl.w3strings zh.w3strings out.w3strings
    if len(sys.argv) == 4:
        cli_test(sys.argv[1], sys.argv[2], sys.argv[3])
        return

    root = tk.Tk()

    # Window/taskbar icon in normal Python execution and packaged builds.
    try:
        root.iconbitmap(resource_path("Witcher3_Dual_Subtitles.ico"))
    except Exception:
        # The icon is cosmetic; never block application startup.
        pass

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
