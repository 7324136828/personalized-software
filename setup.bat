@if defined VIRTUAL_ENV goto active
@if defined CONDA_PREFIX goto active
@py -3.14 "%~dp0setup_environment.py" %*
@exit /b %ERRORLEVEL%

:active
@python "%~dp0setup_environment.py" %*
@exit /b %ERRORLEVEL%
