# Install Python 3.15 for the current user (no admin rights). Called by Setup.bat when no Python 3.11+ is found.
# 1. winget (built into Windows 10/11), 2. else the newest 3.15.x installer from python.org, checked to be signed by
# the Python Software Foundation before it runs. Exit code 0 = Python 3.15 is installed for this user.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'                 # the progress bar makes downloads very slow in PowerShell 5
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$target = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python315\python.exe'
if (Test-Path $target) { exit 0 }

if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host 'Installing Python 3.15 with winget / Dang cai Python 3.15 bang winget...'
    try {
        winget install -e --id Python.Python.3.15 --scope user --silent --disable-interactivity `
            --accept-package-agreements --accept-source-agreements | Out-Host
    } catch { }
    if (Test-Path $target) { exit 0 }
}

try {
    $index = (Invoke-WebRequest 'https://www.python.org/ftp/python/' -UseBasicParsing).Content
} catch {
    Write-Host '[ERROR] Cannot reach python.org (internet / proxy?) / Khong ket noi duoc python.org'
    exit 1
}
$versions = [regex]::Matches($index, 'href="(3\.15\.\d+)/"') | ForEach-Object { [version]$_.Groups[1].Value } |
    Sort-Object -Descending
foreach ($v in $versions) {                               # newest release that has a 64-bit Windows installer
    $url = "https://www.python.org/ftp/python/$v/python-$v-amd64.exe"
    try { Invoke-WebRequest $url -Method Head -UseBasicParsing | Out-Null } catch { continue }
    $exe = Join-Path $env:TEMP "python-$v-amd64.exe"
    Write-Host "Downloading Python $v / Dang tai Python $v..."
    Invoke-WebRequest $url -OutFile $exe -UseBasicParsing
    $sig = Get-AuthenticodeSignature $exe
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        Remove-Item $exe -ErrorAction SilentlyContinue
        Write-Host '[ERROR] The downloaded installer is not signed by the Python Software Foundation - not run.'
        exit 1
    }
    Write-Host "Installing Python $v for this user / Dang cai Python $v (1-2 minutes)..."
    Start-Process $exe -Wait -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1',
        'InstallLauncherAllUsers=0', 'Include_test=0', 'Shortcuts=0'
    Remove-Item $exe -ErrorAction SilentlyContinue
    if (Test-Path $target) { exit 0 }
    Write-Host '[ERROR] The Python installer did not finish / Cai Python khong thanh cong.'
    exit 1
}
Write-Host '[ERROR] No Python 3.15 installer found on python.org.'
exit 1
