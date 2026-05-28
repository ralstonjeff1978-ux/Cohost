# =============================================================================
#  COHOST — Installer for Hans's PC (Windows + NVIDIA CUDA)
#  Run via INSTALL.bat (handles execution policy).
#  Idempotent: safe to re-run if anything fails partway.
# =============================================================================

$ErrorActionPreference = "Stop"
$ProgressPreference   = "SilentlyContinue"   # speeds up Invoke-WebRequest

# Resolve install root from this script's location (one level above .\install)
$Root        = (Resolve-Path "$PSScriptRoot\..").Path
$LogPath     = Join-Path $Root "install\install_log.txt"
$VoiceVenv   = Join-Path $Root "voice\venv312"
$MainVenv    = Join-Path $Root ".venv"

# Tee everything to a log
Start-Transcript -Path $LogPath -Append | Out-Null

function Section($t) { Write-Host ""; Write-Host "==== $t ====" -ForegroundColor Cyan }
function OK($t)      { Write-Host "  [OK] $t"  -ForegroundColor Green }
function Warn($t)    { Write-Host "  [!!] $t"  -ForegroundColor Yellow }
function Fail($t)    { Write-Host "  [XX] $t"  -ForegroundColor Red;   throw $t }

Write-Host ""
Write-Host "============================================================"
Write-Host "  COHOST — Installer"
Write-Host "  Install root: $Root"
Write-Host "  Log:          $LogPath"
Write-Host "============================================================"


# ── 1. Python 3.12 ──────────────────────────────────────────────────────────
Section "Checking Python 3.12"
$pyExe = $null
foreach ($cmd in @("py -3.12", "python3.12", "python")) {
    try {
        $v = & ($cmd -split ' ')[0] ($cmd -split ' ' | Select-Object -Skip 1) --version 2>&1
        if ($v -match "Python 3\.12") {
            $pyExe = $cmd
            OK "Found: $v via '$cmd'"
            break
        }
    } catch { }
}
if (-not $pyExe) {
    Warn "Python 3.12 was not detected on PATH."
    Write-Host "  Install Python 3.12 from https://www.python.org/downloads/release/python-3120/"
    Write-Host "  During install: CHECK 'Add python.exe to PATH'."
    Fail "Re-run INSTALL.bat after Python 3.12 is installed."
}


# ── 2. GPU selection ────────────────────────────────────────────────────────
Section "GPU Setup"
$gpus = Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name
$nvidia = $gpus | Where-Object { $_ -match 'NVIDIA' }
$amd    = $gpus | Where-Object { $_ -match 'AMD|Radeon' }
Write-Host "  Detected GPUs: $($gpus -join ' | ')"
Write-Host ""
Write-Host "  Which GPU does this machine have?"
Write-Host ""
Write-Host "    [1] NVIDIA (CUDA)   — RTX/GTX cards, GPU-accelerated TTS"
Write-Host "    [2] AMD Radeon      — RX/Radeon cards (CPU mode — DirectML"
Write-Host "                          support coming when torch-directml reaches torch 2.6)"
Write-Host "    [3] CPU only        — No GPU acceleration"
Write-Host ""
if ($nvidia) {
    Write-Host "  >> Detected NVIDIA: $($nvidia -join ', ')" -ForegroundColor Green
} elseif ($amd) {
    Write-Host "  >> Detected AMD: $($amd -join ', ')" -ForegroundColor Yellow
}
$gpuChoice = Read-Host "  Enter 1, 2, or 3"
$gpuBackend = "cpu"
switch ($gpuChoice) {
    "1" { $gpuBackend = "cuda"; OK "Selected: NVIDIA CUDA" }
    "2" {
        $gpuBackend = "cpu"
        OK "Selected: AMD Radeon (CPU mode for now)"
        Warn "torch-directml currently requires torch 2.4 but Chatterbox needs 2.6."
        Warn "TTS runs on CPU. Re-run INSTALL.bat when DirectML catches up."
    }
    "3" { $gpuBackend = "cpu"; OK "Selected: CPU only" }
    default {
        Warn "Invalid choice '$gpuChoice' — defaulting to CPU."
        $gpuBackend = "cpu"
    }
}
# Save the choice so selftest and tts_server can read it
$gpuFile = Join-Path $Root "install\gpu_backend.txt"
Set-Content -Path $gpuFile -Value $gpuBackend
OK "GPU backend saved to install\gpu_backend.txt"


# ── 3. Ollama ───────────────────────────────────────────────────────────────
Section "Checking Ollama"
$ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollamaExe) {
    Warn "Ollama not found on PATH."
    Write-Host "  Install Ollama from https://ollama.com/download/windows"
    Write-Host "  Then re-run INSTALL.bat. (Cohost works without it but the brain won't reply.)"
} else {
    $ov = & ollama --version 2>&1
    OK "Found: $ov"
    # Make sure Ollama is running (the Windows installer registers a service, but if not...)
    try {
        $null = Invoke-WebRequest "http://localhost:11434/" -TimeoutSec 3 -UseBasicParsing
        OK "Ollama daemon responding on localhost:11434"
    } catch {
        Warn "Ollama not responding on :11434. Start it from the Start menu (it should auto-launch on login)."
    }
}


