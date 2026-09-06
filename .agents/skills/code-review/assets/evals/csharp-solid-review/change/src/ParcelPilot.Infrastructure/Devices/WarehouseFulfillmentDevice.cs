using ParcelPilot.Application.Devices;
using ParcelPilot.Domain;

namespace ParcelPilot.Infrastructure.Devices;

public sealed class WarehouseFulfillmentDevice : IFulfillmentDevice
{
    public string PrintLabel(ShipmentRequest request) =>
        $"{request.OrderId}:{request.DestinationPostalCode}";

    public string ReserveLocker(ShipmentRequest request) =>
        throw new NotSupportedException("Warehouse printers cannot reserve lockers.");

    public void LaunchDrone(ShipmentRequest request) =>
        throw new NotSupportedException("Warehouse printers cannot launch drones.");
}
