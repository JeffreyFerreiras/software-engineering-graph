using ParcelPilot.Domain;

namespace ParcelPilot.Infrastructure.Rates;

public sealed class StandardRateCalculator : RateCalculator
{
    public override bool CanHandle(ShippingMethod method) =>
        method is ShippingMethod.Standard;

    public override decimal Calculate(ShipmentRequest request)
    {
        request.Validate();
        return 5m + request.WeightKg * 0.5m;
    }
}
