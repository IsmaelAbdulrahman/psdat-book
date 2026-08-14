param([string]$Dest)
$w = New-Object -ComObject WScript.Shell
$desk = [Environment]::GetFolderPath('Desktop')
$d = $w.CreateShortcut((Join-Path $desk 'PSDAT.lnk'))
$d.TargetPath = "$Dest\PSDAT.exe"; $d.WorkingDirectory = $Dest
$d.IconLocation = "$Dest\PSDAT.ico"
$d.Description = 'Power System Dynamic Analysis Toolbox'
$d.Save()
$sm = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\PSDAT'
New-Item -ItemType Directory -Force -Path $sm | Out-Null
$s = $w.CreateShortcut((Join-Path $sm 'PSDAT.lnk'))
$s.TargetPath = "$Dest\PSDAT.exe"; $s.WorkingDirectory = $Dest
$s.IconLocation = "$Dest\PSDAT.ico"; $s.Save()
$m = $w.CreateShortcut((Join-Path $sm 'PSDAT Manual.lnk'))
$m.TargetPath = "$Dest\PSDAT_Manual.pdf"; $m.Save()
$u = $w.CreateShortcut((Join-Path $sm 'Uninstall PSDAT.lnk'))
$u.TargetPath = "$Dest\uninstall.cmd"; $u.Save()
