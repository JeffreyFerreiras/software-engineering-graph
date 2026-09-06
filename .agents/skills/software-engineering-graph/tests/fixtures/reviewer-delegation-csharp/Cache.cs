using System.Collections.Generic;

namespace DelegationFixture;

public sealed class Cache
{
    private readonly Dictionary<string, int> _values = new();

    public void Increment(string key)
    {
        _values[key] = _values.GetValueOrDefault(key) + 1;
    }

    public int Read(string key) => _values.GetValueOrDefault(key);
}
