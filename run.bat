@echo off
setlocal enabledelayedexpansion

rem ---------------------------------------------------------------------------
rem  run.bat - build the React viewers, sync generated content, and host them.
rem
rem  Usage:
rem    run.bat            Sync, build, then serve and open the infographics
rem    run.bat dev        Sync, then start the dev server with hot reload
rem    run.bat build      Sync and build only, no server
rem    run.bat sync       Copy ../output into react/public/data only
rem    run.bat help       Show this message
rem
rem  Options (before or after the command):
rem    --port N           Port to serve on (default 4173 serve, 5174 dev)
rem    --no-open          Do not launch a browser
rem ---------------------------------------------------------------------------

set "ROOT=%~dp0"
set "APP=%ROOT%react"
set "COMMAND=serve"
set "PORT="
set "OPEN=1"

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="dev"       set "COMMAND=dev"      & shift & goto parse
if /i "%~1"=="build"     set "COMMAND=build"    & shift & goto parse
if /i "%~1"=="sync"      set "COMMAND=sync"     & shift & goto parse
if /i "%~1"=="serve"     set "COMMAND=serve"    & shift & goto parse
if /i "%~1"=="help"      goto usage
if /i "%~1"=="--help"    goto usage
if /i "%~1"=="-h"        goto usage
if /i "%~1"=="--no-open" set "OPEN=0"           & shift & goto parse
if /i "%~1"=="--port"    set "PORT=%~2"         & shift & shift & goto parse
echo [run] Unknown argument: %~1
goto badusage
:parsed

if not defined PORT (
    if "%COMMAND%"=="dev" (set "PORT=5174") else (set "PORT=4173")
)

echo.
echo ===========================================================
echo  Learning Content Viewers
echo  command : %COMMAND%
echo  app     : %APP%
echo ===========================================================
echo.

rem -- prerequisites ----------------------------------------------------------

where node >nul 2>&1
if errorlevel 1 (
    echo [run] ERROR: Node.js was not found on PATH.
    echo [run] Install it from https://nodejs.org and reopen this window.
    goto fail
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [run] ERROR: npm was not found on PATH.
    goto fail
)

for /f "delims=" %%v in ('node --version') do set "NODEVER=%%v"
echo [run] Node %NODEVER%

if not exist "%APP%\package.json" (
    echo [run] ERROR: No React project at "%APP%".
    goto fail
)
if not exist "%ROOT%output" (
    echo [run] ERROR: No "output" folder at "%ROOT%output".
    echo [run] Generate content first, e.g.:
    echo [run]   python python\ollama_learning\infographic.py --help
    goto fail
)

pushd "%APP%" || goto fail

rem -- dependencies -----------------------------------------------------------

if not exist "node_modules" (
    echo [run] Installing dependencies ^(first run^)...
    call npm install
    if errorlevel 1 (
        echo [run] ERROR: npm install failed.
        goto popfail
    )
    echo [run] Dependencies installed.
    echo.
)

rem -- step 1: sync -----------------------------------------------------------

echo [run] Step 1/3  Syncing generated content into public\data ...
call npm run sync
if errorlevel 1 (
    echo [run] ERROR: sync failed.
    goto popfail
)
echo.

if /i "%COMMAND%"=="sync" (
    echo [run] Sync complete.
    goto popdone
)

rem -- dev server takes over here ---------------------------------------------

if /i "%COMMAND%"=="dev" (
    echo [run] Starting the dev server on port %PORT% ...
    if "%OPEN%"=="1" start "" "http://localhost:%PORT%/#/infographics"
    echo [run] Press Ctrl+C to stop.
    echo.
    call npm run dev -- --port %PORT%
    goto popdone
)

rem -- step 2: build ----------------------------------------------------------

rem build:only skips the prebuild sync hook, since step 1 already synced.
echo [run] Step 2/3  Building for production ...
call npm run build:only
if errorlevel 1 (
    echo [run] ERROR: build failed.
    goto popfail
)
echo.

if not exist "dist\index.html" (
    echo [run] ERROR: build produced no dist\index.html.
    goto popfail
)

if /i "%COMMAND%"=="build" (
    echo [run] Build complete. Output in "%APP%\dist".
    goto popdone
)

rem -- step 3: host -----------------------------------------------------------

echo [run] Step 3/3  Hosting on port %PORT% ...
echo.
echo   Infographics    http://localhost:%PORT%/#/infographics
echo   All viewers     http://localhost:%PORT%/
echo.
echo   Standalone exports served from the same origin:
for %%F in ("dist\data\infographics\*.html") do (
    echo     http://localhost:%PORT%/data/infographics/%%~nxF
)
for %%F in ("dist\data\infographics\*.svg") do (
    echo     http://localhost:%PORT%/data/infographics/%%~nxF
)
echo.
echo [run] Press Ctrl+C to stop the server.
echo.

if "%OPEN%"=="1" start "" "http://localhost:%PORT%/#/infographics"
call npm run preview -- --port %PORT% --strictPort
if errorlevel 1 (
    echo [run] ERROR: preview server exited with an error.
    echo [run] If the port is in use, retry with:  run.bat --port 4174
    goto popfail
)

:popdone
popd
echo.
echo [run] Done.
endlocal
exit /b 0

:usage
call :printusage
endlocal
exit /b 0

:badusage
call :printusage
endlocal
exit /b 1

:printusage
echo.
echo Usage: run.bat [dev^|build^|sync^|serve] [--port N] [--no-open]
echo.
echo   (no args)   Sync, build, then host and open the infographics
echo   dev         Sync, then run the dev server with hot reload
echo   build       Sync and build only
echo   sync        Copy output\ into react\public\data only
echo.
echo   --port N    Port to serve on (default 4173 serve, 5174 dev)
echo   --no-open   Do not launch a browser
echo.
goto :eof

:popfail
popd
:fail
echo.
echo [run] Failed.
endlocal
exit /b 1
