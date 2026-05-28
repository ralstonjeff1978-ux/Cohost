# =============================================================================
#  COHOST — Self-test for Hans's PC
#  Writes install\selftest_report.txt. Hans sends that file back to cypherstone.
# =============================================================================

$ErrorActionPreference = "Continue"
$Root      = (Resolve-Path "$PSScriptRoot\..").Path
$VoiceVenv = Join-Path $Root "voice\venv312"
$MainVenv  = Join-Path $Root ".venv"
$Report    = Join-Path $Root "install\selftest_report.txt"
$VoicePy   = Join-Path $VoiceVenv "Scripts\python.exe"
$MainPy    = Join-Path $MainVenv  "Scripts\python.exe"

# Reset the report
"" | Set-Content $Report

function Log($msg) {
    Write-Host $msg
    Add-Content -Path $Report -Value $msg
}

function RunPy($py, $code) {
    try {
        $tmp = New-TemporaryFile
        Set-Content -Path $tmp -Value $code
        $out = & $py $tmp 2>&1 | Out-String
        Remove-Item $tmp -ErrorAction SilentlyContinue
        return $out.Trim()
    } catch {
        return "ERROR: $_"
    }
}

Log "============================================================"
Log "  COHOST — Self-test report"
Log "  Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Log "  Machine:   $env:COMPUTERNAME / $env:USERNAME"
Log "  Install:   $Root"
Log "============================================================"


# ── 1. Hardware ─────────────────────────────────────────────────────────────
Log ""
Log "[1] Hardware"
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
$ram = [math]::Round(((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory) / 1GB)
Log "  CPU: $cpu"
Log "  RAM: $ram GB"
$gpus = Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name
Log "  GPUs: $($gpus -join ' | ')"


# ── 2. Python ───────────────────────────────────────────────────────────────
Log ""
Log "[2] Python venvs"
if (Test-Path $MainPy)  { Log "  main venv: $(& $MainPy --version 2>&1)" }
else                    { Log "  main venv: MISSING — run INSTALL.bat" }
if (Test-Path $VoicePy) { Log "  voice venv: $(& $VoicePy --version 2>&1)" }
else                    { Log "  voice venv: MISSING — run INSTALL.bat" }


# ── 3. Torch + GPU ──────────────────────────────────────────────────────────
Log ""
Log "[3] PyTorch + GPU"
$gpuFile = Join-Path $Root "install\gpu_backend.txt"
if (Test-Path $gpuFile) {
    $gpuBackend = (Get-Content $gpuFile).Trim()
    Log "  gpu_backend.txt   = $gpuBackend"
} else {
    $gpuBackend = "unknown"
    Log "  gpu_backend.txt   = NOT FOUND (run INSTALL.bat first)"
}
if (Test-Path $VoicePy) {
    $torchProbeCode = @'
import torch
print(f"torch.__version__   = {torch.__version__}")
print(f"cuda.is_available   = {torch.cuda.is_available()}")
print(f"cuda.device_count   = {torch.cuda.device_count()}")
if torch.cuda.is_available():
    print(f"cuda.device_name    = {torch.cuda.get_device_name(0)}")
    print(f"cuda.compute_cap    = {torch.cuda.get_device_capability(0)}")
try:
    import torch_directml
    print(f"directml.available  = True")
    print(f"directml.devices    = {torch_directml.device_count()}")
    print(f"directml.gpu_name   = {torch_directml.device_name(0)}")
except ImportError:
    print(f"directml.available  = False (not installed)")
except Exception as e:
    print(f"directml.available  = Error: {e}")
'@
    $probe = RunPy $VoicePy $torchProbeCode
    foreach ($line in $probe -split "`r?`n") { Log "  $line" }
} else {
    Log "  SKIP — voice venv missing"
}


# ── 4. Ollama ───────────────────────────────────────────────────────────────
Log ""
Log "[4] Ollama"
$oll = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $oll) {
    Log "  ollama: NOT INSTALLED — install from https://ollama.com/download/windows"
} else {
    Log "  ollama: $(& ollama --version 2>&1)"
    try {
        $tags = Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 5
        $names = $tags.models | ForEach-Object { $_.name }
        Log "  ollama models pulled locally: $($names -join ', ')"
    } catch {
        Log "  ollama daemon: NOT RESPONDING on :11434 (start it from Start menu)"
    }
}


# ── 5. Chatterbox load + GPU generate ───────────────────────────────────────
Log ""
Log "[5] Chatterbox TTS load + timed generation"
$voiceSample = Join-Path $Root "voice\samples\aria_voice.wav"
if ((Test-Path $VoicePy) -and (Test-Path $voiceSample)) {
    $voiceSamplePy = $voiceSample.Replace('\', '/')
    $ttsCode = @'
import os, sys, time, torch
from pathlib import Path
from chatterbox.tts import ChatterboxTTS

VOICE = os.environ['COHOST_VOICE_SAMPLE']

# Read saved GPU backend preference
gpu_file = Path(os.environ.get('COHOST_ROOT', '.')) / 'install' / 'gpu_backend.txt'
saved_backend = gpu_file.read_text().strip() if gpu_file.exists() else ''

device = 'cpu'
if saved_backend == 'directml':
    try:
        import torch_directml
        device = torch_directml.device()
        print(f"device                = directml ({torch_directml.device_name(0)})")
    except Exception as e:
        print(f"device                = cpu (directml failed: {e})")
elif torch.cuda.is_available():
    device = 'cuda'
    print(f"device                = cuda ({torch.cuda.get_device_name(0)})")
else:
    print(f"device                = cpu")

t0 = time.time()
m = ChatterboxTTS.from_pretrained(device=device)
print(f"model_load_secs       = {time.time()-t0:.1f}")

text = 'Hi, this is Aria. Recording check, one two three.'
t0 = time.time()
_ = m.generate(text, audio_prompt_path=VOICE)
print(f"first_generate_secs   = {time.time()-t0:.1f}  (chars={len(text)})")

t0 = time.time()
_ = m.generate('Second test sentence to check for any second-call issues.',
               audio_prompt_path=VOICE)
print(f"second_generate_secs  = {time.time()-t0:.1f}  (should match the first; if much higher, GPU has a state-leak issue)")
'@
    $env:COHOST_VOICE_SAMPLE = $voiceSamplePy
    $env:COHOST_ROOT = $Root
    $tts = RunPy $VoicePy $ttsCode
    Remove-Item env:COHOST_VOICE_SAMPLE -ErrorAction SilentlyContinue
    Remove-Item env:COHOST_ROOT -ErrorAction SilentlyContinue
    foreach ($line in $tts -split "`r?`n") { Log "  $line" }
} else {
    Log "  SKIP — voice venv or aria_voice.wav missing"
}


# ── 6. Microphone devices ───────────────────────────────────────────────────
Log ""
Log "[6] Microphone devices"
if (Test-Path $MainPy) {
    $micsCode = @'
import sounddevice as sd
for i, d in enumerate(sd.query_devices()):
    if d.get("max_input_channels", 0) > 0:
        print(f"  [{i}] {d['name']}  ch={d['max_input_channels']}  sr={int(d['default_samplerate'])}")
'@
    $mics = RunPy $MainPy $micsCode
    Log $mics
} else {
    Log "  SKIP — main venv missing"
}


# ── 7. Done ─────────────────────────────────────────────────────────────────
Log ""
Log "============================================================"
Log "  Report saved to: $Report"
Log "  Email this file to cypherstone."
Log "============================================================"
