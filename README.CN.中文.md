# The Witcher 3 Dual Subtitles

**The Witcher 3 Dual Subtitles** 是一款非官方 Windows 工具，用于在
**《巫师 3：狂猎》（The Witcher 3: Wild Hunt）** 中创建双语文本。

它可以将游戏中已安装的两种语言合并为 v164 `.w3strings`，安装双语菜单适配
MOD，并根据所选择的目标语言动态准备兼容的 Universal Font 资源。

> 这是一个非官方的玩家自制项目，与 CD PROJEKT RED
> 无隶属关系，也未获得其批准或认可。

## 面向玩家

### 功能

-   将 **语言 1 + 语言 2** 合并为游戏中的双语文本。
-   语言 1 显示在前，语言 2 作为游戏当前使用的目标文本语言。
-   自动扫描 `content\content0` 中已经安装的游戏语言。
-   直接支持游戏的 v164 `.w3strings` 格式。
-   可选择在两种语言之间使用自定义分隔符。
-   启用后自动安装双语菜单适配 MOD。
-   根据语言 2 动态构建对应的 Universal Font 资源。
-   在修改受管理的游戏文件前自动创建备份。
-   如果 Apply 安装过程失败，会回滚本次操作。
-   提供 **Restore** 功能，用于恢复由本工具管理的字符串和 MOD 组件。
-   软件界面支持 English、简体中文和 Polski。

### 兼容性

当前版本面向：

-   Windows PC
-   《The Witcher 3: Wild Hunt》Next-Gen / Remastered 资源结构
-   `.w3strings` **version 164**

目前不声明兼容其他游戏版本或资源版本。

### 玩家安装方法

对于已经打包好的二进制发行版：

1.  下载 `Witcher3_Dual_Subtitles.exe`。
2.  将它放在一个普通的、具有写入权限的文件夹中。
3.  运行 EXE。
4.  选择你的 **The Witcher 3** 游戏安装目录。

打包后的 OneFile 版本已经将程序所需资源包含在 EXE
内部，并会在运行时临时解压。使用打包后的 EXE **不需要安装 Python**。

由于这是社区制作且未进行代码签名的可执行文件，Windows
或杀毒软件可能显示额外的安全警告。如果你对此有顾虑，也可以检查源代码并自行构建程序。

### 使用方法

1.  选择 **The Witcher 3 game folder**。
2.  选择 **Language 1 (first)** ------ 这种语言会显示在合并文本的前面。
3.  选择 **Language 2 (game / target)** ------
    这是游戏实际应使用的文本语言。
4.  如有需要，启用自定义双语分隔符。
5.  如果需要适配后的双语 UI，请保持 **Install bilingual menu adaptation
    MOD** 开启。
6.  当所选语言组合需要多语言字体资源时，请保持 **Install Universal Font
    MOD** 开启。
7.  点击 **Apply**。
8.  启动游戏，并将游戏文本语言设置为 **Language 2**。

默认语言组合为 **PL + CN**。

### Restore（恢复）

点击 **Restore** 可以撤销由本工具管理的修改。

根据实际进行过的修改，Restore 可以：

-   从原始备份恢复目标 `.w3strings`；
-   删除由本工具创建的 UI / Font MOD 文件夹；
-   恢复 Apply 过程中被替换的、原本已经存在的受管理 MOD 文件夹。

### 备份与状态文件

工具会在所选择的游戏目录中保存恢复所需的信息：

``` text
.witcher3_dual_subtitles_history.txt
.witcher3_dual_subtitles_components.json
.witcher3_dual_subtitles_backups\
```

对于每一种处理过的目标语言，还会在对应游戏 `.w3strings` 文件旁创建：

``` text
<language>_backup_before_dual.w3strings
```

**如果你仍然希望使用内置 Restore 功能，请不要删除这些文件。**

### 支持的语言代码

``` text
ar, br, cn, cz, de, en, es, esmx, fr, hu, it, jp, kr, pl, ru, tr, ua, zh
```

Universal Font 使用独立字体槽位的语言为：

``` text
cn, zh, jp, kr, ar, ru, ua, en
```

其他受支持的拉丁字母语言目标使用游戏的 EN 字体槽位。

## 面向开发者

本项目提供源代码，供希望检查实现方式、自行构建工具、研究双语
`.w3strings` 工作流程，或将其中部分实现用于相关 Modding
工具的开发者参考。

### 主要实现内容

