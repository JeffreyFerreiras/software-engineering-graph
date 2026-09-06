using ParcelPilot.Application;
using ParcelPilot.Application.Devices;
using ParcelPilot.Domain;
using ParcelPilot.Infrastructure;
using ParcelPilot.Infrastructure.Devices;

var failures = new List<string>();
var calculators = FulfillmentComposition.CreateRateCalculators();

foreach (var method in Enum.GetValues<ShippingMethod>())
{
    var calculator = calculators.SingleOrDefault(candidate => candidate.CanHandle(method));
    if (calculator is null)
    {
        failures.Add($"No rate calculator is registered for {method}.");
        continue;
    }

    var request = new ShipmentRequest("ORDER-42", 25m, method, "10001");
    try
    {
        _ = ShippingPolicy.GetSurcharge(request);
        _ = ShippingPolicy.GetDeliveryWindow(method);
        _ = ShippingPolicy.GetTrackingPrefix(method);
    }
    catch (Exception exception)
    {
        failures.Add($"ShippingPolicy rejected {method}: {exception.Message}");
    }

    try
    {
        _ = calculator.Calculate(request);
    }
    catch (Exception exception)
    {
        failures.Add(
            $"{calculator.GetType().Name} rejected a valid shipment: " +
            exception.Message);
    }
}

var labelService = new LabelService(new WarehouseLabelPrinter());
var label = labelService.CreateLabel(
    new ShipmentRequest("ORDER-42", 2m, ShippingMethod.Standard, "10001"));
if (label != "ORDER-42:10001")
{
    failures.Add("Warehouse label formatting changed.");
}

foreach (var failure in failures)
{
    Console.Error.WriteLine(failure);
}

return failures.Count == 0 ? 0 : 1;
