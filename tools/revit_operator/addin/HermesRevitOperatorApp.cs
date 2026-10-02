using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;

namespace Hermes.RevitOperator;

public class HermesRevitOperatorApp : IExternalApplication
{
    private const string OperatorProtocolVersion = "0.2";
    private const string SourceCapabilityStamp = "continuous-idling-status-file-retry-v2";
    private const string SupportedRevitVersions = "2022;2023;2024;2025;2026;2027";
#if REVIT2022
    private const string TargetRevitVersion = "2022";
    private const string TargetFrameworkMoniker = "net48";
#elif REVIT2023
    private const string TargetRevitVersion = "2023";
    private const string TargetFrameworkMoniker = "net48";
#elif REVIT2024
    private const string TargetRevitVersion = "2024";
    private const string TargetFrameworkMoniker = "net48";
#elif REVIT2025
    private const string TargetRevitVersion = "2025";
    private const string TargetFrameworkMoniker = "net8.0-windows";
#elif REVIT2026
    private const string TargetRevitVersion = "2026";
    private const string TargetFrameworkMoniker = "net8.0-windows";
#elif REVIT2027
    private const string TargetRevitVersion = "2027";
    private const string TargetFrameworkMoniker = "net10.0-windows";
#else
#error HermesRevitOperator requires REVIT2022, REVIT2023, REVIT2024, REVIT2025, REVIT2026, or REVIT2027.
#endif

    private readonly HashSet<string> _processedCommandIds = new();
    private readonly string _sessionId = Guid.NewGuid().ToString("N");
    private readonly DateTimeOffset _loadedAtUtc = DateTimeOffset.UtcNow;
    private UIApplication? _uiapp;
    private string _sandbox = "";

    // Idling stays continuous (SetRaiseWithoutDelay), but the status files are rewritten at most once per
    // interval, single-attempt, and each tick then yields until a message arrives. Rewriting them on every tick,
    // with retry sleeps whenever another tandem Revit held the shared file, kept the UI thread busy or asleep, so
    // every UI Automation request and window message to this Revit waited ~100-300 ms.
    private const int StatusWriteIntervalMilliseconds = 1000;
    private const uint IdleWaitMilliseconds = 20;
    private const uint QsAllInput = 0x04FF;
    private const uint MwmoInputAvailable = 0x0004;
    private DateTime _lastStatusWriteUtc = DateTime.MinValue;
    private long _queueLength = -1;
    private DateTime _queueWriteUtc = DateTime.MinValue;
    private DateTime _queueRetryAfterUtc = DateTime.MinValue;

    // The shared status files are last-writer-wins across tandem Revit sessions, so each process also writes
    // addin_status.<pid>.json, addin_heartbeat.<pid>.json and active_document.<pid>.json. Hermes reads the files of
    // the process that owns its target window; the shared files stay for older readers.
    private static readonly int ProcessId;
    private static readonly DateTime ProcessStartUtc;
    private static readonly string[] ProcessStatusFileStems = { "addin_status", "addin_heartbeat", "active_document" };

    // Commands queued this long before the Revit process started belong to an earlier session and are skipped:
    // every start used to replay the whole queue, month-old metadata exports and view switches included. A command
    // queued shortly before launch (queue, then open the model) still runs.
    private static readonly TimeSpan QueueReplayGrace = TimeSpan.FromMinutes(15);

    // A thread-pool timer sweeps the bridge folder for temp files that failed writes left behind and for the
    // per-process status files of exited Revit processes. Files younger than StaleBridgeFileAge are never touched.
    private static readonly TimeSpan StaleBridgeFileAge = TimeSpan.FromMinutes(10);
    private static readonly TimeSpan BridgeSweepDelay = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan BridgeSweepInterval = TimeSpan.FromMinutes(15);
    private static readonly string[] BridgeTempFilePrefixes =
    {
        "active_document.", "addin_heartbeat.", "addin_status.", "metadata_snapshot."
    };
    private System.Threading.Timer? _sweepTimer;
    private int _sweepRunning;
    private long _lastSweepTicksUtc;
    private int _lastSweepDeletedFiles;
    private int _sweepDeletedFilesTotal;

    private static readonly JsonSerializerOptions IndentedJson = new() { WriteIndented = true };

    // Read once at load: an in-place redeploy renames the loaded DLL aside, and its path then holds the new build.
    private static readonly string? LoadedAssemblyLastWriteUtc;
    private static readonly long? LoadedAssemblyLength;

    [DllImport("user32.dll")]
    private static extern uint MsgWaitForMultipleObjectsEx(uint nCount, IntPtr[]? pHandles, uint dwMilliseconds, uint dwWakeMask, uint dwFlags);

    static HermesRevitOperatorApp()
    {
        using var process = System.Diagnostics.Process.GetCurrentProcess();
        ProcessId = process.Id;
        try
        {
            ProcessStartUtc = process.StartTime.ToUniversalTime();
        }
        catch (Exception)
        {
            ProcessStartUtc = DateTime.UtcNow;
        }
        try
        {
            var location = typeof(HermesRevitOperatorApp).Assembly.Location;
            if (!string.IsNullOrWhiteSpace(location) && File.Exists(location))
            {
                var file = new FileInfo(location);
                LoadedAssemblyLastWriteUtc = file.LastWriteTimeUtc.ToString("O");
                LoadedAssemblyLength = file.Length;
            }
        }
        catch (Exception)
        {
        }
    }

