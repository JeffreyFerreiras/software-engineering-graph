using ParcelPilot.Domain;

namespace ParcelPilot.Application.Devices;

public sealed class LabelService(IFulfillmentDevice device)
{
    public string CreateLabel(ShipmentRequest request)
    {
        request.Validate();
        return device.PrintLabel(request);
    }
}
