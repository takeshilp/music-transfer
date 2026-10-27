@echo off
rem Runs the offline tests, then the app with its console, so a crash shows a traceback.
chcp 65001 >nul
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo Не найден %PY%. Создайте окружение: см. docs\development.md
    pause
    exit /b 1
)

echo === Тесты, без сети и без ваших аккаунтов ===
"%PY%" -m pytest -q
rem neq 0, not "errorlevel 1": a Qt crash exits with a negative code (0xC0000409)
if %errorlevel% neq 0 (
    echo.
    echo Тесты не прошли, вывод выше. Программа всё равно запустится.
    pause
)

echo.
echo === Программа: работает с вашими настоящими аккаунтами, токены в "%APPDATA%\music-transfer" ===
echo Не закрывайте это окно, пока работает программа: оно закроет и её. Сюда же попадут ошибки.
"%PY%" main.py
if %errorlevel% neq 0 (
    echo.
    echo Программа завершилась с ошибкой, вывод выше.
    pause
)
