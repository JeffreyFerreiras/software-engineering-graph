using ParcelPilot.Domain;

namespace ParcelPilot.Application.Devices;

public interface IFulfillmentDevice
{
    string PrintLabel(ShipmentRequest request);

    string ReserveLocker(ShipmentRequest request);

    void LaunchDrone(ShipmentRequest request);
}
