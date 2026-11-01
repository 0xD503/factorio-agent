@echo off
rem factorio-agent CLI launcher for Windows (cmd and PowerShell). Needs Python 3.10+.
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%~dp0fx.py" %*
) else (
  python "%~dp0fx.py" %*
)
exit /b %ERRORLEVEL%
