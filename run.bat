@echo off
setlocal enabledelayedexpansion

rem ---------------------------------------------------------------------------
rem  run.bat - build the React viewers and host them with the Python backend.
rem
rem  Usage:
rem    run.bat            Build, then serve the app and live output data
rem    run.bat dev        Start the backend and Vite with hot reload
rem    run.bat build      Build only, no server
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

if /i not "%COMMAND%"=="build" (
    set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"
    set "PYTHON_ARGS="
    if not exist "!PYTHON_EXE!" (
        set "PYTHON_EXE=python"
        where python >nul 2>&1
        if errorlevel 1 (
            where py >nul 2>&1
            if errorlevel 1 (
                echo [run] ERROR: Python was not found on PATH.
                echo [run] Create .venv or install Python 3.11+.
                goto fail
            )
            set "PYTHON_EXE=py"
            set "PYTHON_ARGS=-3"
        )
    )
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

rem -- dev server takes over here ---------------------------------------------

if /i "%COMMAND%"=="dev" (
    echo [run] Starting the backend and dev server on port %PORT% ...
    echo.
    if "%OPEN%"=="1" (
        call "!PYTHON_EXE!" !PYTHON_ARGS! "%ROOT%python_backend\server.py" --dev --frontend-port %PORT% --open
    ) else (
        call "!PYTHON_EXE!" !PYTHON_ARGS! "%ROOT%python_backend\server.py" --dev --frontend-port %PORT%
    )
    goto popdone
)

rem -- build ------------------------------------------------------------------

echo [run] Building for production ...
call npm run build
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

rem -- host -------------------------------------------------------------------

echo [run] Hosting the app and live output data on port %PORT% ...
echo.
echo   Q^&A             http://localhost:%PORT%/#/qanda
echo   All viewers     http://localhost:%PORT%/
echo.
echo [run] Press Ctrl+C to stop the server.
echo.

if "%OPEN%"=="1" (
    call "!PYTHON_EXE!" !PYTHON_ARGS! "%ROOT%python_backend\server.py" --port %PORT% --open
) else (
    call "!PYTHON_EXE!" !PYTHON_ARGS! "%ROOT%python_backend\server.py" --port %PORT%
)
if errorlevel 1 (
    echo [run] ERROR: backend server exited with an error.
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
echo Usage: run.bat [dev^|build^|serve] [--port N] [--no-open]
echo.
echo   (no args)   Build, then host the app and live output data
echo   dev         Run the Python API and Vite with hot reload
echo   build       Build only
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
