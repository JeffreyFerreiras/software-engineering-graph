using ParcelPilot.Domain;

namespace ParcelPilot.Application.Audit;

public sealed class FileShipmentAuditLog(string auditDirectory)
{
    public void RecordDispatch(ShipmentRequest request)
    {
        Directory.CreateDirectory(auditDirectory);
        File.AppendAllText(
            Path.Combine(auditDirectory, "dispatches.log"),
            $"{DateTimeOffset.UtcNow:O}|{request.OrderId}{Environment.NewLine}");
    }
}
