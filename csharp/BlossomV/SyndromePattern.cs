namespace BlossomV;

/// <summary>
/// Pattern of syndrome measurements
/// Translated from Rust struct SyndromePattern
/// </summary>
public class SyndromePattern
{
    /// <summary>
    /// The vertices corresponding to defect measurements
    /// </summary>
    public List<uint> DefectVertices { get; set; }

    /// <summary>
    /// The edges that experience erasures, i.e. known errors
    /// </summary>
    public List<uint> Erasures { get; set; }

    /// <summary>
    /// General dynamically weighted edges
    /// </summary>
    public List<(uint, int)> DynamicWeights { get; set; }

    public SyndromePattern(List<uint> defectVertices, List<uint>? erasures = null, List<(uint, int)>? dynamicWeights = null)
    {
        DefectVertices = defectVertices ?? new List<uint>();
        Erasures = erasures ?? new List<uint>();
        DynamicWeights = dynamicWeights ?? new List<(uint, int)>();
    }

    public SyndromePattern()
    {
        DefectVertices = new List<uint>();
        Erasures = new List<uint>();
        DynamicWeights = new List<(uint, int)>();
    }
}
