# Starts LM Studio's API + model (if needed), the local TTS service and the xiaozhi server.
# Logs go to the console. Stop with Ctrl+C.
$serverEnv = 'C:\Users\yangy\miniconda3\envs\xiaozhi-server'
$ttsEnv    = 'C:\Users\yangy\miniconda3\envs\qwen3-tts'
$model     = 'qwen3.8-27b-humanlike-chat'

lms server start
if (-not ((lms ps) -match 'local-brain')) {
    lms load $model --gpu max --context-length 8192 --parallel 1 --identifier local-brain -y
}

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:HF_HUB_OFFLINE = '1'
$env:PATH = "C:\FFMpeg;$serverEnv;$serverEnv\Library\bin;$env:PATH"

$tts = Start-Process -FilePath "$ttsEnv\python.exe" -ArgumentList 'C:\AI\ESP32\qwen-tts-service\service.py' -NoNewWindow -PassThru
try {
    while (-not (Test-NetConnection 127.0.0.1 -Port 8765 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
        if ($tts.HasExited) { throw 'TTS service failed to start' }
        Start-Sleep -Seconds 2
    }
    Set-Location "$PSScriptRoot\main\xiaozhi-server"
    & "$serverEnv\python.exe" app.py
} finally {
    if (-not $tts.HasExited) { Stop-Process -Id $tts.Id -Force }
}
