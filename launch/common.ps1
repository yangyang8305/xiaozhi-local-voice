# Shared by the launchers: start the backend if it is not running yet.
$Root = 'C:\AI\ESP32'
$FirmwareIp = '192.168.151.230'  # hard-coded in the board's firmware OTA address

function Test-Port([int]$Port) {
    try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', $Port); $c.Close(); return $true } catch { return $false }
}

function Start-Backend {
    if (-not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -eq $FirmwareIp)) {
        Write-Warning "This PC's IP is no longer $FirmwareIp. The board will not connect: see README, 'PC IP changed'."
    }
    if (Test-Port 8003) { Write-Host 'Backend already running.'; return }
    Write-Host 'Starting LM Studio model, TTS and server in a new window (about 1 minute)...'
    Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', "$Root\xiaozhi-server\start-server.ps1"
    for ($i = 0; $i -lt 150 -and -not (Test-Port 8003); $i++) { Start-Sleep -Seconds 2 }
    if (-not (Test-Port 8003)) { throw 'Backend did not start. Check the backend window for errors.' }
    Write-Host 'Backend ready.'
}

function Stop-VoiceClient {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ExecutablePath -match 'envs\\xiaozhi-server\\' -and $_.CommandLine -match 'client\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}
