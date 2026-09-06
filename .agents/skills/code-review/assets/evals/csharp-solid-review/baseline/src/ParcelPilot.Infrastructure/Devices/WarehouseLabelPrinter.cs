using ParcelPilot.Application.Devices;
using ParcelPilot.Domain;

namespace ParcelPilot.Infrastructure.Devices;

public sealed class WarehouseLabelPrinter : ILabelPrinter
{
    public string PrintLabel(ShipmentRequest request) =>
        $"{request.OrderId}:{request.DestinationPostalCode}";
}
