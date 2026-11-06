# Stops the voice client, TTS and server, and unloads the LLM to free the GPU.
# Matches only this project's Python environments, so other programs named app.py are left alone.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ExecutablePath -match 'envs\\(xiaozhi-server|qwen3-tts)\\' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'start-server\.ps1' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
lms unload --all
Write-Host 'Stopped. GPU memory released.'
Start-Sleep -Seconds 2
