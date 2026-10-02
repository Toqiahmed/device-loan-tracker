@echo off
rem Builds DeviceLoans.exe from app.py. Run this on Windows, in the same folder as app.py.
rem Requires Python 3 (tick "Add python.exe to PATH" when installing it).

py -m pip install --upgrade pip
py -m pip install flask pyinstaller
if errorlevel 1 goto :fail

py -m PyInstaller --onefile --clean --name DeviceLoans app.py
if errorlevel 1 goto :fail

echo.
echo Done! Your program is: dist\DeviceLoans.exe
echo Copy that single file to any Windows PC and double-click it.
pause
exit /b 0

:fail
echo.
echo Something went wrong. Scroll up to read the error.
pause
exit /b 1
