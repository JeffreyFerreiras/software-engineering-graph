namespace DelegationFixture.Tests;

public sealed class WorkerTests
{
    // Intentionally incomplete: no parallel update assertion exercises Worker.RunAsync.
    public void Cache_starts_empty()
    {
        var cache = new Cache();
        _ = cache.Read("shared");
    }
}
