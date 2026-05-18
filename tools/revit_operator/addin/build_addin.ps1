param(
    [string]$Configuration = "Release",
    [ValidateSet("2022", "2023", "2024", "2025", "2026", "2027")]
    [string]$RevitVersion = "2025",
    [string]$RevitInstallDir = "",
    [string]$DotNetPath = ""
)

$ErrorActionPreference = "Stop"
$Project = Join-Path $PSScriptRoot "HermesRevitOperator.csproj"

$TargetFrameworkByVersion = @{
    "2022" = "net48"
    "2023" = "net48"
    "2024" = "net48"
    "2025" = "net8.0-windows"
    "2026" = "net8.0-windows"
    "2027" = "net10.0-windows"
}

if (-not $RevitInstallDir) {
    $RevitInstallDir = "C:\Program Files\Autodesk\Revit $RevitVersion"
}

if (-not $DotNetPath) {
    $DotNetCommand = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($DotNetCommand) {
        $DotNetPath = $DotNetCommand.Source
    }
}

if ($DotNetPath) {
    $SdkList = & $DotNetPath --list-sdks
}

$HermesLocalDotNet = Join-Path $env:USERPROFILE ".dotnet-hermes\dotnet.exe"
if (-not $SdkList -and (Test-Path $HermesLocalDotNet)) {
    $DotNetPath = $HermesLocalDotNet
    $SdkList = & $DotNetPath --list-sdks
}

if (-not $DotNetPath) {
    throw "dotnet was not found. Install a .NET SDK before building the Revit add-in."
}

if (-not $SdkList) {
    throw "No .NET SDKs were found. Revit $RevitVersion add-in builds require $($TargetFrameworkByVersion[$RevitVersion]) support."
}

if (-not (Test-Path (Join-Path $RevitInstallDir "RevitAPI.dll"))) {
    throw "RevitAPI.dll was not found under $RevitInstallDir"
}

& $DotNetPath build $Project -c $Configuration -p:RevitVersion="$RevitVersion" -p:RevitInstallDir="$RevitInstallDir"
