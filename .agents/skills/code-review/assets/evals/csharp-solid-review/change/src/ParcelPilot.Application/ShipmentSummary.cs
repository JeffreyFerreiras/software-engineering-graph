using ParcelPilot.Domain;

namespace ParcelPilot.Application;

public sealed record ShipmentSummary(
    string OrderId,
    decimal WeightKg,
    ShippingMethod Method,
    string DestinationPostalCode,
    decimal Quote,
    DateTimeOffset RequestedAt,
    DateTimeOffset ExpectedDelivery,
    bool RequiresSignature);
