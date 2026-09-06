using ParcelPilot.Domain;

namespace ParcelPilot.Application.Devices;

public interface ILabelPrinter
{
    string PrintLabel(ShipmentRequest request);
}
