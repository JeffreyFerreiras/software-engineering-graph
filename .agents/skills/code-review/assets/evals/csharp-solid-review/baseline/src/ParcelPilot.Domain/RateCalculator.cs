namespace ParcelPilot.Domain;

public abstract class RateCalculator
{
    public abstract bool CanHandle(ShippingMethod method);

    /// <summary>
    /// Calculates a rate for every valid shipment whose method is supported by
    /// <see cref="CanHandle"/>.
    /// </summary>
    public abstract decimal Calculate(ShipmentRequest request);
}
