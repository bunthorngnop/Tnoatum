@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Tnoat Tum Cafe - Safe GitHub Source Push
set "EXPECTED_REMOTE=https://github.com/bunthorngnop/Tnoatum.git"
set "EXPECTED_BRANCH=main"

where git >nul 2>&1 || goto :no_git
git rev-parse --is-inside-work-tree >nul 2>&1 || goto :no_repo
git remote get-url origin >nul 2>&1 || goto :no_remote
for /f "delims=" %%R in ('git remote get-url origin') do set "ACTUAL_REMOTE=%%R"
if /i not "%ACTUAL_REMOTE%"=="%EXPECTED_REMOTE%" (
  echo ERROR: origin does not match %EXPECTED_REMOTE%.
  goto :pause_error
)

echo Checking remote state...
git fetch origin || goto :error
for /f %%B in ('git branch --show-current') do set "BRANCH=%%B"
if not defined BRANCH (
  echo ERROR: Detached HEAD is not safe for this workflow.
  goto :pause_error
)
if /i not "%BRANCH%"=="%EXPECTED_BRANCH%" (
  echo ERROR: Expected branch %EXPECTED_BRANCH%, found %BRANCH%.
  goto :pause_error
)
git show-ref --verify --quiet "refs/remotes/origin/%BRANCH%"
if not errorlevel 1 for /f %%A in ('git rev-list --count HEAD..origin/%BRANCH%') do set "BEHIND=%%A"
if defined BEHIND if not "%BEHIND%"=="0" (
  echo ERROR: Remote work exists. Run SETUP_OR_PULL_FROM_GITHUB.bat first.
  goto :pause_error
)

git add -A || goto :error
git diff --cached --name-only | findstr /i /r "^\.env$ \.sqlite$ \.sqlite3$ \.db$ ^data/ ^backups/ \.log$ credentials secrets" >nul
if not errorlevel 1 (
  echo ERROR: A sensitive or runtime path is staged. Review .gitignore and the index.
  goto :pause_error
)
git diff --cached --quiet && (
  echo SUCCESS: Nothing to commit.
  goto :pause_success
)

for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "STAMP=%%T"
git commit -m "Cafe source update %STAMP%" || goto :error
git push -u origin HEAD || goto :error
echo SUCCESS: Source pushed safely. Runtime financial data remains separate.
goto :pause_success

:no_git
echo ERROR: Git is not installed or not on PATH.
goto :pause_error
:no_repo
echo ERROR: This folder is not a Git repository.
goto :pause_error
:no_remote
echo ERROR: No origin remote is configured. Expected %EXPECTED_REMOTE%.
goto :pause_error
:error
echo ERROR: Git operation failed. Nothing was force-pushed or reset.
:pause_error
pause
exit /b 1
:pause_success
pause
exit /b 0
