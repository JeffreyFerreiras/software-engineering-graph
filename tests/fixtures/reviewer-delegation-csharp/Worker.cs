using System.Threading.Tasks;

namespace DelegationFixture;

public sealed class Worker
{
    private readonly Cache _cache;

    public Worker(Cache cache) => _cache = cache;

    public Task RunAsync(string key) => Task.WhenAll(
        Task.Run(() => _cache.Increment(key)),
        Task.Run(() => _cache.Increment(key)));
}
