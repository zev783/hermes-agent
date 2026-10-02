# Hermes Revit Operator Add-in

This is the in-process Revit bridge for the Hermes Revit human-operator layer.

It is intentionally small:

- loads as an `IExternalApplication`
- runs work on Revit's API thread via the `Idling` event
- writes active document status to the configured sandbox
- reads queued Hermes commands from `bridge/command_queue.jsonl`
- writes command results to `bridge/command_results.jsonl`
- exports read-only metadata to `bridge/metadata_snapshot.json`

Every Revit that loads the add-in shares one bridge folder, so:

- Status files are written per process as well: `addin_status.<pid>.json`,
  `addin_heartbeat.<pid>.json` and `active_document.<pid>.json`. The shared
  `addin_status.json`, `addin_heartbeat.json` and `active_document.json` are
  last-writer-wins across tandem sessions and stay only for older readers.
  Give bridge commands `--hwnd` (or `--pid`) to read the session that owns a
  window.
- Commands queued more than 15 minutes before the Revit process started are
  skipped, not replayed. One `skipped_stale_commands` result lists them. A
  command queued just before launching Revit still runs.
- Status writes rename a per-process temp file over the target, at most once a
  second and without sleeping on the UI thread. A thread-pool timer deletes
  leftover temp files (`*~RF*.TMP` from older builds' `File.Replace`,
  `*.json.*.tmp`) and the per-process files of exited Revit processes, once
  they are 10 minutes old.

Supported Revit versions and add-in targets:

| Revit | Target framework |
| --- | --- |
| 2022 | `net48` |
| 2023 | `net48` |
| 2024 | `net48` |
| 2025 | `net8.0-windows` |
| 2026 | `net8.0-windows` |
| 2027 | `net10.0-windows` |

Build for a specific Revit version:

```powershell
dotnet build .\tools\revit_operator\addin\HermesRevitOperator.csproj -c Release -p:RevitVersion=2025 -p:RevitInstallDir="C:\Program Files\Autodesk\Revit 2025"
```

Or use the guarded helper:

```powershell
.\tools\revit_operator\addin\build_addin.ps1 -RevitVersion 2025
```

The helper uses `dotnet` from `PATH` when it has SDKs available, and falls back to
`%USERPROFILE%\.dotnet-hermes\dotnet.exe` on Hermes-managed workstations.

Install the manifest after the DLL exists:

```powershell
.\tools\revit_operator\addin\install_manifest.ps1 -RevitVersion 2025
```

This machine needs the matching .NET SDK/reference assemblies to build the DLL. Revit 2022-2024 run add-ins on .NET Framework 4.8, Revit 2025-2026 run add-ins on .NET 8, and Revit 2027 targets .NET 10.