项目的核心实现包括：
- 直接读取和写入 The Witcher 3 使用的 v164 .w3strings，在保留字符串 ID / Key 的情况下将两种游戏语言合并为双语文本；
- 自动检测玩家已经安装的游戏语言，并根据所选择的 Language 1 / Language 2 生成对应的双语 .w3strings；
- 内置预制的 Bilingual Menu Adaptation MOD，针对游戏菜单和 UI 在显示双语文本时可能出现的布局、裁切和字体显示问题进行适配；
- 实现 Universal Font 动态适配机制，使同一套通用字形资源能够根据玩家选择的目标语言自动适配游戏对应的字体槽位；
- 从经过验证的 Universal Font 资源中提取主要 DefineFont3，并将其移植到目标语言原始字体 SWF 模板中，同时保留目标字体的 Font ID / Font Name 等必要结构；
- 根据目标语言自动处理 fonts_cn、fonts_zh、fonts_jp、fonts_kr、fonts_ar、fonts_ru、fonts_ua、fonts_en 等字体资源槽位，并为其他受支持的拉丁字母语言使用 EN 字体槽位；
- 自动修改字体资源路径及对应 metadata，使动态生成的字体资源能够作为 modDualSubtitlesFont 被游戏正确加载；
- 将双语字符串、菜单适配和字体适配整合为一次 Apply 操作，无需玩家手动编辑 .w3strings、SWF 或游戏资源；
- 在修改前保存原始状态，并提供事务式失败回滚和持久化 Restore，以恢复原始字符串以及被工具管理的 UI / Font MOD。

### 源码目录结构

开发环境中的项目结构大致如下：

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

`build\`、`dist\`、`__pycache__\` 以及本地 PyInstaller `.spec`
等构建输出文件无需提交到仓库。

### 从源码运行

需要 Python 3。

``` cmd
py Witcher3_Dual_Subtitles.py
```

从源码运行时，程序要求 `assets\` 下存在所需的本地资源。

所需资源目录结构请参阅 `ASSET_MANIFEST.json`。

### 构建单个 EXE

安装 PyInstaller：

``` cmd
py -m pip install pyinstaller
```

然后运行 `BUILD_EXE.cmd`，或者手动执行：

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

生成的程序位于：

``` text
dist\Witcher3_Dual_Subtitles.exe
```

在 PyInstaller 冻结后的版本中，打包进去的只读资源通过 `sys._MEIPASS`
读取。用户数据、游戏数据以及 Restore 状态不应写入临时 bundle 目录。

### 关于资源与再分发的重要说明

本仓库中的 MIT License 适用于该许可证所覆盖的原创项目代码和文档。

它**不授予**以下内容的再分发权：

-   The Witcher 3 游戏文件或游戏资源；
-   REDkit / CD PROJEKT RED 的素材或商标；
-   第三方字体；
-   其他第三方受版权保护的资源。

开发者在制作自己的构建版本时，有责任确认自己添加或分发的任何本地资源具有合法的再分发权限。

更多信息请参阅 `THIRD_PARTY_NOTICES.txt` 和 `ASSET_MANIFEST.json`。

## 已知限制

-   仅支持 v164 `.w3strings`。
-   动态字体移植会替换目标字体 SWF 中第一个/主要的 `DefineFont3`。
-   某些使用其他嵌入字体角色的特殊 UI 元素可能会有不同表现。
-   游戏更新可能改变资源格式或 UI 文件，从而需要发布新的工具版本。
-   其他 MOD 可能与本工具管理的字符串、UI 或字体资源发生冲突。
-   Apply
    回滚会恢复到当前操作开始时记录的状态，但仍建议保留独立的游戏备份。
-   本项目不会修改游戏存档，也不提供游戏存档相关支持。

## 贡献与问题反馈

欢迎提交 Bug 报告以及可复现的兼容性测试结果。

报告问题时，以下信息会很有帮助：

-   游戏版本；
-   Language 1 和 Language 2；
-   是否启用了 UI MOD 和 Universal Font MOD；
-   完整的错误信息或程序日志；
-   问题发生在 Apply、游戏内，还是 Restore 阶段。

除非你拥有相应的再分发权，否则请不要在公开 Issue
中上传受版权保护的游戏资源或字体文件。

## License

本仓库所覆盖的原创项目代码和文档以 **MIT License** 发布。请参阅
`LICENSE`。

第三方材料仍受其各自权利所有者及相应许可证约束。请参阅
`THIRD_PARTY_NOTICES.txt`。