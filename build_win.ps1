$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# EyeDoc Windows Build Script
# ---------------------------------------------------------------------------

# 1. Activate virtual environment
Write-Host "`n[1/5] Activating virtual environment..." -ForegroundColor Cyan
. .\.venv\Scripts\Activate.ps1

# 2. Install / sync Python dependencies
#    Windows-only packages are selected via sys_platform markers in requirements.txt
Write-Host "`n[2/5] Installing Python dependencies..." -ForegroundColor Cyan
pip install -r requirements.txt --quiet

# 3. Build frontend
Write-Host "`n[3/5] Building frontend..." -ForegroundColor Cyan
Push-Location frontend
yarn build
Pop-Location

# 4. Verify the .ico icon exists and is non-empty; regenerate from PNG if needed
Write-Host "`n[4/5] Checking application icon..." -ForegroundColor Cyan
$icoPath = ".\AppIcon.appiconset\appstore1024.ico"
$icoMissing = (-not (Test-Path $icoPath))
$icoEmpty   = (-not $icoMissing) -and ((Get-Item $icoPath).Length -eq 0)

if ($icoMissing -or $icoEmpty) {
    Write-Host "  Generating .ico from PNG (System.Drawing)..." -ForegroundColor Yellow
    Add-Type -AssemblyName System.Drawing

    $src    = New-Object System.Drawing.Bitmap(".\AppIcon.appiconset\appstore1024.png")
    $sizes  = @(256, 128, 64, 48, 32, 16)
    $ms     = New-Object System.IO.MemoryStream
    $bw     = New-Object System.IO.BinaryWriter($ms)

    # ICO file header
    $bw.Write([UInt16]0)             # reserved
    $bw.Write([UInt16]1)             # type = ICO
    $bw.Write([UInt16]$sizes.Count)  # image count

    # Encode each size as PNG into its own stream
    $imageStreams = @()
    foreach ($s in $sizes) {
        $bmp   = New-Object System.Drawing.Bitmap($src, $s, $s)
        $pngMs = New-Object System.IO.MemoryStream
        $bmp.Save($pngMs, [System.Drawing.Imaging.ImageFormat]::Png)
        $imageStreams += $pngMs
        $bmp.Dispose()
    }

    # ICONDIRENTRY for each image (data starts after header + all entries)
    $dataOffset = 6 + $sizes.Count * 16
    for ($i = 0; $i -lt $sizes.Count; $i++) {
        $sz = if ($sizes[$i] -ge 256) { 0 } else { $sizes[$i] }
        $bw.Write([Byte]$sz)                            # width  (0 = 256)
        $bw.Write([Byte]$sz)                            # height (0 = 256)
        $bw.Write([Byte]0)                              # color count
        $bw.Write([Byte]0)                              # reserved
        $bw.Write([UInt16]1)                            # planes
        $bw.Write([UInt16]32)                           # bit count
        $bw.Write([UInt32]$imageStreams[$i].Length)     # size of image data
        $bw.Write([UInt32]$dataOffset)                  # offset of image data
        $dataOffset += $imageStreams[$i].Length
    }

    # Write image data
    foreach ($ims in $imageStreams) {
        $bw.Write($ims.ToArray())
    }

    $absIcoPath = (Join-Path (Get-Location) $icoPath)
    [System.IO.File]::WriteAllBytes($absIcoPath, $ms.ToArray())
    $src.Dispose()
    Write-Host "  Icon saved to $absIcoPath" -ForegroundColor Green
} else {
    Write-Host "  Icon OK ($((Get-Item $icoPath).Length) bytes)" -ForegroundColor Green
}

# 5. Build Windows executable via spec file
Write-Host "`n[5/5] Building EyeDoc.exe with PyInstaller..." -ForegroundColor Cyan
pyinstaller --noconfirm app.spec

Write-Host "`nBuild complete!" -ForegroundColor Green
Write-Host "  Executable : dist\EyeDoc\EyeDoc.exe"
Write-Host "  Run with   : .\dist\EyeDoc\EyeDoc.exe"
