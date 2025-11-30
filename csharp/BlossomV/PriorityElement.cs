namespace BlossomV;

/// <summary>
/// Element used in priority queue for Dijkstra's algorithm
/// Translated from Rust struct PriorityElement
/// </summary>
public readonly struct PriorityElement : IComparable<PriorityElement>
{
    public readonly int Weight;
    public readonly uint Previous;

    public PriorityElement(int weight, uint previous)
    {
        Weight = weight;
        Previous = previous;
    }

    public int CompareTo(PriorityElement other)
    {
        // For min-heap behavior in priority queue
        // Lower weight has higher priority
        return Weight.CompareTo(other.Weight);
    }

    public override bool Equals(object? obj)
    {
        return obj is PriorityElement other && Weight == other.Weight;
    }

    public override int GetHashCode()
    {
        return Weight.GetHashCode();
    }
}
