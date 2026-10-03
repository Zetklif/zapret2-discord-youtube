# Creates the "zapret" Windows service from a general2*.bat strategy (winws2.exe / zapret2).
#
# Why this exists: service.bat used to split the strategy on '=' ',' ';' and glue the pieces back
# together. That worked for winws.exe options (--opt=value,value) but destroys zapret2 syntax such as
#   --lua-desync=fake:blob=tls_google:repeats=6   ->   --lua-desync fake:blob,tls_google:repeats,6
# winws2.exe then exits at once and the service shows as stopped. Here the command line is taken
# as-is from the .bat, only %VARS% are expanded.
#
# Input comes from environment variables (avoids cmd/PowerShell quoting problems):
#   ZP_STRATEGY  path to the general2*.bat      ZP_BIN / ZP_LUA / ZP_LISTS  folders (with trailing \)
#   GameFilterTCP / GameFilterUDP               set by service.bat
# -DryRun prints the service command line and exits without touching services.
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

function Get-WinwsCommandLine {
    param([string]$Path, [string]$Bin, [string]$Lua, [string]$Lists, [string]$TcpFilter, [string]$UdpFilter, [string]$AnyFilter = '12')

    $text = [IO.File]::ReadAllText($Path)
    $text = [regex]::Replace($text, '\^[ \t]*\r?\n', ' ')            # join "^" line continuations
    $marker = 'winws2.exe"'
    $pos = $text.IndexOf($marker, [StringComparison]::OrdinalIgnoreCase)
    if ($pos -lt 0) { throw "winws2.exe launch line not found in '$Path'. Is this a general2*.bat strategy?" }
    $argLine = ($text.Substring($pos + $marker.Length) -split "\r?\n")[0]

    $map = [ordered]@{
        '%BIN%' = $Bin; '%LUA%' = $Lua; '%LISTS%' = $Lists
        '%GameFilterTCP%' = $TcpFilter; '%GameFilterUDP%' = $UdpFilter
        '%GameFilter%' = $AnyFilter          # older Flowseal releases used a single variable
    }
    foreach ($k in $map.Keys) { $argLine = $argLine.Replace($k, $map[$k]) }
    $argLine = ([regex]::Replace($argLine, '\s+', ' ')).Trim()

    $left = [regex]::Match($argLine, '%[A-Za-z_~][^%\s"]*%')
    if ($left.Success) { throw "Unresolved variable $($left.Value) in '$Path'" }

    return [pscustomobject]@{
        Exe  = (Join-Path $Bin 'winws2.exe')
        Args = $argLine
    }
}

$strategy = $env:ZP_STRATEGY
$bin   = $env:ZP_BIN;   $lua = $env:ZP_LUA;   $lists = $env:ZP_LISTS
$tcp   = if ($env:GameFilterTCP) { $env:GameFilterTCP } else { '12' }
$udp   = if ($env:GameFilterUDP) { $env:GameFilterUDP } else { '12' }
$anyf  = if ($env:GameFilter) { $env:GameFilter } else { '12' }
if (-not $strategy -or -not $bin -or -not $lua -or -not $lists) { throw 'ZP_STRATEGY / ZP_BIN / ZP_LUA / ZP_LISTS are not set' }

$cl = Get-WinwsCommandLine -Path $strategy -Bin $bin -Lua $lua -Lists $lists -TcpFilter $tcp -UdpFilter $udp -AnyFilter $anyf
$binPath = '"' + $cl.Exe + '" ' + $cl.Args

if ($DryRun) { Write-Output $binPath; return }

# Every file named in quotes must exist, otherwise winws2.exe exits immediately.
$missing = foreach ($m in [regex]::Matches($cl.Args, '"([^"]+)"')) { if (-not (Test-Path -LiteralPath $m.Groups[1].Value)) { $m.Groups[1].Value } }
if (-not (Test-Path -LiteralPath $cl.Exe)) { $missing = @($cl.Exe) + @($missing) }
if ($missing) {
    Write-Host '[ERROR] Files required by the strategy are missing:' -ForegroundColor Red
    $missing | Sort-Object -Unique | ForEach-Object { Write-Host "        $_" -ForegroundColor Red }
    exit 2
}

Write-Host "Command line ($($binPath.Length) chars):"
Write-Host $binPath
Write-Host ''

New-Service -Name 'zapret' -BinaryPathName $binPath -DisplayName 'zapret' -StartupType Automatic `
    -Description 'Zapret DPI bypass software' | Out-Null
try {
    Start-Service -Name 'zapret'
} catch {
    Write-Host "[ERROR] Service did not start: $($_.Exception.Message)" -ForegroundColor Red
}

Start-Sleep -Seconds 2
$svc = Get-Service -Name 'zapret' -ErrorAction SilentlyContinue
$proc = Get-Process -Name 'winws2' -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq 'Running' -and $proc) {
    Write-Host 'Service "zapret" is RUNNING, winws2.exe is running.' -ForegroundColor Green
    exit 0
}
Write-Host "[ERROR] Service status: $($svc.Status); winws2.exe running: $([bool]$proc)" -ForegroundColor Red
Write-Host 'To see why, stop here and run in a console (as administrator):' -ForegroundColor Yellow
Write-Host "        $binPath" -ForegroundColor Yellow
exit 1
