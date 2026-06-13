@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0start.py"
    goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0start.py"
    goto :done
)

echo [错误] 未找到 Python。请先安装 Python 3.10+ 并勾选 "Add to PATH"。
echo 下载: https://www.python.org/downloads/
pause
exit /b 1

:done
if errorlevel 1 pause
