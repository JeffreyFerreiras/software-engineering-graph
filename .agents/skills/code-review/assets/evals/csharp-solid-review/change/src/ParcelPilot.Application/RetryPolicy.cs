namespace ParcelPilot.Application;

public enum RetryReason
{
    Transient,
    RateLimited,
    Permanent,
}
public static class RetryPolicy
{
    public static TimeSpan GetDelay(RetryReason reason) =>
        reason switch
        {
            RetryReason.Transient => TimeSpan.FromSeconds(2),
            RetryReason.RateLimited => TimeSpan.FromSeconds(30),
            RetryReason.Permanent => TimeSpan.Zero,
            _ => throw new ArgumentOutOfRangeException(nameof(reason)),
        };
}