    public Result OnStartup(UIControlledApplication application)
    {
        _sandbox = ResolveSandbox();
        Directory.CreateDirectory(BridgeDir);
        application.Idling += OnIdling;
        TryWriteStatus(() => WriteBridgeStatus("started", application.ControlledApplication.VersionNumber));
        _sweepTimer = new System.Threading.Timer(_ => SweepBridgeFolder(), null, BridgeSweepDelay, BridgeSweepInterval);
        return Result.Succeeded;
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        application.Idling -= OnIdling;
        _sweepTimer?.Dispose();
        _sweepTimer = null;
        _uiapp = null;
        TryWriteStatus(() => WriteBridgeStatus("stopped", application.ControlledApplication.VersionNumber));
        // This process's heartbeat and active document no longer describe a live session.
        TryDelete(ProcessStatusPath(HeartbeatPath));
        TryDelete(ProcessStatusPath(ActiveDocumentPath));
        return Result.Succeeded;
    }

    private string BridgeDir => Path.Combine(_sandbox, "bridge");
    private string CommandQueuePath => Path.Combine(BridgeDir, "command_queue.jsonl");
    private string CommandResultsPath => Path.Combine(BridgeDir, "command_results.jsonl");
    private string ActiveDocumentPath => Path.Combine(BridgeDir, "active_document.json");
    private string MetadataPath => Path.Combine(BridgeDir, "metadata_snapshot.json");
    private string HeartbeatPath => Path.Combine(BridgeDir, "addin_heartbeat.json");
    private string AddinStatusPath => Path.Combine(BridgeDir, "addin_status.json");

    private string ProcessStatusPath(string sharedPath)
    {
        return Path.Combine(BridgeDir, Path.GetFileNameWithoutExtension(sharedPath) + "." + ProcessId + ".json");
    }

    private void OnIdling(object? sender, IdlingEventArgs args)
    {
        args.SetRaiseWithoutDelay();
        try
        {
            RunIdlingTick(sender);
        }
        finally
        {
            // Returns as soon as input or any message (UI Automation, COM, window messages) is queued.
            MsgWaitForMultipleObjectsEx(0, null, IdleWaitMilliseconds, QsAllInput, MwmoInputAvailable);
        }
    }

    private void RunIdlingTick(object? sender)
    {
        if (sender is UIApplication currentUiapp)
        {
            _uiapp = currentUiapp;
        }
        var uiapp = _uiapp;
        var now = DateTime.UtcNow;
        var statusDue = (now - _lastStatusWriteUtc).TotalMilliseconds >= StatusWriteIntervalMilliseconds;
        if (statusDue)
        {
            _lastStatusWriteUtc = now;
            TryWriteStatus(() => WriteHeartbeat(sender, uiapp, retry: false));
        }
        if (uiapp == null)
        {
            if (statusDue)
            {
                AppendResult(new Dictionary<string, object?>
                {
                    ["id"] = "idling-no-uiapp-" + DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    ["success"] = false,
                    ["error"] = "Revit Idling event did not provide a UIApplication and no fallback UIApplication is available.",
                    ["sender_type"] = sender?.GetType().FullName,
                    ["timestamp"] = DateTimeOffset.UtcNow.ToString("O")
                });
            }
            return;
        }

        try
        {
            if (statusDue)
            {
                Directory.CreateDirectory(BridgeDir);
                TryWriteStatus(() => WriteActiveDocument(uiapp, retry: false));
            }
            if (CommandQueueChanged())
            {
                ProcessQueuedCommands(uiapp);
            }
        }
        catch (Exception ex)
        {
            // Re-read the queue after one interval: a line may have been mid-append when this read failed.
            _queueLength = -1;
            _queueRetryAfterUtc = DateTime.UtcNow.AddMilliseconds(StatusWriteIntervalMilliseconds);
            AppendResult(new Dictionary<string, object?>
            {
                ["id"] = "idling-error-" + DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["success"] = false,
                ["error"] = ex.ToString(),
                ["sender_type"] = sender?.GetType().FullName,
                ["timestamp"] = DateTimeOffset.UtcNow.ToString("O")
            });
        }
    }

    private bool CommandQueueChanged()
    {
        if (DateTime.UtcNow < _queueRetryAfterUtc)
        {
            return false;
        }
        var queue = new FileInfo(CommandQueuePath);
        if (!queue.Exists)
        {
            _queueLength = -1;
            return false;
        }
        if (queue.Length == _queueLength && queue.LastWriteTimeUtc == _queueWriteUtc)
        {
            return false;
        }
        _queueLength = queue.Length;
        _queueWriteUtc = queue.LastWriteTimeUtc;
        return true;
    }

