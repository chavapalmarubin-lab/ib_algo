@echo off
REM TH IB-Algo Lab - self-logging VPS setup. Output saved to Desktop and opened in Notepad.
set "LOG=%USERPROFILE%\Desktop\th_lab_setup_log.txt"
echo TH LAB SETUP %date% %time% > "%LOG%"
cd /d "%TEMP%"
echo. >> "%LOG%"
echo [1/5] Python check/install ... >> "%LOG%"
where python >nul 2>nul
if errorlevel 1 (
  curl -L -o py.exe https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe
  start /wait "" py.exe /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1
)
set "PY=python"
where python >nul 2>nul || set "PY=%ProgramFiles%\Python312\python.exe"
"%PY%" --version >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo [2/5] Downloading the lab (public zip) ... >> "%LOG%"
curl -L -o lab.zip https://github.com/chavapalmarubin-lab/ib_algo/archive/refs/heads/main.zip >> "%LOG%" 2>&1
rmdir /s /q C:\ib_algo 2>nul
rmdir /s /q lab_x 2>nul & mkdir lab_x & tar -xf lab.zip -C lab_x >> "%LOG%" 2>&1
for /d %%D in (lab_x\*) do move "%%D" C:\ib_algo >> "%LOG%" 2>&1
echo   lab -> C:\ib_algo >> "%LOG%"
echo. >> "%LOG%"
echo [3/5] Installing deps (numpy, ib_insync) ... >> "%LOG%"
"%PY%" -m pip install --upgrade pip numpy ib_insync >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo [4/5] Fetching multi-asset universe from local TWS (port 7497) ... >> "%LOG%"
cd /d C:\ib_algo
"%PY%" agents\multi_asset_lab.py --fetch >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo [5/5] Scheduling daily research run ... >> "%LOG%"
schtasks /create /tn "TH-MultiAsset-Lab" /tr "cmd /c cd /d C:\ib_algo && python agents\multi_asset_lab.py --fetch >> C:\ib_algo\lab_daily.log 2>&1" /sc daily /st 08:30 /f >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo ===== DONE.  If step 4 shows a connection error, enable TWS API (port 7497) and re-run. ===== >> "%LOG%"
start notepad "%LOG%"
