param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $PSScriptRoot "..\mods\wyccc_variant_selector_patch\cover.png"
}

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
$parent = [System.IO.Path]::GetDirectoryName($resolvedOutput)
[System.IO.Directory]::CreateDirectory($parent) | Out-Null

$size = 500
$bitmap = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$font = $null
$brush = $null
$format = $null
try {
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    # A single flat field keeps the requested cover free of people and patterns.
    $graphics.Clear([System.Drawing.Color]::FromArgb(14, 22, 36))

    $font = New-Object System.Drawing.Font("Arial Narrow", 36, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(246, 239, 220))
    $format = New-Object System.Drawing.StringFormat
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    $format.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap
    $rectangle = New-Object System.Drawing.RectangleF(10, 205, 480, 90)
    $graphics.DrawString("Dynamic Variant Selector Patch", $font, $brush, $rectangle, $format)
    $bitmap.Save($resolvedOutput, [System.Drawing.Imaging.ImageFormat]::Png)
    if ([System.IO.Path]::GetFileName($resolvedOutput).ToLowerInvariant() -eq "cover.png") {
        $sibling = Join-Path $parent "wyccc_variant_selector_patch.png"
        $bitmap.Save($sibling, [System.Drawing.Imaging.ImageFormat]::Png)
    }
}
finally {
    if ($format) { $format.Dispose() }
    if ($brush) { $brush.Dispose() }
    if ($font) { $font.Dispose() }
    if ($graphics) { $graphics.Dispose() }
    if ($bitmap) { $bitmap.Dispose() }
}

Write-Output $resolvedOutput
