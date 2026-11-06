# Runs the PC voice client on the Bluetooth speaker. Start ..\xiaozhi-server\start-server.ps1 first.
# Wake words: 你好小智 / 小智小智. Stop with Ctrl+C. Use --list to see sound device names.
$serverEnv = 'C:\Users\yangy\miniconda3\envs\xiaozhi-server'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PATH = "$serverEnv;$serverEnv\Library\bin;$env:PATH"
Set-Location $PSScriptRoot
& "$serverEnv\python.exe" client.py @args
