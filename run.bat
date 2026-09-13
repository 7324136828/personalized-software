@if defined VIRTUAL_ENV goto active
@if defined CONDA_PREFIX goto active
@if not exist "%~dp0.venv\Scripts\python.exe" call "%~dp0setup.bat"
@if errorlevel 1 exit /b %ERRORLEVEL%
@"%~dp0.venv\Scripts\python.exe" "%~dp0run_app.py" %*
@exit /b %ERRORLEVEL%

:active
@python "%~dp0run_app.py" %*
@exit /b %ERRORLEVEL%
