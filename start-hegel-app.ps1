$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Hegel Dialogue App - One Click Launcher" -ForegroundColor Cyan
Write-Host "  Conda-aware startup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Set-Location -Path $PSScriptRoot

$script:UseCondaRun = $false
$script:CondaEnvName = ""
$script:FoundCondaPath = $null
$script:PythonExePath = $null  # e.g. project .venv or explicit python.exe

function FailAndExit([string]$message, [string[]]$solutions) {
    Write-Host "[FAILED] $message" -ForegroundColor Red
    if ($solutions -and $solutions.Count -gt 0) {
        Write-Host "How to fix:" -ForegroundColor Yellow
        foreach ($s in $solutions) {
            Write-Host "  - $s" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

function Get-CondaInstallRoot {
    param([string]$LauncherPath)
    if (-not $LauncherPath) { return $null }
    try {
        $full = (Resolve-Path -LiteralPath $LauncherPath -ErrorAction Stop).Path
    } catch { return $null }
    $parentDir = Split-Path -Parent $full
    $leaf = Split-Path -Leaf $parentDir
    if ($leaf -eq "Scripts" -or $leaf -eq "condabin") {
        return (Split-Path -Parent $parentDir)
    }
    return $null
}

function Get-PythonInCondaEnv {
    param([string]$CondaBase, [string]$EnvName)
    if (-not $CondaBase) { return $null }
    if ($EnvName -eq "base") {
        $py = Join-Path $CondaBase "python.exe"
        if (Test-Path -LiteralPath $py) { return $py }
        return $null
    }
    $py = Join-Path $CondaBase "envs\$EnvName\python.exe"
    if (Test-Path -LiteralPath $py) { return $py }
    return $null
}

function Add-CondaLaunchersFromRegistry {
    param([System.Collections.Generic.List[string]]$List)
    foreach ($pattern in @(
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )) {
        try {
            Get-ItemProperty $pattern -ErrorAction SilentlyContinue | Where-Object {
                $_.DisplayName -and $_.DisplayName -match '(?i)Miniconda|Anaconda'
            } | ForEach-Object {
                $loc = $_.InstallLocation
                if (-not $loc) { $loc = $_.InstallDir }
                if (-not $loc) { return }
                $loc = $loc.Trim().TrimEnd('\', '/')
                if ($loc -match '(?i)\\Scripts$') { $loc = Split-Path $loc }
                $bat = Join-Path $loc "condabin\conda.bat"
                $cex = Join-Path $loc "Scripts\conda.exe"
                if (Test-Path -LiteralPath $bat) { $List.Add($bat) }
                elseif (Test-Path -LiteralPath $cex) { $List.Add($cex) }
            }
        } catch {}
    }
}

function Add-CondaFromFixedDrivesShallow {
    param([System.Collections.Generic.List[string]]$List)
    try {
        foreach ($d in [System.IO.DriveInfo]::GetDrives()) {
            if (-not $d.IsReady -or $d.DriveType -ne [System.IO.DriveType]::Fixed) { continue }
            $root = $d.RootDirectory.FullName
            foreach ($d1 in @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue)) {
                foreach ($leaf in @('Miniconda3', 'miniconda3', 'Anaconda3', 'anaconda3')) {
                    $bat = Join-Path $d1.FullName "$leaf\condabin\conda.bat"
                    if (Test-Path -LiteralPath $bat) { $List.Add($bat) }
                }
                foreach ($d2 in @(Get-ChildItem -LiteralPath $d1.FullName -Directory -ErrorAction SilentlyContinue)) {
                    $leaf2 = Split-Path -Leaf $d2.FullName
                    if ($leaf2 -notmatch '^(?i)(miniconda3|anaconda3)$') { continue }
                    $bat = Join-Path $d2.FullName "condabin\conda.bat"
                    if (Test-Path -LiteralPath $bat) { $List.Add($bat) }
                }
            }
        }
    } catch {}
}

function Test-PythonInterpreter {
    param([string]$PythonExe)
    if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) { return $false }
    $restoreHome = $env:PYTHONHOME
    $restorePyPath = $env:PYTHONPATH
    try {
        $env:PYTHONHOME = $null
        $env:PYTHONPATH = $null
        # Do not use "import encodings" as two argv tokens: Windows Start-Process can break -c's body (SyntaxError: import).
        # One-line, no spaces needed: __import__('encodings')
        $p = Start-Process -FilePath $PythonExe -ArgumentList @('-c', '__import__(''encodings'')') -Wait -PassThru -NoNewWindow
        return ($p.ExitCode -eq 0)
    } catch {
        return $false
    } finally {
        $env:PYTHONHOME = $restoreHome
        $env:PYTHONPATH = $restorePyPath
    }
}

function Get-CondaEnvListJson {
    param([string]$CondaBase, [string]$PreferredLauncher)
    $launchers = New-Object System.Collections.Generic.List[string]
    if ($CondaBase) {
        $bat = Join-Path $CondaBase "condabin\conda.bat"
        if (Test-Path -LiteralPath $bat) { $launchers.Add($bat) }
    }
    if ($PreferredLauncher) { $launchers.Add($PreferredLauncher) }

    foreach ($launcher in ($launchers | Select-Object -Unique)) {
        if (-not $launcher -or -not (Test-Path -LiteralPath $launcher)) { continue }
        try {
            if ($launcher -match '\.(bat|cmd)$') {
                $raw = & cmd.exe /c "call `"$launcher`" env list --json 2>nul" 2>$null
            } else {
                $raw = & $launcher env list --json 2>$null
            }
            if (-not $raw) { continue }
            return ($raw | ConvertFrom-Json -ErrorAction Stop)
        } catch { }
    }
    return $null
}

function Invoke-Py {
    param([string[]]$Arguments)
    $restoreHome = $env:PYTHONHOME
    $restorePyPath = $env:PYTHONPATH
    try {
        if ($script:PythonExePath -or $script:UseCondaRun) {
            $env:PYTHONHOME = $null
            $env:PYTHONPATH = $null
        }
        if ($script:PythonExePath) {
            & $script:PythonExePath @Arguments
        } elseif ($script:UseCondaRun -and $script:FoundCondaPath) {
            $launcher = $script:FoundCondaPath
            if ($launcher -match '\.(bat|cmd)$') {
                $condaArgs = @("run", "-n", $script:CondaEnvName, "python") + $Arguments
                $escaped = ($condaArgs | ForEach-Object {
                    $a = "$_"
                    if ($a -match '\s|"') { '"' + ($a.Replace('"', '""')) + '"' } else { $a }
                }) -join ' '
                & cmd.exe /c "call `"$launcher`" $escaped"
            } else {
                & $launcher run -n $script:CondaEnvName python @Arguments
            }
        } else {
            & python @Arguments
        }
    } finally {
        $env:PYTHONHOME = $restoreHome
        $env:PYTHONPATH = $restorePyPath
    }
}

function Resolve-PythonRuntime {
    # 0. Project-local virtualenv (portable with the repo; no conda needed)
    $venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        try {
            $ver = & $venvPy --version 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[INFO] Using project venv: $venvPy ($ver)"
                $script:PythonExePath = $venvPy
                $script:UseCondaRun = $false
                return
            }
        } catch {}
    }

    # 1. If python is already available and works, just use it
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        try {
            $ver = & python --version 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[INFO] Found python: $ver"
                $script:UseCondaRun = $false
                return
            }
        } catch {}
    }

    # 1b. Windows py launcher (Python installed but not necessarily as "python" on PATH)
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $ver = & py -3 --version 2>$null
            if ($LASTEXITCODE -eq 0) {
                $resolved = (& py -3 -c "import sys; print(sys.executable)") 2>$null
                $resolved = if ($resolved) { ($resolved | Out-String).Trim() } else { "" }
                if ($resolved -and (Test-Path -LiteralPath $resolved)) {
                    Write-Host "[INFO] Using Python from py -3: $ver -> $resolved"
                    $script:PythonExePath = $resolved
                    $script:UseCondaRun = $false
                    return
                }
            }
        } catch {}
    }

    # 2. conda on PATH or from installer env vars, then common install locations
    $possibleCondaPaths = New-Object System.Collections.Generic.List[string]
    $hegelCondaRoot = $env:HEGEL_CONDA_ROOT
    if ($hegelCondaRoot -and $hegelCondaRoot.Trim().Length -gt 0) {
        $rr = $hegelCondaRoot.Trim().TrimEnd('\', '/')
        $hbat = Join-Path $rr "condabin\conda.bat"
        $hexe = Join-Path $rr "Scripts\conda.exe"
        if (Test-Path -LiteralPath $hbat) { $possibleCondaPaths.Add($hbat) }
        elseif (Test-Path -LiteralPath $hexe) { $possibleCondaPaths.Add($hexe) }
    }
    foreach ($x in @(
        $env:CONDA_EXE,
        $env:MAMBA_EXE
    )) {
        if ($x -and (Test-Path $x)) { $possibleCondaPaths.Add($x) }
    }
    $condaCmd = Get-Command conda -ErrorAction SilentlyContinue
    if ($condaCmd -and $condaCmd.Source) { $possibleCondaPaths.Add($condaCmd.Source) }

    foreach ($dir in ($env:Path -split ';' | Where-Object { $_ })) {
        foreach ($name in @('conda.exe', 'mamba.exe')) {
            $cand = Join-Path $dir $name
            if (Test-Path $cand) { $possibleCondaPaths.Add($cand) }
        }
        try {
            $fullDir = (Resolve-Path -LiteralPath $dir.Trim() -ErrorAction Stop).Path
        } catch { continue }
        $leaf = Split-Path -Leaf $fullDir
        if ($leaf -ne "Scripts" -and $leaf -ne "condabin") { continue }
        $condaRootFromPath = Split-Path -Parent $fullDir
        $rootLeaf = Split-Path -Leaf $condaRootFromPath
        if ($rootLeaf -notmatch '^(?i)(miniconda3|anaconda3)$') { continue }
        $fromPathBat = Join-Path $condaRootFromPath "condabin\conda.bat"
        $fromPathExe = Join-Path $condaRootFromPath "Scripts\conda.exe"
        if (Test-Path -LiteralPath $fromPathBat) { $possibleCondaPaths.Add($fromPathBat) }
        elseif (Test-Path -LiteralPath $fromPathExe) { $possibleCondaPaths.Add($fromPathExe) }
    }

    Add-CondaLaunchersFromRegistry -List $possibleCondaPaths
    Add-CondaFromFixedDrivesShallow -List $possibleCondaPaths

    # Prefer condabin\conda.bat first: Scripts\conda.exe often depends on conda-script.py and breaks on partial installs.
    $suffixes = @(
        @("miniconda3", "condabin\conda.bat"),
        @("miniconda3", "Scripts\conda.exe"),
        @("anaconda3", "condabin\conda.bat"),
        @("anaconda3", "Scripts\conda.exe"),
        @("Miniconda3", "condabin\conda.bat"),
        @("Miniconda3", "Scripts\conda.exe"),
        @("Anaconda3", "condabin\conda.bat"),
        @("Anaconda3", "Scripts\conda.exe")
    )
    $rootsUser = @($env:UserProfile, $env:LOCALAPPDATA) | Where-Object { $_ }
    $rootsMachine = @("C:\ProgramData", $env:ProgramData) | Where-Object { $_ }
    foreach ($root in ($rootsUser | Select-Object -Unique)) {
        foreach ($pair in $suffixes) {
            $possibleCondaPaths.Add((Join-Path $root ($pair[0] + "\" + $pair[1])))
        }
    }
    foreach ($root in ($rootsMachine | Select-Object -Unique)) {
        foreach ($pair in $suffixes) {
            $possibleCondaPaths.Add((Join-Path $root ($pair[0] + "\" + $pair[1])))
        }
    }
    $condaBasesOrdered = New-Object System.Collections.Generic.List[string]
    $seenLaunchers = @{}
    foreach ($p in $possibleCondaPaths) {
        if (-not $p -or -not (Test-Path -LiteralPath $p)) { continue }
        try {
            $normL = (Resolve-Path -LiteralPath $p).Path
        } catch { continue }
        if ($seenLaunchers.ContainsKey($normL)) { continue }
        $seenLaunchers[$normL] = $true
        $b = Get-CondaInstallRoot -LauncherPath $p
        if (-not $b) { continue }
        try {
            $normB = (Resolve-Path -LiteralPath $b).Path
        } catch { continue }
        $already = $false
        foreach ($existing in $condaBasesOrdered) {
            if ($existing -eq $normB) { $already = $true; break }
        }
        if ($already) { continue }
        $condaBasesOrdered.Add($normB)
    }

    $deprioritize = New-Object System.Collections.Generic.List[string]
    $prefer = New-Object System.Collections.Generic.List[string]
    foreach ($cb in $condaBasesOrdered) {
        if ($cb -match '(?i)\\ProgramData\\miniconda3$') { $deprioritize.Add($cb) }
        else { $prefer.Add($cb) }
    }
    $merged = New-Object System.Collections.Generic.List[string]
    foreach ($x in $prefer) { $merged.Add($x) }
    foreach ($x in $deprioritize) { $merged.Add($x) }
    $condaBasesOrdered = $merged

    # 3. Try each Conda root (ProgramData ghost/broken installs are skipped after stdlib check).
    if ($condaBasesOrdered.Count -gt 0) {
        Write-Host "[INFO] Conda install roots to try: $($condaBasesOrdered -join ' | ')"

        $preferred = $env:HEGEL_CONDA_ENV
        if (-not $preferred -or $preferred.Trim() -eq "") {
            $preferred = "hegel"
        }

        foreach ($condaBase in $condaBasesOrdered) {
            try {
                $foundConda = $null
                $bat = Join-Path $condaBase "condabin\conda.bat"
                $cex = Join-Path $condaBase "Scripts\conda.exe"
                if (Test-Path -LiteralPath $bat) {
                    $foundConda = $bat
                } elseif (Test-Path -LiteralPath $cex) {
                    $foundConda = $cex
                } else {
                    Write-Host "[WARN] No conda.bat or conda.exe under $condaBase ; skipping."
                    continue
                }

                $envToUse = $preferred
                $envList = Get-CondaEnvListJson -CondaBase $condaBase -PreferredLauncher $foundConda

                if ($envList -and $envList.envs) {
                    $availableEnvs = @($envList.envs | ForEach-Object { ($_ -split "[\\/]" | Select-Object -Last 1) })
                    if ($availableEnvs -contains $preferred) {
                        $envToUse = $preferred
                    } elseif ($availableEnvs -contains "base") {
                        $envToUse = "base"
                    } else {
                        Write-Host "[WARN] No '$preferred' or base in $condaBase ; skipping. Available: $($availableEnvs -join ', ')"
                        continue
                    }
                } else {
                    Write-Host "[WARN] Could not list conda envs for $condaBase ; checking env folders on disk..."
                    if (Test-Path -LiteralPath (Join-Path $condaBase "envs\$preferred\python.exe")) {
                        $envToUse = $preferred
                    } elseif (Test-Path -LiteralPath (Join-Path $condaBase "python.exe")) {
                        $envToUse = "base"
                    } else {
                        $envsDir = Join-Path $condaBase "envs"
                        if (Test-Path -LiteralPath $envsDir) {
                            $first = Get-ChildItem -LiteralPath $envsDir -Directory -ErrorAction SilentlyContinue |
                                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "python.exe") } |
                                Select-Object -First 1
                            if ($first) {
                                $envToUse = $first.Name
                                Write-Host "[INFO] Using conda env (from disk): $envToUse"
                            }
                        }
                    }
                }

                $directPy = Get-PythonInCondaEnv -CondaBase $condaBase -EnvName $envToUse
                if (-not $directPy -and $envToUse -ne "base") {
                    $directPy = Get-PythonInCondaEnv -CondaBase $condaBase -EnvName "base"
                    if ($directPy) {
                        $envToUse = "base"
                        Write-Host "[INFO] Env '$preferred' not found under $condaBase ; falling back to base."
                    }
                }

                if (-not $directPy) {
                    Write-Host "[WARN] No python.exe for env '$envToUse' under $condaBase ; trying next root."
                    continue
                }

                if (-not (Test-PythonInterpreter -PythonExe $directPy)) {
                    Write-Host "[WARN] Python at $directPy failed stdlib check (broken prefix, missing encodings, or bad %PYTHONHOME%). Skipping this install."
                    continue
                }

                $ver = & $directPy --version 2>$null
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "[WARN] Could not run --version on $directPy ; trying next root."
                    continue
                }

                Write-Host "[INFO] Using conda env Python directly: $directPy ($ver)"
                $script:PythonExePath = $directPy
                $script:UseCondaRun = $false
                $script:FoundCondaPath = $null
                $script:CondaEnvName = $envToUse
                return
            } catch {
                Write-Host "[WARN] Skipped conda root $condaBase : $($_.Exception.Message)"
                continue
            }
        }

        FailAndExit "Found Conda folder(s) but none had a working Python (or env '$preferred' is missing)." @(
            "Set HEGEL_CONDA_ROOT to your good Miniconda path (e.g. E:\Project Tools\Miniconda3)",
            "Uninstall or fix the broken install under C:\ProgramData\miniconda3 if you do not use it",
            "Create env: conda create -n hegel python=3.12 -y",
            "Or: python -m venv .venv  then install requirements there"
        )
    }

    # 4. Last resort: fail with helpful message
    FailAndExit "Python not found." @(
        "Install Miniconda from https://docs.conda.io/en/latest/miniconda.html",
        "Or ensure python is in your system PATH",
        "Run this script from an Anaconda/Miniconda prompt if installed"
    )
}

function Ensure-Requirements {
    if (-not (Test-Path "requirements.txt")) {
        FailAndExit "requirements.txt not found." @(
            "Make sure launcher is in project root",
            "Restore requirements.txt"
        )
    }

    Invoke-Py -Arguments @("-c", "import importlib.util,sys;mods=['streamlit','requests'];missing=[m for m in mods if importlib.util.find_spec(m) is None];sys.exit(1 if missing else 0)")
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[INFO] Dependencies already satisfied."
        return
    }

    Write-Host "[INFO] Missing dependencies detected, installing..."
    Invoke-Py -Arguments @("-m", "pip", "install", "-r", "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        FailAndExit "Dependency installation failed." @(
            "Check network access",
            "Try: conda activate hegel",
            "Then run: python -m pip install -r requirements.txt"
        )
    }
}

function Get-PortPids([int]$Port) {
    $out = @()
    $lines = netstat -ano | Select-String (":" + $Port)
    foreach ($line in $lines) {
        $parts = ($line.ToString().Trim() -split "\s+")
        if ($parts.Length -ge 5) {
            $pidStr = $parts[-1]
            if ($pidStr -match "^\d+$") { $out += [int]$pidStr }
        }
    }
    return ($out | Select-Object -Unique)
}

function Is-PortBusy([int]$Port) {
    $pids = Get-PortPids -Port $Port
    return ($pids.Count -gt 0)
}

function Stop-OldStreamlitOnPort([int]$Port) {
    $stopped = 0
    $pids = Get-PortPids -Port $Port
    foreach ($procId in $pids) {
        try {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId"
            $cmd = [string]$proc.CommandLine
            $name = [string]$proc.Name
            # 只清理与本项目相关的 python/streamlit 进程，避免误杀其他服务
            if (
                ($name -match "(?i)python(\.exe)?|streamlit(\.exe)?") -and
                ($cmd -match "(?i)streamlit") -and
                ($cmd -match "(?i)app_streamlit\.py|hegel-logic")
            ) {
                Write-Host "[INFO] Stopping old Streamlit PID: $procId"
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                $stopped += 1
            }
        } catch {}
    }
    return $stopped
}

function Find-FreePort([int]$StartPort, [int]$MaxTries = 20) {
    for ($i = 0; $i -lt $MaxTries; $i++) {
        $p = $StartPort + $i
        if (-not (Is-PortBusy -Port $p)) { return $p }
    }
    return -1
}

try {
    Write-Host "[1/5] Resolving python runtime..." -ForegroundColor Green
    Resolve-PythonRuntime

    Write-Host ""
    Write-Host "[2/5] Checking python and pip..." -ForegroundColor Green
    Invoke-Py -Arguments @("--version")
    if ($LASTEXITCODE -ne 0) {
        FailAndExit "Python runtime is not available." @(
            "If using conda: conda activate hegel",
            "Verify: python --version",
            "Then rerun launcher"
        )
    }
    Invoke-Py -Arguments @("-m", "pip", "--version")
    if ($LASTEXITCODE -ne 0) {
        FailAndExit "pip not available in selected runtime." @(
            "Run: python -m ensurepip --upgrade",
            "Or recreate conda env with pip",
            "Then rerun launcher"
        )
    }

    Write-Host ""
    Write-Host "[3/5] Checking/installing requirements..." -ForegroundColor Green
    Ensure-Requirements

    Write-Host ""
    Write-Host "[4/5] Checking port 8501..." -ForegroundColor Green
    $targetPort = 8501
    if (Is-PortBusy -Port $targetPort) {
        Write-Host "[NOTICE] Port 8501 is in use. Trying to restart old app..."
        $stopped = Stop-OldStreamlitOnPort -Port $targetPort
        if ($stopped -gt 0) {
            Start-Sleep -Seconds 1
        }
        if (Is-PortBusy -Port $targetPort) {
            $freePort = Find-FreePort -StartPort 8502 -MaxTries 30
            if ($freePort -lt 0) {
                FailAndExit "Port 8501 is busy and no free fallback port found." @(
                    "Close old app windows and retry",
                    "Or manually pick a free port: python -m streamlit run app_streamlit.py --server.port <PORT>"
                )
            }
            $targetPort = $freePort
            Write-Host "[NOTICE] Port 8501 still busy. Switching to port $targetPort."
        }
    }

    if (-not (Test-Path "app_streamlit.py")) {
        FailAndExit "app_streamlit.py not found." @(
            "Make sure you run this from project root",
            "Restore app_streamlit.py"
        )
    }

    Write-Host ""
    Write-Host "[5/5] Launch succeeded. Opening browser..." -ForegroundColor Green
    Write-Host "URL: http://localhost:$targetPort"
    Write-Host "Keep this window open while using the app."
    Start-Process ("http://localhost:" + $targetPort) | Out-Null

    Invoke-Py -Arguments @("-m", "streamlit", "run", "app_streamlit.py", "--server.headless", "true", "--server.port", "$targetPort")
    if ($LASTEXITCODE -ne 0) {
        FailAndExit "Streamlit failed to start." @(
            "Check selected conda env has streamlit installed",
            "Check port availability",
            "Manual run: python -m streamlit run app_streamlit.py --server.port <PORT>"
        )
    }
}
catch {
    FailAndExit ("Unhandled error: " + $_.Exception.Message) @(
        "Copy this message and share it",
        "Verify conda env and Python dependencies"
    )
}
