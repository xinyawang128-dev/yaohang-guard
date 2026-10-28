@echo off
if defined YAO_PYTHON exit /b 0
if exist "%LocalAppData%\Programs\Python\Python314\python.exe" set "YAO_PYTHON=%LocalAppData%\Programs\Python\Python314\python.exe"
if defined YAO_PYTHON exit /b 0
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "YAO_PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
if defined YAO_PYTHON exit /b 0
for /f "delims=" %%P in ('where python 2^>nul') do if not defined YAO_PYTHON set "YAO_PYTHON=%%P"
if defined YAO_PYTHON exit /b 0
where py >nul 2>nul
if not errorlevel 1 set "YAO_PYTHON=py"
if defined YAO_PYTHON exit /b 0
echo Python 3.10+ was not found. Install Python or set YAO_PYTHON to python.exe.
exit /b 1