    // Status files are best effort: when another Revit holds the shared file, skip this interval rather than
    // sleep on the UI thread.
    private static void TryWriteStatus(Action write)
    {
        try
        {
            write();
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private void ProcessQueuedCommands(UIApplication uiapp)
    {
        if (!File.Exists(CommandQueuePath))
        {
            return;
        }

        var queueWriteUtc = File.GetLastWriteTimeUtc(CommandQueuePath);
        var text = ReadAllTextShared(CommandQueuePath);
        var lines = text.Split('\n');
        var terminated = text.EndsWith("\n", StringComparison.Ordinal);
        var staleBeforeUtc = ProcessStartUtc - QueueReplayGrace;
        var skippedStale = new List<string>();
        for (var index = 0; index < lines.Length; index++)
        {
            var line = lines[index].Trim();
            if (line.Length == 0)
            {
                continue;
            }
            var lineNumber = index + 1;

            JsonDocument doc;
            try
            {
                doc = JsonDocument.Parse(line);
            }
            catch (JsonException ex)
            {
                // An unterminated last line may still be mid-append; it is read again once the queue changes.
                if (index == lines.Length - 1 && !terminated)
                {
                    continue;
                }
                var invalidId = "invalid-queue-line-" + lineNumber;
                if (!_processedCommandIds.Add(invalidId))
                {
                    continue;
                }
                if (queueWriteUtc < staleBeforeUtc)
                {
                    skippedStale.Add(invalidId);
                    continue;
                }
                AppendResult(new Dictionary<string, object?>
                {
                    ["id"] = invalidId,
                    ["success"] = false,
                    ["error"] = "Command queue line " + lineNumber + " is not valid JSON: " + ex.Message,
                    ["addin"] = AddinInfo(),
                    ["timestamp"] = DateTimeOffset.UtcNow.ToString("O")
                });
                continue;
            }

            using (doc)
            {
                var root = doc.RootElement;
                // The queue is append-only, so a line without an id is keyed by its position.
                var id = GetString(root, "id") ?? "queue-line-" + lineNumber;
                if (!_processedCommandIds.Add(id))
                {
                    continue;
                }
                // Without a timestamp, the queue file's last write bounds how recently the line was appended.
                var queuedAtUtc = GetUtcTimestamp(root, "timestamp") ?? queueWriteUtc;
                if (queuedAtUtc < staleBeforeUtc)
                {
                    skippedStale.Add(id);
                    continue;
                }
                ExecuteQueuedCommand(uiapp, root, id);
            }
        }

        if (skippedStale.Count > 0)
        {
            AppendResult(new Dictionary<string, object?>
            {
                ["id"] = "stale-queue-skip-" + _sessionId + "-" + DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["success"] = true,
                ["status"] = "skipped_stale_commands",
                ["message"] = "Skipped commands queued before this Revit process started; they were not replayed.",
                ["skipped_count"] = skippedStale.Count,
                ["skipped_command_ids"] = skippedStale.Take(50).ToList(),
                ["queued_before_utc"] = staleBeforeUtc.ToString("O"),
                ["addin"] = AddinInfo(),
                ["timestamp"] = DateTimeOffset.UtcNow.ToString("O")
            });
        }
    }

    private void ExecuteQueuedCommand(UIApplication uiapp, JsonElement root, string id)
    {
        try
        {
            var operation = GetString(root, "operation") ?? "";
            var guards = root.TryGetProperty("guards", out var guardElement) ? guardElement : default;
            var allowModelWrite = GetBool(guards, "allow_model_write");
            var allowSync = GetBool(guards, "allow_sync");
            var opArgs = root.TryGetProperty("args", out var argsElement) ? argsElement : default;

            var result = ExecuteOperation(uiapp, operation, opArgs, allowModelWrite, allowSync);
            result["id"] = id;
            result["operation"] = operation;
            result["timestamp"] = DateTimeOffset.UtcNow.ToString("O");
            result["addin"] = AddinInfo();
            AppendResult(result);
        }
        catch (Exception ex)
        {
            AppendResult(new Dictionary<string, object?>
            {
                ["id"] = id,
                ["success"] = false,
                ["error"] = ex.ToString(),
                ["addin"] = AddinInfo(),
                ["timestamp"] = DateTimeOffset.UtcNow.ToString("O")
            });
        }
    }

    private Dictionary<string, object?> ExecuteOperation(
        UIApplication uiapp,
        string operation,
        JsonElement opArgs,
        bool allowModelWrite,
        bool allowSync)
    {
        var uidoc = uiapp.ActiveUIDocument;
        var doc = uidoc?.Document;
        if (operation == "active-document")
        {
            WriteActiveDocument(uiapp);
            return Success("Active document status written.");
        }
        if (operation == "open-model")
        {
            return OpenModel(uiapp, opArgs);
        }
        if (doc == null)
        {
            return Failure("No active Revit document.");
        }

        switch (operation)
        {
            case "export-metadata":
            case "qa-snapshot":
                WriteMetadata(uiapp);
                return Success("Metadata snapshot written.", MetadataPath);
            case "save":
                RequireModelWrite(allowModelWrite, operation);
                doc.Save();
                return Success("Document saved.");
            case "sync":
            case "synchronize-with-central":
                RequireModelWrite(allowModelWrite, operation);
                if (!allowSync)
                {
                    throw new InvalidOperationException("Sync requires allow_sync guard.");
                }
                if (!doc.IsWorkshared)
                {
                    throw new InvalidOperationException("Active document is not workshared.");
                }
                var transactOptions = new TransactWithCentralOptions();
                var syncOptions = new SynchronizeWithCentralOptions();
                syncOptions.Comment = "Hermes supervised synchronization";
                syncOptions.SetRelinquishOptions(new RelinquishOptions(false));
                doc.SynchronizeWithCentral(transactOptions, syncOptions);
                return Success("Document synchronized with central.");
            case "reload-links":
                RequireModelWrite(allowModelWrite, operation);
                return ReloadLinks(doc);
            case "activate-view":
                return ActivateView(uiapp, doc, opArgs);
            case "close-model":
                var saveBeforeClose = GetBool(opArgs, "save_before_close");
                if (saveBeforeClose)
                {
                    RequireModelWrite(allowModelWrite, operation);
                }
                var closed = doc.Close(saveBeforeClose);
                return new Dictionary<string, object?>
                {
                    ["success"] = closed,
                    ["message"] = closed ? "Document closed." : "Document did not close."
                };
            case "modify-model":
            case "set-project-info-parameter":
                RequireModelWrite(allowModelWrite, operation);
                return SetProjectInfoParameter(doc, opArgs);
            case "detach":
            case "upgrade":
                return Failure("Use operation open-model with detach/allow_upgrade arguments so Revit opens the copied model under supervision.");
            default:
                return Failure("Unknown operation: " + operation);
        }
    }

    private Dictionary<string, object?> OpenModel(UIApplication uiapp, JsonElement opArgs)
    {
        var path = GetString(opArgs, "path") ?? GetString(opArgs, "model_path");
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return Failure("Model path missing or not found.");
        }

        var detach = GetBool(opArgs, "detach");
        var openOptions = new OpenOptions();
        if (detach)
        {
            openOptions.DetachFromCentralOption = DetachFromCentralOption.DetachAndPreserveWorksets;
        }

        var modelPath = ModelPathUtils.ConvertUserVisiblePathToModelPath(path);
        var uidoc = uiapp.OpenAndActivateDocument(modelPath, openOptions, false);
        return new Dictionary<string, object?>
        {
            ["success"] = uidoc != null,
            ["message"] = "Model open requested.",
            ["path"] = path,
            ["detach"] = detach
        };
    }

    private Dictionary<string, object?> ReloadLinks(Document doc)
    {
        var results = new List<Dictionary<string, object?>>();
        var linkTypes = new FilteredElementCollector(doc)
            .OfClass(typeof(RevitLinkType))
            .Cast<RevitLinkType>()
            .ToList();

        foreach (var linkType in linkTypes)
        {
            try
            {
                linkType.Reload();
                results.Add(new Dictionary<string, object?>
                {
                    ["name"] = linkType.Name,
                    ["success"] = true
                });
            }
            catch (Exception ex)
            {
                results.Add(new Dictionary<string, object?>
                {
                    ["name"] = linkType.Name,
                    ["success"] = false,
                    ["error"] = ex.Message
                });
            }
        }

        return new Dictionary<string, object?>
        {
            ["success"] = results.All(r => r.TryGetValue("success", out var value) && value is true),
            ["message"] = "Reload links attempted.",
            ["links"] = results
        };
    }

    private Dictionary<string, object?> SetProjectInfoParameter(Document doc, JsonElement opArgs)
    {
        var name = GetString(opArgs, "name");
        var value = GetString(opArgs, "value") ?? "";
        if (string.IsNullOrWhiteSpace(name))
        {
            return Failure("Missing parameter name.");
        }

        using var tx = new Transaction(doc, "Hermes set project information parameter");
        tx.Start();
        var parameter = doc.ProjectInformation.LookupParameter(name);
        if (parameter == null || parameter.IsReadOnly)
        {
            tx.RollBack();
            return Failure("Parameter not found or read-only: " + name);
        }
        var ok = parameter.Set(value);
        tx.Commit();
        return new Dictionary<string, object?>
        {
            ["success"] = ok,
            ["message"] = "Project information parameter updated.",
            ["parameter"] = name
        };
    }

    private Dictionary<string, object?> ActivateView(UIApplication uiapp, Document doc, JsonElement opArgs)
    {
        var uidoc = uiapp.ActiveUIDocument;
        if (uidoc == null)
        {
            return Failure("No active UI document.");
        }

        var view = ResolveView(doc, opArgs);
        if (view == null)
        {
            return Failure("View or sheet not found.");
        }
        if (view.IsTemplate)
        {
            return Failure("View templates cannot be activated.");
        }
        if (view is ViewSheet sheet && sheet.IsPlaceholder)
        {
            return Failure("Placeholder sheets cannot be activated.");
        }

        uidoc.ActiveView = view;
        WriteActiveDocument(uiapp);
        return new Dictionary<string, object?>
        {
            ["success"] = true,
            ["message"] = "Active view changed.",
            ["view"] = ViewSummary(view)
        };
    }

    private View? ResolveView(Document doc, JsonElement opArgs)
    {
        var id = GetLong(opArgs, "id") ?? GetLong(opArgs, "view_id");
        if (id.HasValue)
        {
            return doc.GetElement(NewElementId(id.Value)) as View;
        }

        var sheetNumber = GetString(opArgs, "sheet_number");
        if (!string.IsNullOrWhiteSpace(sheetNumber))
        {
            return new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .FirstOrDefault(s => string.Equals(s.SheetNumber, sheetNumber, StringComparison.OrdinalIgnoreCase));
        }

        var name = GetString(opArgs, "view_name") ?? GetString(opArgs, "name");
        if (!string.IsNullOrWhiteSpace(name))
        {
            return new FilteredElementCollector(doc)
                .OfClass(typeof(View))
                .Cast<View>()
                .Where(v => !v.IsTemplate)
                .FirstOrDefault(v => string.Equals(v.Name, name, StringComparison.OrdinalIgnoreCase));
        }

        return null;
    }

    private Dictionary<string, object?> ViewSummary(View view)
    {
        return new Dictionary<string, object?>
        {
            ["id"] = ElementIdValue(view.Id),
            ["name"] = view.Name,
            ["view_type"] = view.ViewType.ToString(),
            ["sheet_number"] = view is ViewSheet sheet ? sheet.SheetNumber : null
        };
    }

    private void WriteActiveDocument(UIApplication uiapp, bool retry = true)
    {
        var app = uiapp.Application;
        var doc = uiapp.ActiveUIDocument?.Document;
        var payload = new Dictionary<string, object?>
        {
            ["available"] = doc != null,
            ["status"] = doc != null ? "connected" : "no_active_document",
            ["revit_version"] = app.VersionNumber,
            ["addin"] = AddinInfo(),
            ["written_at"] = DateTimeOffset.UtcNow.ToString("O")
        };
        if (doc != null)
        {
            payload["document"] = DocumentInfo(doc, app);
        }
        WriteStatusFiles(ActiveDocumentPath, payload, retry);
    }

    private void WriteMetadata(UIApplication uiapp)
    {
        var doc = uiapp.ActiveUIDocument?.Document;
        if (doc == null)
        {
            throw new InvalidOperationException("No active Revit document.");
        }

        var payload = new Dictionary<string, object?>
        {
            ["label"] = "DRAFT / NOT FOR PERMIT / REQUIRES PE REVIEW",
            ["generated_at"] = DateTimeOffset.UtcNow.ToString("O"),
            ["read_only"] = true,
            ["document"] = DocumentInfo(doc, uiapp.Application),
            ["project_info"] = ProjectInfo(doc),
            ["levels"] = ElementsByCategory(doc, BuiltInCategory.OST_Levels),
            ["grids"] = ElementsByCategory(doc, BuiltInCategory.OST_Grids),
            ["views"] = Views(doc),
            ["sheets"] = Sheets(doc),
            ["titleblocks"] = ElementsByCategory(doc, BuiltInCategory.OST_TitleBlocks),
            ["links"] = Links(doc),
            ["warnings"] = Warnings(doc),
            ["families"] = Families(doc),
            ["types"] = Types(doc)
        };
        WriteJsonAtomic(MetadataPath, payload);
    }

    private Dictionary<string, object?> DocumentInfo(Document doc, Application app)
    {
        return new Dictionary<string, object?>
        {
            ["title"] = doc.Title,
            ["path"] = doc.PathName,
            ["revit_version"] = app.VersionNumber,
            ["worksharing"] = doc.IsWorkshared ? "enabled" : "disabled",
            ["central_path"] = CentralPath(doc),
            ["dirty"] = doc.IsModified,
            ["active_view"] = doc.ActiveView == null ? null : new Dictionary<string, object?>
            {
                ["name"] = doc.ActiveView.Name,
                ["type"] = doc.ActiveView.ViewType.ToString()
            }
        };
    }

    private Dictionary<string, object?> ProjectInfo(Document doc)
    {
        var info = doc.ProjectInformation;
        return new Dictionary<string, object?>
        {
            ["name"] = info.Name,
            ["number"] = info.Number,
            ["client_name"] = info.ClientName,
            ["address"] = info.Address,
            ["status"] = info.Status
        };
    }

    private List<Dictionary<string, object?>> ElementsByCategory(Document doc, BuiltInCategory category)
    {
        return new FilteredElementCollector(doc)
            .OfCategory(category)
            .WhereElementIsNotElementType()
            .Select(BasicElement)
            .ToList();
    }

    private List<Dictionary<string, object?>> Views(Document doc)
    {
        return new FilteredElementCollector(doc)
            .OfClass(typeof(View))
            .Cast<View>()
            .Where(v => !v.IsTemplate)
            .Select(v => new Dictionary<string, object?>
            {
                ["id"] = ElementIdValue(v.Id),
                ["name"] = v.Name,
                ["view_type"] = v.ViewType.ToString(),
                ["template_id"] = ElementIdValue(v.ViewTemplateId)
            })
            .ToList();
    }

    private List<Dictionary<string, object?>> Sheets(Document doc)
    {
        return new FilteredElementCollector(doc)
            .OfClass(typeof(ViewSheet))
            .Cast<ViewSheet>()
            .Select(s => new Dictionary<string, object?>
            {
                ["id"] = ElementIdValue(s.Id),
                ["sheet_number"] = s.SheetNumber,
                ["name"] = s.Name,
                ["is_placeholder"] = s.IsPlaceholder
            })
            .ToList();
    }

    private List<Dictionary<string, object?>> Links(Document doc)
    {
        return new FilteredElementCollector(doc)
            .OfClass(typeof(RevitLinkType))
            .Cast<RevitLinkType>()
            .Select(l => new Dictionary<string, object?>
            {
                ["id"] = ElementIdValue(l.Id),
                ["name"] = l.Name,
                ["status"] = "unknown"
            })
            .ToList();
    }

    private List<Dictionary<string, object?>> Warnings(Document doc)
    {
        return doc.GetWarnings()
            .Select(w => new Dictionary<string, object?>
            {
                ["description"] = w.GetDescriptionText(),
                ["severity"] = w.GetSeverity().ToString(),
                ["failing_element_ids"] = w.GetFailingElements().Select(ElementIdValue).ToList()
            })
            .ToList();
    }

    private List<Dictionary<string, object?>> Families(Document doc)
    {
        return new FilteredElementCollector(doc)
            .OfClass(typeof(Family))
            .Cast<Family>()
            .Select(f => new Dictionary<string, object?>
            {
                ["id"] = ElementIdValue(f.Id),
                ["name"] = f.Name,
                ["category"] = f.FamilyCategory?.Name
            })
            .ToList();
    }

    private List<Dictionary<string, object?>> Types(Document doc)
    {
        return new FilteredElementCollector(doc)
            .WhereElementIsElementType()
            .Select(e => new Dictionary<string, object?>
            {
                ["id"] = ElementIdValue(e.Id),
                ["name"] = e.Name,
                ["category"] = e.Category?.Name
            })
            .ToList();
    }

    private Dictionary<string, object?> BasicElement(Element e)
    {
        return new Dictionary<string, object?>
        {
            ["id"] = ElementIdValue(e.Id),
            ["name"] = e.Name,
            ["category"] = e.Category?.Name
        };
    }

    private static long ElementIdValue(ElementId id)
    {
#if REVIT2022 || REVIT2023
        return id.IntegerValue;
#else
        return id.Value;
#endif
    }

    private static ElementId NewElementId(long value)
    {
#if REVIT2022 || REVIT2023
        return new ElementId((int)value);
#else
        return new ElementId(value);
#endif
    }

    private string? CentralPath(Document doc)
    {
        if (!doc.IsWorkshared)
        {
            return null;
        }
        var modelPath = doc.GetWorksharingCentralModelPath();
        return ModelPathUtils.ConvertModelPathToUserVisiblePath(modelPath);
    }

    private void RequireModelWrite(bool allowModelWrite, string operation)
    {
        if (!allowModelWrite)
        {
            throw new InvalidOperationException(operation + " requires allow_model_write guard.");
        }
    }

    private Dictionary<string, object?> Success(string message, string? path = null)
    {
        var result = new Dictionary<string, object?>
        {
            ["success"] = true,
            ["message"] = message
        };
        if (path != null)
        {
            result["path"] = path;
        }
        return result;
    }

    private Dictionary<string, object?> Failure(string message)
    {
        return new Dictionary<string, object?>
        {
            ["success"] = false,
            ["error"] = message
        };
    }

    private static string? GetString(JsonElement element, string property)
    {
        return element.ValueKind == JsonValueKind.Object
            && element.TryGetProperty(property, out var value)
            && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
    }

    private static DateTime? GetUtcTimestamp(JsonElement element, string property)
    {
        var text = GetString(element, property);
        return text != null && DateTimeOffset.TryParse(
            text,
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
            out var value)
            ? value.UtcDateTime
            : null;
    }

    private static long? GetLong(JsonElement element, string property)
    {
        if (element.ValueKind != JsonValueKind.Object || !element.TryGetProperty(property, out var value))
        {
            return null;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number))
        {
            return number;
        }
        if (value.ValueKind == JsonValueKind.String && long.TryParse(value.GetString(), out var parsed))
        {
            return parsed;
        }
        return null;
    }

