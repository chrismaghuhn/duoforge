# Starts the pinned Showdown server for the live-path arena (python -m duoforge_live.arena, issue #362) on Windows,
# bound to the WSL host address only (the vEthernet (WSL) adapter's IPv4), so the --no-security server takes no guest
# from the LAN. No change to the checkout: without a port argument the server takes its address and port from
# cloud-env (BIND_IP, PORT). The bots in WSL connect with --host <the printed address>.
#
#   powershell -File tools/live/local_server.ps1 -ShowdownDir C:\Dev\src\pokemon-showdown [-Port 8000]
param(
    [Parameter(Mandatory = $true)][string]$ShowdownDir,
    [int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$address = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -like 'vEthernet (WSL*' }).IPAddress
if (-not $address -or @($address).Count -ne 1) {
    throw "no single vEthernet (WSL) IPv4 address: $address"
}
Write-Output "local Showdown server on ${address}:$Port (arena: --host $address --port $Port)"
$env:BIND_IP = $address
$env:PORT = "$Port"
Set-Location $ShowdownDir
node pokemon-showdown start --no-security
