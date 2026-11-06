# Speaker mode: Bluetooth speaker SoundCore 2 paired with this PC. Wait for her to finish before talking.
. "$PSScriptRoot\common.ps1"
try {
    Stop-VoiceClient
    Start-Backend
    Write-Host ''
    Write-Host 'Make sure SoundCore 2 is on and connected to this PC.'
    Write-Host 'Do not talk to the board at the same time: the TTS serves one conversation at a time.'
    & "$Root\pc-voice-client\start-voice-client.ps1"
} catch { Write-Host "ERROR: $_" -ForegroundColor Red }
Read-Host 'Press Enter to close this window'