    private static bool GetBool(JsonElement element, string property)
    {
        return element.ValueKind == JsonValueKind.Object
            && element.TryGetProperty(property, out var value)
            && value.ValueKind is JsonValueKind.True or JsonValueKind.False
            && value.GetBoolean();
    }

    private void AppendResult(Dictionary<string, object?> payload)
    {
        Directory.CreateDirectory(BridgeDir);
        AppendLineWithRetry(CommandResultsPath, JsonSerializer.Serialize(payload) + Environment.NewLine);
    }

    private void WriteBridgeStatus(string status, string version)
    {
        Directory.CreateDirectory(BridgeDir);
        WriteStatusFiles(AddinStatusPath, new Dictionary<string, object?>
        {
            ["status"] = status,
            ["revit_version"] = version,
            ["addin"] = AddinInfo(),
            ["timestamp"] = DateTimeOffset.UtcNow.ToString("O")
        }, retry: true);
    }

    private void WriteHeartbeat(object? sender, UIApplication? uiapp, bool retry = true)
    {
        Directory.CreateDirectory(BridgeDir);
        WriteStatusFiles(HeartbeatPath, new Dictionary<string, object?>
        {
            ["status"] = "idling",
            ["timestamp"] = DateTimeOffset.UtcNow.ToString("O"),
            ["sender_type"] = sender?.GetType().FullName,
            ["has_ui_application"] = uiapp != null,
            ["has_active_document"] = uiapp?.ActiveUIDocument?.Document != null,
            ["bridge_sweep"] = BridgeSweepInfo(),
            ["addin"] = AddinInfo()
        }, retry);
    }

