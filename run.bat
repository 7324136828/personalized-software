@if exist "%~dp0.venv\Scripts\python.exe" (
  @"%~dp0.venv\Scripts\python.exe" "%~dp0run_app.py" %*
) else (
  @python "%~dp0run_app.py" %*
)
