using ParcelPilot.Domain;

namespace ParcelPilot.Application;

public static class ShippingPolicy
{
    public static decimal GetSurcharge(ShipmentRequest request) =>
        request.Method switch
        {
            ShippingMethod.Standard => 0m,
            ShippingMethod.Express => 12m,
            ShippingMethod.Overnight => 25m,
            ShippingMethod.Drone => 18m,
            ShippingMethod.LocalPickup => 2m,
            _ => throw new ArgumentOutOfRangeException(nameof(request)),
        };

    public static TimeSpan GetDeliveryWindow(ShippingMethod method) =>
        method switch
        {
            ShippingMethod.Standard => TimeSpan.FromDays(5),
            ShippingMethod.Express => TimeSpan.FromDays(2),
            ShippingMethod.Overnight => TimeSpan.FromDays(1),
            ShippingMethod.Drone => TimeSpan.FromHours(4),
            ShippingMethod.LocalPickup => TimeSpan.FromHours(2),
            _ => throw new ArgumentOutOfRangeException(nameof(method)),
        };

    public static string GetTrackingPrefix(ShippingMethod method) =>
        method switch
        {
            ShippingMethod.Standard => "STD",
            ShippingMethod.Express => "EXP",
            ShippingMethod.Overnight => "OVN",
            ShippingMethod.Drone => "DRN",
            _ => throw new ArgumentOutOfRangeException(nameof(method)),
        };
}