    // The per-process file must land, and only this Revit writes it. The shared copy is single-attempt best effort,
    // so a tandem session holding it never makes this UI thread wait.
    private void WriteStatusFiles(string sharedPath, object payload, bool retry)
    {
        WriteJsonAtomic(ProcessStatusPath(sharedPath), payload, retry);
        TryWriteStatus(() => WriteJsonAtomic(sharedPath, payload, retry: false));
    }

    private Dictionary<string, object?> AddinInfo()
    {
        var assembly = Assembly.GetExecutingAssembly();
        var assemblyName = assembly.GetName();

        return new Dictionary<string, object?>
        {
            ["name"] = "Hermes Revit Operator",
            ["bridge_protocol_version"] = OperatorProtocolVersion,
            ["source_capability_stamp"] = SourceCapabilityStamp,
            ["target_revit_version"] = TargetRevitVersion,
            ["supported_revit_versions"] = SupportedRevitVersions,
            ["target_framework"] = TargetFrameworkMoniker,
            ["supports_continuous_idling"] = true,
            ["uses_idling_set_raise_without_delay"] = true,
            ["status_write_interval_ms"] = StatusWriteIntervalMilliseconds,
            ["idle_message_wait_ms"] = IdleWaitMilliseconds,
            ["process_id"] = ProcessId,
            ["process_start_utc"] = ProcessStartUtc.ToString("O"),
            ["writes_process_status_files"] = true,
            ["stale_queue_grace_seconds"] = (int)QueueReplayGrace.TotalSeconds,
            ["loaded_at_utc"] = _loadedAtUtc.ToString("O"),
            ["session_id"] = _sessionId,
            ["assembly_name"] = assemblyName.Name,
            ["assembly_version"] = assemblyName.Version?.ToString(),
            ["assembly_path"] = assembly.Location,
            ["assembly_last_write_utc"] = LoadedAssemblyLastWriteUtc,
            ["assembly_length"] = LoadedAssemblyLength,
            ["capabilities"] = new[]
            {
                "active-document",
                "export-metadata",
                "qa-snapshot",
                "open-model",
                "activate-view",
                "guarded-model-write-operations"
            }
        };
    }

