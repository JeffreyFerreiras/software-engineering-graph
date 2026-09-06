using ParcelPilot.Application.Audit;
using ParcelPilot.Domain;

namespace ParcelPilot.Infrastructure.Audit;

public sealed class InMemoryShipmentAuditLog : IShipmentAuditLog
{
    public List<string> DispatchedOrderIds { get; } = [];

    public void RecordDispatch(ShipmentRequest request) =>
        DispatchedOrderIds.Add(request.OrderId);
}
