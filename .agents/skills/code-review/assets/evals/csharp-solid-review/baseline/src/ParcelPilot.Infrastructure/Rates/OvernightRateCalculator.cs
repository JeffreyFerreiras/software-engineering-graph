using ParcelPilot.Domain;

namespace ParcelPilot.Infrastructure.Rates;

public sealed class OvernightRateCalculator : RateCalculator
{
    public override bool CanHandle(ShippingMethod method) =>
        method is ShippingMethod.Overnight;

    public override decimal Calculate(ShipmentRequest request)
    {
        request.Validate();
        return 25m + request.WeightKg * 1.25m;
    }
}