    private Dictionary<string, object?> BridgeSweepInfo()
    {
        var ticks = Interlocked.Read(ref _lastSweepTicksUtc);
        return new Dictionary<string, object?>
        {
            ["last_run_utc"] = ticks == 0 ? null : new DateTime(ticks, DateTimeKind.Utc).ToString("O"),
            ["deleted_files"] = Volatile.Read(ref _lastSweepDeletedFiles),
            ["deleted_files_total"] = Volatile.Read(ref _sweepDeletedFilesTotal)
        };
    }

    // Runs on a thread-pool thread, never on Revit's UI thread, and must not throw.
    private void SweepBridgeFolder()
    {
        if (Interlocked.Exchange(ref _sweepRunning, 1) == 1)
        {
            return;
        }
        try
        {
            var bridge = new DirectoryInfo(BridgeDir);
            if (!bridge.Exists)
            {
                return;
            }
            var staleBeforeUtc = DateTime.UtcNow - StaleBridgeFileAge;
            var deleted = 0;
            foreach (var file in bridge.EnumerateFiles())
            {
                try
                {
                    if (file.LastWriteTimeUtc < staleBeforeUtc
                        && (IsLeftoverTempFile(file.Name) || IsExitedProcessStatusFile(file))
                        && TryDelete(file.FullName))
                    {
                        deleted++;
                    }
                }
                catch (Exception)
                {
                }
            }
            Volatile.Write(ref _lastSweepDeletedFiles, deleted);
            Interlocked.Add(ref _sweepDeletedFilesTotal, deleted);
            Interlocked.Exchange(ref _lastSweepTicksUtc, DateTime.UtcNow.Ticks);
        }
        catch (Exception)
        {
        }
        finally
        {
            Interlocked.Exchange(ref _sweepRunning, 0);
        }
    }

