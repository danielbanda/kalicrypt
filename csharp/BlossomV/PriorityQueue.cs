using System.Collections.Generic;

namespace BlossomV;

/// <summary>
/// Simple priority queue implementation for Dijkstra's algorithm
/// Using SortedDictionary for simplicity (not the most efficient, but works)
/// </summary>
public class PriorityQueue<TKey, TPriority> where TPriority : IComparable<TPriority> where TKey : notnull
{
    private readonly SortedSet<(TPriority Priority, TKey Key)> _heap;
    private readonly Dictionary<TKey, TPriority> _priorities;

    public PriorityQueue()
    {
        _heap = new SortedSet<(TPriority, TKey)>(Comparer<(TPriority Priority, TKey Key)>.Create((a, b) =>
        {
            var cmp = a.Priority.CompareTo(b.Priority);
            if (cmp != 0)
            {
                return cmp;
            }

            return Comparer<TKey>.Default.Compare(a.Key, b.Key);
        }));
        _priorities = [];
    }

    public void Push(TKey key, TPriority priority)
    {
        if (_priorities.ContainsKey(key))
        {
            // Remove old entry
            _heap.Remove((_priorities[key], key));
        }
        _heap.Add((priority, key));
        _priorities[key] = priority;
    }

    public (TKey Key, TPriority Priority) Pop()
    {
        if (_heap.Count == 0)
            throw new InvalidOperationException("Queue is empty");

        var min = _heap.Min;
        _heap.Remove(min);
        _priorities.Remove(min.Key);
        return (min.Key, min.Priority);
    }

    public TPriority? GetPriority(TKey key)
    {
        return _priorities.GetValueOrDefault(key);
    }

    public bool ContainsKey(TKey key)
    {
        return _priorities.ContainsKey(key);
    }

    public void ChangePriority(TKey key, TPriority newPriority)
    {
        if (_priorities.ContainsKey(key))
        {
            _heap.Remove((_priorities[key], key));
        }
        _heap.Add((newPriority, key));
        _priorities[key] = newPriority;
    }

    public bool IsEmpty => _heap.Count == 0;

    public int Count => _heap.Count;
}
