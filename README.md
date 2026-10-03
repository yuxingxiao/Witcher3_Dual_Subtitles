# The Witcher 3 Dual Subtitles

**The Witcher 3 Dual Subtitles** is an unofficial Windows tool for
creating bilingual text in **The Witcher 3: Wild Hunt**.

It combines two installed game languages into v164 `.w3strings`, can
install a bilingual menu adaptation, and dynamically prepares the
compatible Universal Font resource required by the selected target
language.

> This is an unofficial fan-made project and is not approved, affiliated
> with, or endorsed by CD PROJEKT RED.

## For players

### What it does

-   Combines **Language 1 + Language 2** into bilingual game text.
-   Keeps Language 1 first and Language 2 as the game's active/target
    text language.
-   Automatically scans languages installed in `content\content0`.
-   Supports the game's v164 `.w3strings` format directly.
-   Provides an optional custom separator between the two languages.
-   Installs the bilingual menu adaptation MOD when enabled.
-   Dynamically builds the appropriate Universal Font resource for
    Language 2.
-   Creates backups before modifying managed game files.
-   Rolls back the current Apply operation if installation fails.
-   Provides a **Restore** function for reverting managed strings and
    MOD components.
-   Includes English, Simplified Chinese, and Polish application
    interfaces.

### Compatibility

The current release is intended for:

-   Windows PC
-   The Witcher 3: Wild Hunt Next-Gen / Remastered resource layout
-   `.w3strings` **version 164**

Other game/resource versions are not claimed to be compatible.

### Installation for players

For a binary release:

1.  Download `Witcher3_Dual_Subtitles.exe`.
2.  Put it in a normal writable folder.
3.  Run the EXE.
4.  Select your **The Witcher 3** installation folder.

The packaged OneFile build contains its application resources internally
and extracts them temporarily at runtime. Python is not required for the
packaged EXE.

Windows or antivirus software may show additional warnings for an
unsigned community-built executable. If you prefer, you can inspect the
source and build the program yourself.

### Usage

1.  Select the **The Witcher 3 game folder**.
2.  Choose **Language 1 (first)** --- this language appears first in the
    combined text.
3.  Choose **Language 2 (game / target)** --- this is the text language
    the game should use.
4.  Optionally enable a custom bilingual separator.
5.  Leave **Install bilingual menu adaptation MOD** enabled if you want
    the adapted bilingual UI.
6.  Leave **Install Universal Font MOD** enabled when the selected
    language combination requires the multilingual font resource.
7.  Click **Apply**.
8.  Start the game and set its text language to **Language 2**.

The default selection is **PL + CN**.

### Restore

Click **Restore** to revert changes managed by the tool.

Depending on what was changed, Restore can:

-   restore the target `.w3strings` from its original backup;
-   remove UI/font MOD folders created by the tool;
-   restore pre-existing managed MOD folders that were replaced during
    Apply.

### Backups and state

The tool stores restoration information in the selected game folder:

``` text
.witcher3_dual_subtitles_history.txt
.witcher3_dual_subtitles_components.json
.witcher3_dual_subtitles_backups\
```

For each processed target language, it also creates:

``` text
<language>_backup_before_dual.w3strings
```

beside the corresponding game `.w3strings`.

**Do not delete these files while you still want the built-in Restore
function to work.**

### Supported language handles

``` text
ar, br, cn, cz, de, en, es, esmx, fr, hu, it, jp, kr, pl, ru, tr, ua, zh
```

Dedicated Universal Font slots are used for:

``` text
cn, zh, jp, kr, ar, ru, ua, en
```

Other supported Latin-language targets use the game's EN font slot.


## For developers

The source is provided for developers who want to inspect the
implementation, build the tool themselves, study the bilingual
`.w3strings` workflow, or adapt parts of the project for related modding
tools.

### Main implementation areas

The project includes code for:

-   reading and writing v164 `.w3strings`;
-   merging two languages while preserving Witcher string IDs/keys;
-   automatic language discovery;
-   transactional Apply and rollback;
-   persistent Restore state;
-   installation/restoration of managed MOD directories;
-   SWF parsing and recompression;
-   extracting and transplanting the main `DefineFont3`;
-   patching the target font resource path;
-   patching matching metadata paths;
-   dynamically creating `modDualSubtitlesFont`;
-   Tkinter desktop UI and localization;
-   PyInstaller OneFile resource handling through `sys._MEIPASS`.

### Source layout

A development checkout is expected to look broadly like:

``` text
Witcher3_Dual_Subtitles\
├─ Witcher3_Dual_Subtitles.py
├─ Witcher3_Dual_Subtitles.ico
├─ BUILD_EXE.cmd
├─ README.md
├─ LICENSE
├─ THIRD_PARTY_NOTICES.txt
├─ ASSET_MANIFEST.json
└─ assets\
   ├─ modDualSubtitlesUI\
   ├─ modDualSubtitlesFontBase\
   └─ font_templates\
```

Build output such as `build\`, `dist\`, `__pycache__\`, and local
PyInstaller `.spec` files does not need to be committed.

### Running from source

Python 3 is required.

``` cmd
py Witcher3_Dual_Subtitles.py
```

The source build expects the required local assets to exist under
`assets\`.

See `ASSET_MANIFEST.json` for the expected resource layout.

### Building a single EXE

Install PyInstaller:

``` cmd
py -m pip install pyinstaller
```

Then use `BUILD_EXE.cmd`, or build manually:

``` cmd
py -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "Witcher3_Dual_Subtitles" ^
  --icon "Witcher3_Dual_Subtitles.ico" ^
  --add-data "Witcher3_Dual_Subtitles.ico;." ^
  --add-data "assets;assets" ^
  "Witcher3_Dual_Subtitles.py"
```

The resulting application is:

``` text
dist\Witcher3_Dual_Subtitles.exe
```

In a frozen PyInstaller build, bundled read-only resources are loaded
from `sys._MEIPASS`. User/game data and restoration state are not
intended to be written into the temporary bundle directory.

### Important asset and redistribution note

The MIT license in this repository applies to the original project code
and documentation covered by that license.

It does **not** grant redistribution rights for:

-   The Witcher 3 game files or resources;
-   REDkit/CD PROJEKT RED material or trademarks;
-   third-party fonts;
-   other third-party copyrighted assets.

Developers creating their own builds are responsible for ensuring that
any local assets they add or distribute may legally be redistributed.

See `THIRD_PARTY_NOTICES.txt` and `ASSET_MANIFEST.json` for additional
information.

## Known limitations

-   Only v164 `.w3strings` are supported.
-   The dynamic font transplant replaces the first/main `DefineFont3` in
    the target font SWF.
-   Unusual UI elements using a different embedded font role may behave
    differently.
-   Game updates may change resource formats or UI files and require a
    new tool release.
-   Other mods can conflict with managed strings, UI, or font resources.
-   Apply rollback restores the state captured at the beginning of the
    current operation, but keeping an independent game backup is still
    recommended.
-   The project does not modify or provide support for game saves.

## Contributing

Bug reports and reproducible compatibility findings are welcome.

When reporting a problem, useful information includes:

-   game version;
-   Language 1 and Language 2;
-   whether the UI MOD and Universal Font MOD were enabled;
-   the exact error message or application log;
-   whether the problem occurs during Apply, in-game, or during Restore.

Please avoid uploading copyrighted game/font resources in public issues
unless you have the right to redistribute them.

## License

Original project code and documentation covered by this repository are
released under the **MIT License**. See `LICENSE`.

Third-party materials remain subject to their respective owners and
licenses. See `THIRD_PARTY_NOTICES.txt`.
