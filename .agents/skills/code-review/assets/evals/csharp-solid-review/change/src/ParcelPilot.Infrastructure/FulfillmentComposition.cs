using ParcelPilot.Domain;
using ParcelPilot.Infrastructure.Rates;

namespace ParcelPilot.Infrastructure;

public static class FulfillmentComposition
{
    public static IReadOnlyList<RateCalculator> CreateRateCalculators() =>
        [
            new StandardRateCalculator(),
            new ExpressRateCalculator(),
            new OvernightRateCalculator(),
            new DroneRateCalculator(),
            new LocalPickupRateCalculator(),
        ];
}
