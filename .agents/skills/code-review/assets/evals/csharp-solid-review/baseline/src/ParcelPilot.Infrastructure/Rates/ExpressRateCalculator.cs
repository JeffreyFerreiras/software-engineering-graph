using ParcelPilot.Domain;

namespace ParcelPilot.Infrastructure.Rates;

public sealed class ExpressRateCalculator : RateCalculator
{
    public override bool CanHandle(ShippingMethod method) =>
        method is ShippingMethod.Express;

    public override decimal Calculate(ShipmentRequest request)
    {
        request.Validate();
        return 12m + request.WeightKg * 0.85m;
    }
}
