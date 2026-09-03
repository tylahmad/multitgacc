@echo off
chcp 65001 >nul
title ahmadtgmulti.py - tgmultipanel ^| مدير جلسات Telethon
setlocal EnableExtensions

REM ============================================================
REM  tgmultipanel - تشغيل الواجهة الرسومية على Windows
REM  1) ينشئ بيئة افتراضية (venv) عند أول تشغيل
REM  2) يثبّت المتطلبات من requirements.txt
REM  3) يشغّل gui.py
REM ============================================================

cd /d "%~dp0"

REM --- التأكد من وجود Python ---
set "PY_CMD="
where py >nul 2>nul && set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>nul && set "PY_CMD=python"
)
if not defined PY_CMD (
    echo.
    echo [خطأ] لم يتم العثور على Python 3 على هذا الجهاز.
    echo        حمّله من https://www.python.org/downloads/windows/
    echo        وفعّل خيار "Add python.exe to PATH" أثناء التثبيت.
    echo.
    pause
    exit /b 1
)

REM --- إنشاء البيئة الافتراضية عند أول تشغيل ---
if not exist "venv\Scripts\python.exe" (
    echo [1/3] إنشاء البيئة الافتراضية venv ...
    %PY_CMD% -m venv venv
    if errorlevel 1 (
        echo [خطأ] فشل إنشاء البيئة الافتراضية.
        pause
        exit /b 1
    )
)

set "VENV_PY=venv\Scripts\python.exe"

REM --- تثبيت / تحديث المتطلبات (يتم تخطيها إذا لم يتغير requirements.txt) ---
set "NEED_INSTALL=1"
if exist "venv\.requirements.stamp" (
    fc /b requirements.txt "venv\.requirements.stamp" >nul 2>nul && set "NEED_INSTALL=0"
)
if "%NEED_INSTALL%"=="1" (
    echo [2/3] تثبيت المتطلبات ^(telethon, PyQt5 ...^) - قد يستغرق دقيقة عند أول مرة ...
    "%VENV_PY%" -m pip install --upgrade pip >nul 2>nul
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [خطأ] فشل تثبيت المتطلبات. تأكد من اتصال الإنترنت ثم أعد المحاولة.
        pause
        exit /b 1
    )
    copy /y requirements.txt "venv\.requirements.stamp" >nul
) else (
    echo [2/3] المتطلبات مثبتة مسبقاً.
)

REM --- المجلدات اللازمة ---
if not exist "sessions" mkdir "sessions"
if not exist "logs" mkdir "logs"
if not exist "data" mkdir "data"

REM --- تشغيل الواجهة ---
echo [3/3] تشغيل الواجهة ...
"%VENV_PY%" gui.py
if errorlevel 1 (
    echo.
    echo [تنبيه] أُغلقت الواجهة بخطأ. راجع الملف logs\gui.log لمزيد من التفاصيل.
    pause
)
endlocal
