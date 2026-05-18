param(
    [string]$Configuration = "Release",
    [string]$RevitInstallDir = "C:\Program Files\Autodesk\Revit 2025"
)

$ErrorActionPreference = "Stop"
$Project = Join-Path $PSScriptRoot "HermesRevitOperator.csproj"

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw "dotnet was not found. Install a .NET SDK before building the Revit add-in."
}

$SdkList = & dotnet --list-sdks
if (-not $SdkList) {
    throw "No .NET SDKs were found. Revit 2025 add-in builds require a .NET 8 SDK or newer."
}

if (-not (Test-Path (Join-Path $RevitInstallDir "RevitAPI.dll"))) {
    throw "RevitAPI.dll was not found under $RevitInstallDir"
}

& dotnet build $Project -c $Configuration -p:RevitInstallDir="$RevitInstallDir"
