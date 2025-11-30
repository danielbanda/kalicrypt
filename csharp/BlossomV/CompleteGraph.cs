using System.Diagnostics;

namespace BlossomV;

/// <summary>
/// Vertex in the complete graph
/// Translated from Rust struct CompleteGraphVertex
/// </summary>
public class CompleteGraphVertex
{
    /// <summary>
    /// All skeleton graph edges connected to this vertex
    /// Key: peer vertex index, Value: edge weight
    /// </summary>
    public SortedDictionary<uint, int> Edges { get; set; }

    /// <summary>
    /// Timestamp for Dijkstra's algorithm
    /// </summary>
    public ulong Timestamp { get; set; }

    public CompleteGraphVertex()
    {
        Edges = [];
        Timestamp = 0;
    }
}

/// <summary>
/// Build complete graph out of skeleton graph using Dijkstra's algorithm
/// Translated from Rust struct CompleteGraph
/// </summary>
public class CompleteGraph
{
    /// <summary>
    /// Number of vertices
    /// </summary>
    public uint VertexNum { get; private set; }

    /// <summary>
    /// The vertices to run Dijkstra's algorithm
    /// </summary>
    public List<CompleteGraphVertex> Vertices { get; private set; }

    /// <summary>
    /// Timestamp to invalidate all vertices without iterating them
    /// </summary>
    private ulong _activeTimestamp;

    /// <summary>
    /// Remember the edges that's modified by erasures
    /// </summary>
    public EdgeWeightModifier EdgeModifier { get; private set; }

    /// <summary>
    /// Original edge weights
    /// </summary>
    public List<(uint, uint, int)> WeightedEdges { get; private set; }

    /// <summary>
    /// Create complete graph given skeleton graph
    /// </summary>
    public CompleteGraph(uint vertexNum, List<(uint, uint, int)> weightedEdges)
    {
        VertexNum = vertexNum;
        Vertices = new List<CompleteGraphVertex>((int)vertexNum);

        for (var i = 0; i < vertexNum; i++)
        {
            Vertices.Add(new CompleteGraphVertex());
        }

        foreach (var (i, j, weight) in weightedEdges)
        {
            Vertices[(int)i].Edges[j] = weight;
            Vertices[(int)j].Edges[i] = weight;
        }

        _activeTimestamp = 0;
        EdgeModifier = new EdgeWeightModifier();
        WeightedEdges = [.. weightedEdges];
    }

    /// <summary>
    /// Reset any temporary changes like erasure edges
    /// </summary>
    public void Reset()
    {
        // Recover erasure edges
        while (EdgeModifier.HasModifiedEdges())
        {
            var (edgeIndex, originalWeight) = EdgeModifier.PopModifiedEdge();
            var (vertexIdx1, vertexIdx2, _) = WeightedEdges[(int)edgeIndex];
            var vertex1 = Vertices[(int)vertexIdx1];
            vertex1.Edges[vertexIdx2] = originalWeight;
            var vertex2 = Vertices[(int)vertexIdx2];
            vertex2.Edges[vertexIdx1] = originalWeight;
            WeightedEdges[(int)edgeIndex] = (vertexIdx1, vertexIdx2, originalWeight);
        }
    }

    /// <summary>
    /// Load edge modifier (internal method)
    /// </summary>
    private void LoadEdgeModifier(List<(uint, int)> edgeModifier)
    {
        Debug.Assert(!EdgeModifier.HasModifiedEdges(),
            "The current erasure modifier is not clean, probably forget to clean the state?");

        foreach (var (edgeIndex, targetWeight) in edgeModifier)
        {
            var (vertexIdx1, vertexIdx2, originalWeight) = WeightedEdges[(int)edgeIndex];
            var vertex1 = Vertices[(int)vertexIdx1];
            vertex1.Edges[vertexIdx2] = targetWeight;
            var vertex2 = Vertices[(int)vertexIdx2];
            vertex2.Edges[vertexIdx1] = targetWeight;
            EdgeModifier.PushModifiedEdge(edgeIndex, originalWeight);
            WeightedEdges[(int)edgeIndex] = (vertexIdx1, vertexIdx2, targetWeight);
        }
    }

    /// <summary>
    /// Temporarily set some edges to 0 weight, and when it resets, those edges will be reverted back to the original weight
    /// </summary>
    public void LoadErasures(List<uint> erasures)
    {
        var edgeModifier = erasures.Select(edgeIndex => (edgeIndex, 0)).ToList();
        LoadEdgeModifier(edgeModifier);
    }

