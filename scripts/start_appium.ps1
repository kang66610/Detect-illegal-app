[CmdletBinding()]
param(
    [int]$Port = 4725
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$statusUrl = "http://127.0.0.1:$Port/status"

try {
    $existing = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $statusUrl
    if ($existing.StatusCode -eq 200) {
        Write-Host "Appium is already ready at $statusUrl"
        exit 0
    }
} catch {
    # The port is not serving Appium yet; start the local server below.
}

$appium = Get-Command appium.cmd -ErrorAction SilentlyContinue |
    Where-Object { $_.Source -and [IO.Path]::GetFileName($_.Source) -match '^appium(?:\.cmd)?$' } |
    Select-Object -First 1
if (-not $appium) {
    $appium = Get-Command appium -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -and [IO.Path]::GetFileName($_.Source) -match '^appium(?:\.cmd)?$' } |
        Select-Object -First 1
}

# Prefer an existing Appium CLI.  A stale/mismatched npx cache can make
# ``npx --no-install appium`` fail with "missing packages" even though a
# previous npx invocation already populated a usable Appium cache.
if (-not $appium) {
    $cacheRoots = @()
    if ($env:npm_config_cache) { $cacheRoots += $env:npm_config_cache }
    if ($env:LOCALAPPDATA) { $cacheRoots += (Join-Path $env:LOCALAPPDATA 'npm-cache') }
    $cachedAppium = @(
        foreach ($cacheRoot in ($cacheRoots | Select-Object -Unique)) {
            $npxRoot = Join-Path $cacheRoot '_npx'
            if (Test-Path $npxRoot) {
                Get-ChildItem -Path (Join-Path $npxRoot '*\node_modules\.bin\appium.cmd') -File -ErrorAction SilentlyContinue
                Get-ChildItem -Path (Join-Path $npxRoot '*\node_modules\.bin\appium') -File -ErrorAction SilentlyContinue
            }
        }
    ) | Sort-Object LastWriteTime -Descending
    if ($cachedAppium.Count -gt 0) { $appium = $cachedAppium[0] }
}

$npx = $null
if (-not $appium) {
    $npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
    if (-not $npx) { $npx = Get-Command npx -ErrorAction SilentlyContinue }
    if (-not $npx) { throw 'Cannot find Appium or npx. Install Node.js and Appium first.' }
}

$sdkRoot = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { $env:ANDROID_HOME }
if ($sdkRoot -and (Test-Path (Join-Path $sdkRoot 'platform-tools'))) {
    $env:Path = "$(Join-Path $sdkRoot 'platform-tools');$env:Path"
}

$logPath = Join-Path $projectRoot "data\logs\appium-$Port.log"
$arguments = @()
if ($appium) {
    $filePath = if ($appium.Source) { $appium.Source } else { $appium.FullName }
    $arguments += 'server'
} else {
    $filePath = $npx.Source
    $arguments += @('--no-install', 'appium', 'server')
}
$arguments += @('--address', '127.0.0.1', '--port', "$Port", '--session-override', '--allow-insecure', '*:session_discovery', '--log', $logPath, '--log-level', 'info')
$launchFile = $filePath
$launchArguments = $arguments
$detached = $false
if ($filePath -match '\.cmd$' -or (Test-Path (Join-Path (Split-Path $filePath -Parent) '..\appium\index.js'))) {
    # Detach the Node process through ``start``.  The Codex/PowerShell host
    # places child processes in a job that is cleaned up when this script
    # exits; a normal Start-Process therefore leaves a server that dies as
    # soon as the startup probe returns.  ``start /b`` creates a sibling
    # process that survives the short-lived launcher while keeping the
    # Appium console hidden.
    $node = Get-Command node.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Source } | Select-Object -First 1
    $entry = Join-Path (Split-Path $filePath -Parent) '..\appium\index.js'
    if ($node -and (Test-Path $entry)) {
        $nodePath = (Resolve-Path $node.Source).Path
        $entryPath = (Resolve-Path $entry).Path
        $formatArgument = {
            param([string]$value)
            if ($value -match '[\s"]') {
                return '"' + ($value -replace '"', '\"') + '"'
            }
            return $value
        }
        $commandLine = 'start "Appium" /b ' + (& $formatArgument $nodePath) + ' ' + (& $formatArgument $entryPath)
        foreach ($argument in $arguments) {
            $commandLine += ' ' + (& $formatArgument ([string]$argument))
        }
        # Do not inherit the launcher's stdout/stderr pipe.  The desktop
        # runner closes that pipe after this script returns; Node would then
        # terminate on its first console write, making the service appear to
        # start successfully for only a few seconds.
        $commandLine += ' >nul 2>&1'
        # Start a short-lived cmd wrapper and let ``start`` create the actual
        # Appium sibling.  Invoking cmd with ``&`` directly can make
        # PowerShell wait on inherited handles even though ``start`` has
        # already returned; Start-Process returns as soon as the wrapper is
        # created and the redirected child remains alive.
        Start-Process -FilePath $env:ComSpec -ArgumentList @('/d', '/c', $commandLine) `
            -WorkingDirectory $projectRoot -WindowStyle Hidden | Out-Null
        $detached = $true
    } else {
        $launchFile = $env:ComSpec
        $quotedArguments = ($arguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
        $launchArguments = '/d /c call "' + $filePath + '" ' + $quotedArguments
    }
}
$process = if ($detached) { $null } else {
    Start-Process -FilePath $launchFile -ArgumentList $launchArguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
}

foreach ($attempt in 1..30) {
    Start-Sleep -Milliseconds 500
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $statusUrl
        if ($response.StatusCode -eq 200) {
            $pidText = if ($process) { "PID $($process.Id)" } else { 'detached process' }
            Write-Host "Appium is ready at $statusUrl ($pidText)"
            exit 0
        }
    } catch {}
}

if (Test-Path $logPath) { Get-Content $logPath -Tail 80 }
throw "Appium did not become ready. See $logPath"
