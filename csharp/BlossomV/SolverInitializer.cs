namespace BlossomV;

/// <summary>
/// Initializer for the MWPM solver
/// Translated from Rust struct SolverInitializer
/// </summary>
public class SolverInitializer
{
    /// <summary>
    /// The number of vertices
    /// </summary>
    public uint VertexNum { get; set; }

    /// <summary>
    /// Weighted edges, where vertex indices are within the range [0, vertex_num)
    /// Each tuple contains (vertex1, vertex2, weight)
    /// </summary>
    public List<(uint, uint, int)> WeightedEdges { get; set; }

    /// <summary>
    /// The virtual vertices
    /// </summary>
    public List<uint> VirtualVertices { get; set; }

    public SolverInitializer(uint vertexNum, List<(uint, uint, int)> weightedEdges, List<uint> virtualVertices)
    {
        VertexNum = vertexNum;
        WeightedEdges = weightedEdges ?? new List<(uint, uint, int)>();
        VirtualVertices = virtualVertices ?? new List<uint>();
    }

    public SolverInitializer()
    {
        VertexNum = 0;
        WeightedEdges = new List<(uint, uint, int)>();
        VirtualVertices = new List<uint>();
    }
}
