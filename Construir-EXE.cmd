@echo off
cd /d "%~dp0"
"C:\Users\lukas\AppData\Local\Programs\Python\Python312\python.exe" -m PyInstaller --noconfirm --clean EditorConquistando.spec
pause
