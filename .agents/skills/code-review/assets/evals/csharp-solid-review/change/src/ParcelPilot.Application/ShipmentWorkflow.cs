using System.Globalization;
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

    public ShipmentSummary BuildSummary(
        ShipmentRequest request,
        RateCalculator calculator,
        DateTimeOffset requestedAt)
    {
        var quote = CalculateQuote(request, calculator);
        return new ShipmentSummary(
            request.OrderId,
            request.WeightKg,
            request.Method,
            request.DestinationPostalCode,
            quote,
            requestedAt,
            requestedAt + ShippingPolicy.GetDeliveryWindow(request.Method),
            request.WeightKg >= 10m);
    }

    public string FormatInvoiceCsv(ShipmentSummary summary) =>
        string.Join(
            ",",
            summary.OrderId,
            summary.Method,
            summary.WeightKg.ToString(CultureInfo.InvariantCulture),
            summary.Quote.ToString("0.00", CultureInfo.InvariantCulture));

    public string BuildDelayEmail(
        ShipmentSummary summary,
        TimeSpan delay) =>
        $"Order {summary.OrderId} is delayed by {delay.TotalHours:0} hours. " +
        $"The revised delivery time is {summary.ExpectedDelivery + delay:O}.";
}
