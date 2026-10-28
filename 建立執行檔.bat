@echo off
setlocal
cd /d "%~dp0"

if not exist "conductivity_gui.py" goto missing
if not exist "conductivity_gui_v2.py" goto missing

echo [1/3] Preparing Python environment...
py -3.12 -m venv ".conductivity-build"
if errorlevel 1 goto failed

echo [2/3] Installing build dependencies...
".conductivity-build\Scripts\python.exe" -m pip install numpy==2.2.6 matplotlib==3.10.3 PyInstaller==6.14.2
if errorlevel 1 goto failed

echo [3/3] Building Windows executable...
".conductivity-build\Scripts\python.exe" -m PyInstaller ^
 --noconfirm ^
 --clean ^
 --onefile ^
 --windowed ^
 --name ConductivityCalculator ^
 --add-data "conductivity_gui.py;." ^
 --hidden-import conductivity_gui ^
 conductivity_gui_v2.py
if errorlevel 1 goto failed

echo.
echo Build completed: dist\ConductivityCalculator.exe
start "" "%~dp0dist\ConductivityCalculator.exe"
pause
exit /b 0

:missing
echo Please put both Python files in the same folder as this BAT file.
pause
exit /b 1

:failed
echo Build failed. Please capture the error message above.
pause
exit /b 1