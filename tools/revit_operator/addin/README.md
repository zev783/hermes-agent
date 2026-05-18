# Hermes Revit Operator Add-in

This is the in-process Revit bridge for the Hermes Revit human-operator layer.

It is intentionally small:

- loads as an `IExternalApplication`
- runs work on Revit's API thread via the `Idling` event
- writes active document status to the configured sandbox
- reads queued Hermes commands from `bridge/command_queue.jsonl`
- writes command results to `bridge/command_results.jsonl`
- exports read-only metadata to `bridge/metadata_snapshot.json`

Build for Revit 2025:

```powershell
dotnet build .\tools\revit_operator\addin\HermesRevitOperator.csproj -c Release -p:RevitInstallDir="C:\Program Files\Autodesk\Revit 2025"
```

Or use the guarded helper:

```powershell
.\tools\revit_operator\addin\build_addin.ps1 -RevitInstallDir "C:\Program Files\Autodesk\Revit 2025"
```

Install the manifest after the DLL exists:

```powershell
.\tools\revit_operator\addin\install_manifest.ps1 -RevitVersion 2025
```

This machine needs a .NET SDK to build the DLL. Revit 2025 runs add-ins on .NET 8.
