# The Witcher 3 Dual Subtitles v1.0.0

A Windows tool for creating bilingual text in **The Witcher 3: Wild Hunt**
using v164 `.w3strings`, with automatic menu adaptation and dynamic Universal
Font support.

> This is an unofficial fan-made tool and is not approved or endorsed by
> CD PROJEKT RED.

## Features

- Scans the installed game languages automatically.
- Combines Language 1 + Language 2 in v164 `.w3strings`.
- Optional custom separator.
- Installs the bilingual menu adaptation MOD.
- Dynamically builds the correct Universal Font resource for the target
  language slot.
- Transaction rollback if Apply fails.
- Persistent Restore for original strings and managed UI/font MODs.
- Application interface in English, 简体中文 and Polski.
- Dark UI.

## Compatibility

- Windows PC.
- The Witcher 3 `.w3strings` **version 164**.
- The release has been designed around the current Next-Gen/Remastered
  resource layout.
- Other game versions are not claimed to be compatible.

## Installation

1. Extract the release to a normal writable folder.
2. Make sure the required release assets listed in `ASSET_MANIFEST.json` are
   present.
3. Run `Witcher3_Dual_Subtitles.py` with Python 3, or the packaged EXE in a
   binary release.
4. Select your The Witcher 3 game folder.

## Usage

1. Choose **Language 1** — shown first.
2. Choose **Language 2** — the game's active/target text language.
3. Optionally enable a custom separator.
4. Keep the menu adaptation and Universal Font options enabled unless you
   intentionally do not need them.
5. Click **Apply**.
6. In the game, set the text language to Language 2.

## Restore

Click **Restore**. The tool can:

- restore the selected target `.w3strings` from the original backup;
- remove MODs installed by the tool if they did not exist before;
- restore pre-existing MOD folders that the tool replaced.

## Backups and state

Inside the selected game folder the tool uses:

- `.witcher3_dual_subtitles_history.txt`
- `.witcher3_dual_subtitles_components.json`
- `.witcher3_dual_subtitles_backups\`

For each processed target language it also creates an original
`<language>_backup_before_dual.w3strings` beside the target file.

Do not delete these while you still want the built-in Restore function.

## Supported language handles

`ar, br, cn, cz, de, en, es, esmx, fr, hu, it, jp, kr, pl, ru, tr, ua, zh`

The Universal Font resource uses dedicated slots for:
`cn, zh, jp, kr, ar, ru, ua, en`.

Other supported Latin-language targets use the game's EN font slot.

## Known limitations

- Only v164 `.w3strings` are supported.
- The dynamic font transplant replaces the first/main `DefineFont3` in the
  target font SWF. The tested bilingual UI path is supported; unusual UI
  elements using another embedded font role may behave differently.
- Game updates can change resource formats or UI files and may require a new
  release.
- Mods can conflict with one another. Apply rollback protects the exact state
  at the start of the operation, but keeping a separate game backup is still
  sensible.
- The tool does not provide support for modified game saves.

## Interface language

Use the **Interface / 界面语言 / Język interfejsu** selector in the upper
right. It can be changed without restarting.

## GitHub link

At the top of `Witcher3_Dual_Subtitles.py`, change:

```python
GITHUB_URL = "https://github.com/YOUR_GITHUB_USERNAME"
```

to your own GitHub profile or repository. The small **Dev. Yuxing Łódź** link in the lower-right corner will open it.

## License and third-party material

The original program code is licensed under the MIT License; see `LICENSE`.
That license does **not** cover The Witcher 3 / REDkit assets, trademarks,
or third-party fonts. Read `THIRD_PARTY_NOTICES.txt` before creating a public
binary package.


### UI note
The translation symbol next to the interface selector is drawn by the program itself; no third-party icon asset is bundled.


### RC5 UI fixes
- The bottom status/credit row now reserves layout space and stays visible at the normal window size.
- On Windows 10/11 the application requests a dark native title bar/window frame to match the dark theme.


### RC6 title-bar fix
The Windows native title bar now uses explicit DWM caption, text and border colors on Windows 11, with immersive-dark-mode fallback for Windows 10. The setting is retried after the Tk window is mapped.


### Native Windows window design
The release uses the normal Windows/Tk title bar and standard window-manager behavior. Custom frameless title bars and DWM color overrides are intentionally not used, prioritizing reliable minimize/maximize/restore/taskbar behavior.


### RC10 application icon
`Witcher3_Dual_Subtitles.ico` is loaded by the Tk window at runtime and is also used by `BUILD_EXE.cmd` as the packaged EXE icon. Install PyInstaller with `py -m pip install pyinstaller`, then run `BUILD_EXE.cmd`.
