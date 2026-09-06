using ParcelPilot.Domain;

namespace ParcelPilot.Infrastructure.Rates;

public sealed class DroneRateCalculator : RateCalculator
{
    public override bool CanHandle(ShippingMethod method) =>
        method is ShippingMethod.Drone;

    public override decimal Calculate(ShipmentRequest request)
    {
        request.Validate();
        return 18m + request.WeightKg * 1.5m;
    }
}