# ── 4. Main venv (.venv) ────────────────────────────────────────────────────
Section "Creating main venv (.venv)"
$pythonCmd = $pyExe -split ' '
if (-not (Test-Path $MainVenv)) {
    & $pythonCmd[0] $pythonCmd[1..($pythonCmd.Length-1)] -m venv $MainVenv
    OK "Created $MainVenv"
} else {
    OK "Already exists at $MainVenv"
}
$mainPy  = Join-Path $MainVenv "Scripts\python.exe"
$mainPip = Join-Path $MainVenv "Scripts\pip.exe"

& $mainPy -m pip install --quiet --upgrade pip wheel setuptools
& $mainPip install --quiet pyyaml requests numpy sounddevice soundfile faster-whisper silero-vad keyboard flask
OK "Main venv ready"


# ── 5. Voice venv (voice/venv312) ───────────────────────────────────────────
Section "Creating voice venv (voice/venv312)"
if (-not (Test-Path $VoiceVenv)) {
    & $pythonCmd[0] $pythonCmd[1..($pythonCmd.Length-1)] -m venv $VoiceVenv
    OK "Created $VoiceVenv"
} else {
    OK "Already exists at $VoiceVenv"
}
$voicePy  = Join-Path $VoiceVenv "Scripts\python.exe"
$voicePip = Join-Path $VoiceVenv "Scripts\pip.exe"

& $voicePy -m pip install --quiet --upgrade pip wheel setuptools

Section "Installing PyTorch into voice venv"
if ($gpuBackend -eq "cuda") {
    Write-Host "  Installing torch+cu124 (~2 GB download — be patient)..."
    & $voicePip install --quiet torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
    OK "PyTorch (CUDA) installed"
    $probe = & $voicePy -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')"
    Write-Host "  torch probe: $probe"
    if ($probe -notmatch "True") {
        Warn "torch.cuda.is_available() is False. Driver may be too old — update NVIDIA drivers from https://www.nvidia.com/Download/index.aspx"
    }
} else {
    Write-Host "  Installing CPU PyTorch..."
    & $voicePip install --quiet torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
    OK "PyTorch (CPU) installed"
    $probe = & $voicePy -c "import torch; print(torch.__version__, torch.cuda.is_available())"
    Write-Host "  torch probe: $probe"
}

Section "Installing Chatterbox + audio libs into voice venv"
# --no-deps avoids the torch==2.6.0 pin fight; we already installed the right torch above
& $voicePip install --quiet chatterbox-tts --no-deps
& $voicePip install --quiet conformer diffusers librosa numpy omegaconf pykakasi pyloudnorm resemble-perth s3tokenizer safetensors spacy-pkuseg transformers sounddevice soundfile faster-whisper silero-vad
OK "Chatterbox + audio libs installed"


# ── 6. Pre-download Chatterbox weights (so first run isn't a surprise wait) ──
Section "Pre-downloading Chatterbox model weights (~2 GB)"
$dlScript = @'
import os, sys
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "300")
try:
    from chatterbox.tts import ChatterboxTTS
    print("Downloading model weights...", flush=True)
    m = ChatterboxTTS.from_pretrained(device="cpu")  # CPU is fine, we just want the download
    print("Weights cached.", flush=True)
except Exception as e:
    print(f"WARN: weight pre-download failed: {e}", flush=True)
    sys.exit(0)  # Not fatal — first real run will download then
'@
$dlScript | & $voicePy -
OK "Weights cached (or will be on first run)"


# ── 7. Ollama model pull ────────────────────────────────────────────────────
if ($ollamaExe) {
    Section "Pulling default Ollama model (gpt-oss:120b-cloud)"
    Write-Host "  This requires you to be signed into Ollama Cloud."
    Write-Host "  If pull fails, run 'ollama signin' once, then re-run INSTALL.bat."
    try {
        & ollama pull gpt-oss:120b-cloud
        OK "Model pulled"
    } catch {
        Warn "ollama pull failed. Sign in with 'ollama signin' then re-run."
    }
}


# ── 7b. cloudflared (for Remote Help) ───────────────────────────────────────
Section "Checking cloudflared (Remote Help feature)"
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if ($cf) {
    OK "cloudflared already installed: $cf"
} else {
    Write-Host "  cloudflared is optional — only needed for the 'Remote help' button."
    Write-Host "  Attempting install via winget..."
    try {
        & winget install --silent --accept-source-agreements --accept-package-agreements Cloudflare.cloudflared 2>&1 | Out-Null
        $cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
        if ($cf) { OK "cloudflared installed: $cf" }
        else     { Warn "winget install of cloudflared did not register on PATH. Install manually if you need Remote Help: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" }
    } catch {
        Warn "Could not install cloudflared via winget. Remote Help will be disabled until you install it manually."
    }
}


# ── 7c. Persist COHOST_HOME for the user ────────────────────────────────────
Section "Setting COHOST_HOME environment variable"
try {
    [System.Environment]::SetEnvironmentVariable("COHOST_HOME", $Root, "User")
    OK "COHOST_HOME set for current user: $Root"
} catch {
    Warn "Could not set COHOST_HOME — Cohost will fall back to its install path at runtime."
}


# ── 8. Done ─────────────────────────────────────────────────────────────────
Section "Install complete"
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    1. Double-click SELFTEST.bat — produces install\selftest_report.txt"
Write-Host "    2. Send selftest_report.txt back to cypherstone"
Write-Host "    3. When green-lit, double-click Cohost.bat to start"
Write-Host ""

Stop-Transcript | Out-Null
