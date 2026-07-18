# Pin to the same commit CI builds against (.github/workflows/build.yml)
$demucsSha = "e976d93ecc3865e5757426930257e200846a520a"

# Check if demucs_source exists
if (-not (Test-Path "demucs_source")) {
    Write-Host "Cloning Demucs..."
    git clone https://github.com/facebookresearch/demucs.git demucs_source
    git -C demucs_source checkout $demucsSha
} else {
    # Existing checkouts have patches applied, so don't force a checkout over them
    Write-Host "Demucs source already exists. To re-pin to $demucsSha, delete demucs_source and re-run."
}

# Patch requirements_minimal.txt
$reqFile = "demucs_source/requirements_minimal.txt"
if (Test-Path $reqFile) {
    Write-Host "Patching $reqFile..."
    $content = Get-Content $reqFile
    $content = $content | Where-Object { $_ -notmatch "lameenc" -and $_ -notmatch "torchaudio" }
    Set-Content -Path $reqFile -Value $content
}

# Patch audio.py
$audioFile = "demucs_source/demucs/audio.py"
if (Test-Path $audioFile) {
    Write-Host "Patching $audioFile..."
    $audioContent = Get-Content $audioFile -Raw
    $audioContent = $audioContent -replace "import lameenc", "try:`r`n    import lameenc`r`nexcept ImportError:`r`n    lameenc = None"
    Set-Content -Path $audioFile -Value $audioContent
}

# Install
Write-Host "Installing Demucs..."
pip install -e ./demucs_source

Write-Host "Setup Complete! You can now run python app.py"
