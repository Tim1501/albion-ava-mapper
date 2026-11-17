@echo off
REM Runs Albion Ava Mapper from the source code with your own Python 3.10+ (python.org).
REM Most people should use the ready-made download from the Releases page instead.
cd /d "%~dp0"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt || goto :error
start "" pythonw app\server.py
goto :eof
:error
echo Could not install the requirements. Is Python installed and on PATH?
pause
