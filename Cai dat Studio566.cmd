@echo off
rem Bam dup de cai dat Studio566. Can mang Internet, lan dau mat vai phut.
chcp 65001 >nul
title Cai dat Studio566
cd /d "%~dp0"
if not exist "%~dp0setup.ps1" (
  echo Hay giai nen file zip ra mot thu muc truoc ^(chuot phai vao file zip, chon Extract All^),
  echo roi bam dup "Cai dat Studio566.cmd" trong thu muc vua giai nen.
  if not defined ICONTENT_NO_PAUSE pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set RC=%errorlevel%
echo.
if not "%RC%"=="0" echo Cai dat chua xong. Hay doc thong bao o tren, hoac chup man hinh nay gui cho tac gia.
if not defined ICONTENT_NO_PAUSE pause
exit /b %RC%
