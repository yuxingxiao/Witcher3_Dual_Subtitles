@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo  The Witcher 3 Dual Subtitles v1.0.0
echo  Building OneFile EXE...
echo ==========================================
echo.

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

echo.
echo ==========================================
echo  Build finished
echo ==========================================
echo.
echo Output:
echo dist\Witcher3_Dual_Subtitles.exe
echo.
pause