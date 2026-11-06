# Headset mode: USB-C headset on the board's OTG port. You can interrupt her by talking.
. "$PSScriptRoot\common.ps1"
try {
    Stop-VoiceClient
    Start-Backend
    Write-Host ''
    Write-Host 'Ready. Wake word: Hi ESP (the board restarts its connection automatically).'
    Write-Host 'Keep the backend window open. Use the Stop shortcut when finished.'
} catch { Write-Host "ERROR: $_" -ForegroundColor Red }
Read-Host 'Press Enter to close this window'
