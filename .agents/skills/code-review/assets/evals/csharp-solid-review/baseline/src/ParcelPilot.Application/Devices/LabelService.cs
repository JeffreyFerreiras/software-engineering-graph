using ParcelPilot.Domain;

namespace ParcelPilot.Application.Devices;

public sealed class LabelService(ILabelPrinter printer)
{
    public string CreateLabel(ShipmentRequest request)
    {
        request.Validate();
        return printer.PrintLabel(request);
    }
}
