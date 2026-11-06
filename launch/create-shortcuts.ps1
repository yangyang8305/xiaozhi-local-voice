# Creates the desktop shortcuts. Run again if they are ever deleted.
$items = @(
    @{ Name = '小智-耳机模式'; File = 'start-headset.ps1' },
    @{ Name = '小智-音箱模式'; File = 'start-speaker.ps1' },
    @{ Name = '小智-全部停止'; File = 'stop-all.ps1' }
)
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
foreach ($item in $items) {
    $link = $shell.CreateShortcut((Join-Path $desktop "$($item.Name).lnk"))
    $link.TargetPath = 'powershell.exe'
    $link.Arguments = "-ExecutionPolicy Bypass -File `"$PSScriptRoot\$($item.File)`""
    $link.WorkingDirectory = $PSScriptRoot
    $link.Save()
    Write-Host "Created $($item.Name)"
}
