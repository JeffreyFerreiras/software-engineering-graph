using ParcelPilot.Domain;

namespace ParcelPilot.Infrastructure.Rates;

public sealed class LocalPickupRateCalculator : RateCalculator
{
    public override bool CanHandle(ShippingMethod method) =>
        method is ShippingMethod.LocalPickup;

    public override decimal Calculate(ShipmentRequest request)
    {
        request.Validate();
        if (request.WeightKg > 20m)
        {
            throw new NotSupportedException(
                "Local pickup only supports shipments up to 20 kilograms.");
        }

        return 2m;
    }
}
