@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Tnoat Tum Cafe - Safe Setup or Pull
set "EXPECTED_REMOTE=https://github.com/bunthorngnop/Tnoatum.git"
set "EXPECTED_BRANCH=main"

where git >nul 2>&1 || goto :no_git
where py >nul 2>&1 || goto :no_python
py -3 --version >nul 2>&1 || goto :no_python
git rev-parse --is-inside-work-tree >nul 2>&1 || goto :clone_first
git remote get-url origin >nul 2>&1 || goto :no_remote
for /f "delims=" %%R in ('git remote get-url origin') do set "ACTUAL_REMOTE=%%R"
if /i not "%ACTUAL_REMOTE%"=="%EXPECTED_REMOTE%" goto :wrong_remote
for /f %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /i not "%BRANCH%"=="%EXPECTED_BRANCH%" goto :wrong_branch

git diff --quiet || goto :dirty
git diff --cached --quiet || goto :dirty
git pull --ff-only || goto :error

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv || goto :error
call ".venv\Scripts\activate.bat" || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt || goto :error
if not exist "data" mkdir "data"
if not exist "backups" mkdir "backups"
if not exist "logs" mkdir "logs"
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo ACTION REQUIRED: Edit .env and add locally required Telegram IDs/token.
)
python -m alembic upgrade head || goto :error
python -m pytest || goto :error
python -m tnoat_tum_cafe.cli health || goto :error
echo SUCCESS: Source and dependencies are current; existing runtime DB was not overwritten.
goto :pause_success

:clone_first
echo ERROR: Run: git clone %EXPECTED_REMOTE% "Tnoat-Tum-Cafe"
echo Then see NEW_PC_SETUP.md.
goto :pause_error
:no_remote
echo ERROR: No origin remote is configured. Expected %EXPECTED_REMOTE%.
goto :pause_error
:wrong_remote
echo ERROR: origin does not match %EXPECTED_REMOTE%.
goto :pause_error
:wrong_branch
echo ERROR: Expected branch %EXPECTED_BRANCH%, found %BRANCH%.
goto :pause_error
:dirty
echo ERROR: Local source changes exist. Commit or review them before pulling.
goto :pause_error
:no_git
echo ERROR: Install Git for Windows, then retry.
goto :pause_error
:no_python
echo ERROR: Install 64-bit Python 3.11 or newer with the py launcher, then retry.
goto :pause_error
:error
echo ERROR: Setup/update stopped. No force reset was used and runtime DB was not replaced.
:pause_error
pause
exit /b 1
:pause_success
pause
exit /b 0
