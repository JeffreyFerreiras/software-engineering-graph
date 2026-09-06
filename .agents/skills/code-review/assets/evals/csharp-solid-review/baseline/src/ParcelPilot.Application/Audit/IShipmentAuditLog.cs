using ParcelPilot.Domain;

namespace ParcelPilot.Application.Audit;

public interface IShipmentAuditLog
{
    void RecordDispatch(ShipmentRequest request);
}
