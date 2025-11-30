namespace BlossomV;

/// <summary>
/// Tracks edge weight modifications caused by erasures or correlations
/// Translated from Rust struct EdgeWeightModifier
/// </summary>
public class EdgeWeightModifier
{
    /// <summary>
    /// Edges with changed weights caused by the erasure or X/Z correlation
    /// Each tuple contains (edge_index, original_weight)
    /// </summary>
    private readonly List<(uint, int)> _modified;

    public EdgeWeightModifier()
    {
        _modified = [];
    }

    /// <summary>
    /// Record the modified edge
    /// </summary>
    public void PushModifiedEdge(uint edgeIndex, int originalWeight) => _modified.Add((edgeIndex, originalWeight));

    /// <summary>
    /// Check if some edges are not recovered
    /// </summary>
    public bool HasModifiedEdges() => _modified.Count > 0;

    /// <summary>
    /// Retrieve the last modified edge
    /// </summary>
    /// <exception cref="InvalidOperationException">Thrown when no more modified edges exist</exception>
    public (uint EdgeIndex, int OriginalWeight) PopModifiedEdge()
    {
        if (_modified.Count == 0)
        {
            throw new InvalidOperationException("No more modified edges, please check HasModifiedEdges before calling this method");
        }

        var lastIndex = _modified.Count - 1;
        var result = _modified[lastIndex];
        _modified.RemoveAt(lastIndex);
        return result;
    }
}
