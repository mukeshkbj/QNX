# 01-install-wsl.ps1 - run on the Windows PC in PowerShell **as Administrator**.
# Installs WSL2 + Ubuntu 22.04 (a QNX-supported Linux host) and enables nested
# virtualisation so QEMU can use KVM inside WSL2.

$ErrorActionPreference = "Stop"

Write-Host "== Checking this PC can host QNX SDP 8.0 ==" -ForegroundColor Cyan
if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    Write-Host "This PC reports '$($env:PROCESSOR_ARCHITECTURE)'. QNX SDP 8.0 does not support ARM hosts. Stop here." -ForegroundColor Red
    exit 1
}
$build = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber
Write-Host "Windows build $build, x64 CPU - OK"
if ($build -lt 22000) {
    Write-Host "Windows 10 detected: WSL GUI apps (needed for the QNX Software Center window) need Windows 11 or WSLg. You can still continue; see SETUP.md for the command-line install." -ForegroundColor Yellow
}

$virt = (Get-CimInstance Win32_Processor | Select-Object -First 1).VirtualizationFirmwareEnabled
if ($virt -eq $false) {
    Write-Host "CPU virtualisation is OFF in BIOS/UEFI. Turn on Intel VT-x / AMD-V (SVM) and rerun." -ForegroundColor Red
    exit 1
}

Write-Host "== Writing $env:USERPROFILE\.wslconfig (nested virtualisation for KVM) ==" -ForegroundColor Cyan
$cfg = "$env:USERPROFILE\.wslconfig"
if (Test-Path $cfg) { Copy-Item $cfg "$cfg.bak" -Force; Write-Host "Existing .wslconfig backed up to .wslconfig.bak" }
@"
[wsl2]
nestedVirtualization=true
memory=8GB
"@ | Set-Content -Path $cfg -Encoding ascii

Write-Host "== Installing WSL2 + Ubuntu-22.04 ==" -ForegroundColor Cyan
$distros = (wsl --list --quiet 2>$null) -replace "`0", ""
if ($distros -match "Ubuntu-22.04") {
    Write-Host "Ubuntu-22.04 already installed."
    wsl --update
} else {
    wsl --install -d Ubuntu-22.04
}

Write-Host ""
Write-Host "Done. If Windows asks, RESTART the PC." -ForegroundColor Green
Write-Host "Then open 'Ubuntu 22.04' from the Start menu, create your Linux user, and follow step 2 in SETUP.md."
