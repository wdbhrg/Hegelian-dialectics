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

function Invoke-Py {
    param([string[]]$Arguments)
    if ($script:UseCondaRun -and $script:FoundCondaPath) {
        & $script:FoundCondaPath run -n $script:CondaEnvName python @Arguments
    } else {
        & python @Arguments
    }
}

function Resolve-PythonRuntime {
    # 1. If python is already available and works, just use it
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        try {
            $ver = (& python --version) 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[INFO] Found python: $ver"
                $script:UseCondaRun = $false
                return
            }
        } catch {}
    }

    # 2. Try common Miniconda/Anaconda paths (including user-specified E:\Miniconda3)
    $possibleCondaPaths = @(
        "E:\Miniconda3\Scripts\conda.exe",
        "E:\Miniconda3\condabin\conda.bat",
        "$env:UserProfile\miniconda3\Scripts\conda.exe",
        "$env:UserProfile\miniconda3\condabin\conda.bat",
        "$env:UserProfile\anaconda3\Scripts\conda.exe",
        "$env:UserProfile\anaconda3\condabin\conda.bat",
        "$env:ProgramData\miniconda3\Scripts\conda.exe",
        "$env:ProgramData\anaconda3\Scripts\conda.exe"
    )
    $foundConda = $null
    foreach ($p in $possibleCondaPaths) {
        if (Test-Path $p) {
            $foundConda = $p
            Write-Host "[INFO] Found conda at: $p"
            break
        }
    }

    # 3. Try to use conda to run
    if ($foundConda) {
        $script:FoundCondaPath = $foundConda
        $preferred = $env:HEGEL_CONDA_ENV
        if (-not $preferred -or $preferred.Trim() -eq "") {
            $preferred = "hegel"
        }
        
        # Try hegel first, then base
        $envToUse = $preferred
        try {
            $envList = & $foundConda env list --json 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue
            $availableEnvs = $envList.envs | ForEach-Object { ($_ -split "[\\/]" | Select-Object -Last 1) }
            if ($availableEnvs -contains $preferred) {
                $envToUse = $preferred
            } elseif ($availableEnvs -contains "base") {
                $envToUse = "base"
            } else {
                FailAndExit "No suitable conda env found. Available: $($availableEnvs -join ', ')" @(
                    "Create env: conda create -n hegel python=3.12 -y",
                    "Install deps: conda activate hegel && pip install -r requirements.txt"
                )
            }
        } catch {
            Write-Host "[WARN] Could not list conda envs, trying default: hegel"
        }

        $script:UseCondaRun = $true
        $script:CondaEnvName = $envToUse
        Write-Host "[INFO] Using conda at: $foundConda"
        Write-Host "[INFO] Using conda run -n $envToUse"
        return
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
    $portBusy = netstat -ano | Select-String ":8501"
    if ($portBusy) {
        Write-Host "[NOTICE] Port 8501 is already in use. Trying to restart with latest code..."
        $portPids = @()
        foreach ($line in $portBusy) {
            $parts = ($line.ToString().Trim() -split "\s+")
            if ($parts.Length -ge 5) {
                $pidStr = $parts[-1]
                if ($pidStr -match "^\d+$") { $portPids += [int]$pidStr }
            }
        }
        $portPids = $portPids | Select-Object -Unique
        foreach ($procId in $portPids) {
            try {
                $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId"
                $cmd = $proc.CommandLine
                if ($cmd -and $cmd -match "streamlit" -and $cmd -match "app_streamlit.py") {
                    Write-Host "[INFO] Stopping old Streamlit PID: $procId"
                    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                }
            } catch {}
        }
        Start-Sleep -Seconds 1
        $portBusy = netstat -ano | Select-String ":8501"
        if ($portBusy) {
            FailAndExit "Port 8501 is still busy after restart attempt." @(
                "Close old app windows and retry",
                "Or run app on another port manually"
            )
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
    Write-Host "URL: http://localhost:8501"
    Write-Host "Keep this window open while using the app."
    Start-Process "http://localhost:8501" | Out-Null

    Invoke-Py -Arguments @("-m", "streamlit", "run", "app_streamlit.py", "--server.headless", "true", "--server.port", "8501")
    if ($LASTEXITCODE -ne 0) {
        FailAndExit "Streamlit failed to start." @(
            "Check selected conda env has streamlit installed",
            "Check port 8501 availability",
            "Manual run: python -m streamlit run app_streamlit.py --server.port 8501"
        )
    }
}
catch {
    FailAndExit ("Unhandled error: " + $_.Exception.Message) @(
        "Copy this message and share it",
        "Verify conda env and Python dependencies"
    )
}
