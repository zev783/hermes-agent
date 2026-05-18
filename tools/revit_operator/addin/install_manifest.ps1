param(
    [string]$RevitVersion = "2025",
    [string]$AssemblyPath = "",
    [string]$AddinsRoot = "$env:APPDATA\Autodesk\Revit\Addins"
)

$ErrorActionPreference = "Stop"

if (-not $AssemblyPath) {
    $AssemblyPath = Join-Path $PSScriptRoot "bin\Release\net8.0-windows\HermesRevitOperator.dll"
}

if (-not (Test-Path $AssemblyPath)) {
    throw "Add-in assembly was not found: $AssemblyPath. Build the add-in first."
}

$TargetDir = Join-Path $AddinsRoot $RevitVersion
$TargetManifest = Join-Path $TargetDir "HermesRevitOperator.addin"
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

$Manifest = @"
<?xml version="1.0" encoding="utf-8" standalone="no"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>Hermes Revit Operator</Name>
    <Assembly>$AssemblyPath</Assembly>
    <AddInId>9B9E5F15-C0B3-4D2A-8E4D-5F7D07F81A11</AddInId>
    <FullClassName>Hermes.RevitOperator.HermesRevitOperatorApp</FullClassName>
    <VendorId>HERM</VendorId>
    <VendorDescription>Hermes local Revit human-operator bridge</VendorDescription>
  </AddIn>
</RevitAddIns>
"@

Set-Content -Path $TargetManifest -Value $Manifest -Encoding UTF8
Write-Host "Installed $TargetManifest"
