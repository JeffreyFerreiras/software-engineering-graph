using ParcelPilot.Domain;

namespace ParcelPilot.Application;

public sealed class ShipmentWorkflow
{
    public decimal CalculateQuote(
        ShipmentRequest request,
        RateCalculator calculator)
    {
        request.Validate();
        if (!calculator.CanHandle(request.Method))
        {
            throw new ArgumentException(
                "The calculator does not support the requested shipping method.",
                nameof(calculator));
        }

        return calculator.Calculate(request) + ShippingPolicy.GetSurcharge(request);
    }
}
