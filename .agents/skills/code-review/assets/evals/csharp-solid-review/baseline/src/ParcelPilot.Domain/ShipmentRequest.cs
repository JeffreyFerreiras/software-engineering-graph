namespace ParcelPilot.Domain;

public sealed record ShipmentRequest(
    string OrderId,
    decimal WeightKg,
    ShippingMethod Method,
    string DestinationPostalCode)
{
    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(OrderId);
        ArgumentException.ThrowIfNullOrWhiteSpace(DestinationPostalCode);
        if (WeightKg <= 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(WeightKg),
                "Shipment weight must be positive.");
        }
    }
}