    // "<name>~RF<hex>.TMP" files are File.Replace backups that older builds left when another process held the
    // target; "<name>.<guid|pid>.tmp" files are temps of writes that failed before their rename.
    private static bool IsLeftoverTempFile(string name)
    {
        return name.EndsWith(".tmp", StringComparison.OrdinalIgnoreCase)
            && BridgeTempFilePrefixes.Any(prefix => name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase));
    }

    private static bool IsExitedProcessStatusFile(FileInfo file)
    {
        var pid = ProcessIdFromStatusFileName(file.Name);
        if (pid == null || pid.Value == ProcessId)
        {
            return false;
        }
        try
        {
            using var process = System.Diagnostics.Process.GetProcessById(pid.Value);
            // A reused PID belongs to a process that started after the status file was last written.
            return !string.Equals(process.ProcessName, "Revit", StringComparison.OrdinalIgnoreCase)
                || process.StartTime.ToUniversalTime() > file.LastWriteTimeUtc;
        }
        catch (ArgumentException)
        {
            return true;
        }
        catch (InvalidOperationException)
        {
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }

    private static int? ProcessIdFromStatusFileName(string name)
    {
        const string extension = ".json";
        foreach (var stem in ProcessStatusFileStems)
        {
            var prefix = stem + ".";
            if (name.Length > prefix.Length + extension.Length
                && name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)
                && name.EndsWith(extension, StringComparison.OrdinalIgnoreCase)
                && int.TryParse(
                    name.Substring(prefix.Length, name.Length - prefix.Length - extension.Length),
                    NumberStyles.None,
                    CultureInfo.InvariantCulture,
                    out var pid))
            {
                return pid;
            }
        }
        return null;
    }

    // Writes a temp file and renames it over the target. File.Replace is not used: when another process held the
    // target it left "<name>~RF<hex>.TMP" backups behind, ~45k of them in the shared bridge folder. The temp name is
    // per process, so a temp that a failed write leaves is overwritten by the next write instead of accumulating.
    private static void WriteJsonAtomic(string path, object payload, bool retry = true)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path) ?? ".");
        var temp = path + "." + ProcessId + ".tmp";
        var json = JsonSerializer.Serialize(payload, IndentedJson);
        WriteAllTextShared(temp, json, retry);
        try
        {
            RunFileOperation(() => MoveReplacing(temp, path), retry);
        }
        finally
        {
            TryDelete(temp);
        }
    }

    private static void MoveReplacing(string source, string destination)
    {
#if NET
        File.Move(source, destination, true);
#else
        if (!MoveFileEx(source, destination, MoveFileReplaceExisting))
        {
            throw new IOException("Could not replace " + destination + ".", Marshal.GetHRForLastWin32Error());
        }
#endif
    }