    /// <summary>
    /// Load dynamic weights
    /// </summary>
    public void LoadDynamicWeights(List<(uint, int)> dynamicWeights) => LoadEdgeModifier([.. dynamicWeights]);

    /// <summary>
    /// Invalidate Dijkstra's algorithm state from previous call
    /// </summary>
    public ulong InvalidatePreviousDijkstra()
    {
        if (_activeTimestamp == ulong.MaxValue)
        {
            // Rarely happens
            _activeTimestamp = 0;
            for (var i = 0; i < VertexNum; i++)
            {
                Vertices[i].Timestamp = 0; // Refresh all timestamps to avoid conflicts
            }
        }
        _activeTimestamp += 1; // Implicitly invalidate all vertices
        return _activeTimestamp;
    }

    /// <summary>
    /// Get all complete graph edges from the specific vertex, but will terminate if terminate vertex is found
    /// </summary>
    public SortedDictionary<uint, (uint Previous, int Weight)> AllEdgesWithTerminate(uint vertex, uint terminate)
    {
        var activeTimestamp = InvalidatePreviousDijkstra();
        var pq = new PriorityQueue<uint, PriorityElement>();
        pq.Push(vertex, new PriorityElement(0, vertex));
        SortedDictionary<uint, (uint, int)> computedEdges = []; // { peer: (previous, weight) }

        while (!pq.IsEmpty)
        {
            var (target, priorityElement) = pq.Pop();
            var weight = priorityElement.Weight;
            var previous = priorityElement.Previous;

            Debug.Assert(!computedEdges.ContainsKey(target)); // This entry shouldn't have been set

            // Update entry
            Vertices[(int)target].Timestamp = activeTimestamp; // Mark as visited
            if (target != vertex)
            {
                computedEdges[target] = (previous, weight);
                if (target == terminate)
                {
                    break; // Early terminate
                }
            }

            // Add its neighbors to priority queue
            foreach (var (neighbor, neighborWeight) in Vertices[(int)target].Edges)
            {
                var edgeWeight = weight + neighborWeight;
                var existingPriority = pq.GetPriority(neighbor);

                if (existingPriority != null && !EqualityComparer<PriorityElement>.Default.Equals(existingPriority.Value, default))
                {
                    var existingWeight = existingPriority.Value.Weight;
                    var existingPrevious = existingPriority.Value.Previous;

                    // Update the priority if weight is smaller or weight is equal but distance is smaller
                    var update = edgeWeight < existingWeight;
                    if (edgeWeight == existingWeight)
                    {
                        var distance = neighbor > previous ? neighbor - previous : previous - neighbor;
                        var existingDistance = neighbor > existingPrevious ? neighbor - existingPrevious : existingPrevious - neighbor;

                        // Prevent loop by enforcing strong non-descending
                        if (distance < existingDistance || (distance == existingDistance && previous < existingPrevious))
                        {
                            update = true;
                        }
                    }

                    if (update)
                    {
                        pq.ChangePriority(neighbor, new PriorityElement(edgeWeight, target));
                    }
                }
                else
                {
                    // Insert new entry only if neighbor has not been visited
                    if (Vertices[(int)neighbor].Timestamp != activeTimestamp)
                    {
                        pq.Push(neighbor, new PriorityElement(edgeWeight, target));
                    }
                }
            }
        }

        return computedEdges;
    }

    /// <summary>
    /// Get all complete graph edges from the specific vertex
    /// </summary>
    public SortedDictionary<uint, (uint Previous, int Weight)> AllEdges(uint vertex) =>
        AllEdgesWithTerminate(vertex, uint.MaxValue);

    /// <summary>
    /// Get minimum-weight path between any two vertices a and b
    /// </summary>
    public (List<(uint Vertex, int Weight)> Path, int TotalWeight) GetPath(uint a, uint b)
    {
        Debug.Assert(a != b, "Cannot get path between the same vertex");

        var edges = AllEdgesWithTerminate(a, b);
        var vertex = b;
        List<(uint, int)> path = [];

        while (vertex != a)
        {
            var (previous, weight) = edges[vertex];
            path.Add((vertex, weight));
            if (path.Count > 1)
            {
                var previousIndex = path.Count - 2;
                var (v, w) = path[previousIndex];
                path[previousIndex] = (v, w - weight);
            }
            vertex = previous;
        }

        path.Reverse();
        return (path, edges[b].Weight);
    }
}
