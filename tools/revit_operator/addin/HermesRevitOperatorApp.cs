using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
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

    private readonly HashSet<string> _processedCommandIds = new();
    private readonly string _sessionId = Guid.NewGuid().ToString("N");
    private readonly DateTimeOffset _loadedAtUtc = DateTimeOffset.UtcNow;
    private UIApplication? _uiapp;
    private string _sandbox = "";

    public Result OnStartup(UIControlledApplication application)
    {
        _sandbox = ResolveSandbox();
        Directory.CreateDirectory(BridgeDir);
        application.Idling += OnIdling;
        WriteBridgeStatus("started", application.ControlledApplication.VersionNumber);
        return Result.Succeeded;
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        application.Idling -= OnIdling;
        _uiapp = null;
        WriteBridgeStatus("stopped", application.ControlledApplication.VersionNumber);
        return Result.Succeeded;
    }

    private string BridgeDir => Path.Combine(_sandbox, "bridge");
    private string CommandQueuePath => Path.Combine(BridgeDir, "command_queue.jsonl");
    private string CommandResultsPath => Path.Combine(BridgeDir, "command_results.jsonl");
    private string ActiveDocumentPath => Path.Combine(BridgeDir, "active_document.json");
    private string MetadataPath => Path.Combine(BridgeDir, "metadata_snapshot.json");
    private string HeartbeatPath => Path.Combine(BridgeDir, "addin_heartbeat.json");

    private void OnIdling(object? sender, IdlingEventArgs args)
    {
        args.SetRaiseWithoutDelay();
        if (sender is UIApplication currentUiapp)
        {
            _uiapp = currentUiapp;
        }
        var uiapp = _uiapp;
        WriteHeartbeat(sender, uiapp);
        if (uiapp == null)
        {
            AppendResult(new Dictionary<string, object?>
            {
                ["id"] = "idling-no-uiapp-" + DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["success"] = false,
                ["error"] = "Revit Idling event did not provide a UIApplication and no fallback UIApplication is available.",
                ["sender_type"] = sender?.GetType().FullName,
                ["timestamp"] = DateTimeOffset.UtcNow.ToString("O")
            });
            return;
        }

        try
        {
            Directory.CreateDirectory(BridgeDir);
            WriteActiveDocument(uiapp);
            ProcessQueuedCommands(uiapp);
        }
        catch (Exception ex)
        {
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

    private void ProcessQueuedCommands(UIApplication uiapp)
    {
        if (!File.Exists(CommandQueuePath))
        {
            return;
        }

        foreach (var line in File.ReadLines(CommandQueuePath).ToList())
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            using var doc = JsonDocument.Parse(line);
            var root = doc.RootElement;
            var id = GetString(root, "id") ?? Guid.NewGuid().ToString("N");
            if (_processedCommandIds.Contains(id))
            {
                continue;
            }
            _processedCommandIds.Add(id);

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
            return doc.GetElement(new ElementId(id.Value)) as View;
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
            ["id"] = view.Id.Value,
            ["name"] = view.Name,
            ["view_type"] = view.ViewType.ToString(),
            ["sheet_number"] = view is ViewSheet sheet ? sheet.SheetNumber : null
        };
    }

    private void WriteActiveDocument(UIApplication uiapp)
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
        WriteJsonAtomic(ActiveDocumentPath, payload);
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
                ["id"] = v.Id.Value,
                ["name"] = v.Name,
                ["view_type"] = v.ViewType.ToString(),
                ["template_id"] = v.ViewTemplateId.Value
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
                ["id"] = s.Id.Value,
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
                ["id"] = l.Id.Value,
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
                ["failing_element_ids"] = w.GetFailingElements().Select(id => id.Value).ToList()
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
                ["id"] = f.Id.Value,
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
                ["id"] = e.Id.Value,
                ["name"] = e.Name,
                ["category"] = e.Category?.Name
            })
            .ToList();
    }

    private Dictionary<string, object?> BasicElement(Element e)
    {
        return new Dictionary<string, object?>
        {
            ["id"] = e.Id.Value,
            ["name"] = e.Name,
            ["category"] = e.Category?.Name
        };
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
        WriteJsonAtomic(Path.Combine(BridgeDir, "addin_status.json"), new Dictionary<string, object?>
        {
            ["status"] = status,
            ["revit_version"] = version,
            ["addin"] = AddinInfo(),
            ["timestamp"] = DateTimeOffset.UtcNow.ToString("O")
        });
    }

    private void WriteHeartbeat(object? sender, UIApplication? uiapp)
    {
        Directory.CreateDirectory(BridgeDir);
        WriteJsonAtomic(HeartbeatPath, new Dictionary<string, object?>
        {
            ["status"] = "idling",
            ["timestamp"] = DateTimeOffset.UtcNow.ToString("O"),
            ["sender_type"] = sender?.GetType().FullName,
            ["has_ui_application"] = uiapp != null,
            ["has_active_document"] = uiapp?.ActiveUIDocument?.Document != null,
            ["addin"] = AddinInfo()
        });
    }

    private Dictionary<string, object?> AddinInfo()
    {
        var assembly = Assembly.GetExecutingAssembly();
        var assemblyName = assembly.GetName();
        var assemblyPath = assembly.Location;
        var assemblyFile = string.IsNullOrWhiteSpace(assemblyPath) || !File.Exists(assemblyPath)
            ? null
            : new FileInfo(assemblyPath);

        return new Dictionary<string, object?>
        {
            ["name"] = "Hermes Revit Operator",
            ["bridge_protocol_version"] = OperatorProtocolVersion,
            ["source_capability_stamp"] = SourceCapabilityStamp,
            ["supports_continuous_idling"] = true,
            ["uses_idling_set_raise_without_delay"] = true,
            ["loaded_at_utc"] = _loadedAtUtc.ToString("O"),
            ["session_id"] = _sessionId,
            ["assembly_name"] = assemblyName.Name,
            ["assembly_version"] = assemblyName.Version?.ToString(),
            ["assembly_path"] = assemblyPath,
            ["assembly_last_write_utc"] = assemblyFile == null ? null : assemblyFile.LastWriteTimeUtc.ToString("O"),
            ["assembly_length"] = assemblyFile?.Length,
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

    private static void WriteJsonAtomic(string path, object payload)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path) ?? ".");
        var temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions
        {
            WriteIndented = true
        });
        WriteAllTextShared(temp, json);
        try
        {
            RetryFileOperation(() =>
            {
                if (File.Exists(path))
                {
                    File.Replace(temp, path, null, true);
                }
                else
                {
                    File.Move(temp, path);
                }
            });
        }
        finally
        {
            TryDelete(temp);
        }
    }

    private static void WriteAllTextShared(string path, string text)
    {
        RetryFileOperation(() =>
        {
            using var stream = new FileStream(
                path,
                FileMode.Create,
                FileAccess.Write,
                FileShare.ReadWrite | FileShare.Delete);
            using var writer = new StreamWriter(stream);
            writer.Write(text);
        });
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

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
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
