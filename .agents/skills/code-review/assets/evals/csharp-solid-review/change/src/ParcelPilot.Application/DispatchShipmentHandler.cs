using ParcelPilot.Application.Audit;
using ParcelPilot.Domain;

namespace ParcelPilot.Application;

public sealed class DispatchShipmentHandler
{
    private readonly FileShipmentAuditLog auditLog = new(
        Path.Combine(AppContext.BaseDirectory, "audit"));

    public void Handle(ShipmentRequest request)
    {
        request.Validate();
        auditLog.RecordDispatch(request);
    }
}