#if !NET
    private const uint MoveFileReplaceExisting = 0x1;

    [DllImport("kernel32.dll", EntryPoint = "MoveFileExW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool MoveFileEx(string existingFileName, string newFileName, uint flags);
#endif

    private static void WriteAllTextShared(string path, string text, bool retry = true)
    {
        RunFileOperation(() =>
        {
            using var stream = new FileStream(
                path,
                FileMode.Create,
                FileAccess.Write,
                FileShare.ReadWrite | FileShare.Delete);
            using var writer = new StreamWriter(stream);
            writer.Write(text);
        }, retry);
    }

    private static string ReadAllTextShared(string path)
    {
        using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete);
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }

    private static void RunFileOperation(Action action, bool retry)
    {
        if (retry)
        {
            RetryFileOperation(action);
        }
        else
        {
            action();
        }
    }

    private static void AppendLineWithRetry(string path, string line)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path) ?? ".");
        RetryFileOperation(() =>
        {
            using var stream = new FileStream(
                path,
                FileMode.Append,
                FileAccess.Write,
                FileShare.ReadWrite | FileShare.Delete);
            using var writer = new StreamWriter(stream);
            writer.Write(line);
        });
    }

    private static void RetryFileOperation(Action action)
    {
        var delays = new[] { 25, 50, 100, 200, 400, 800 };
        for (var attempt = 0; attempt <= delays.Length; attempt++)
        {
            try
            {
                action();
                return;
            }
            catch (IOException) when (attempt < delays.Length)
            {
                Thread.Sleep(delays[attempt]);
            }
            catch (UnauthorizedAccessException) when (attempt < delays.Length)
            {
                Thread.Sleep(delays[attempt]);
            }
        }
    }

    private static bool TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
                return true;
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
        return false;
    }

    private static string ResolveSandbox()
    {
        var configured = Environment.GetEnvironmentVariable("HERMES_REVIT_OPERATOR_SANDBOX");
        if (!string.IsNullOrWhiteSpace(configured))
        {
            return configured;
        }
        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return Path.Combine(
            userProfile,
            "IdeaProjects",
            "Tools",
            "_Hermes_WorkingCopies",
            "24522_St_John_XXIII_Youth_Pavilion",
            "_AI_Hermes_Sandbox_DO_NOT_USE_FOR_PERMIT");
    }
}
