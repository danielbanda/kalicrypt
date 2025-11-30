using System.Runtime.InteropServices;

namespace BlossomV;

/// <summary>
/// Blossom V algorithm wrapper
/// Translated from Rust module blossom_v
///
/// NOTE: This implementation requires a native Blossom V library.
/// The native library can be obtained from https://pub.ist.ac.at/~vnk/software.html
/// See the Blossom V paper: https://doi.org/10.1007/s12532-009-0002-8
/// </summary>
public static class BlossomVSolver
{
    // P/Invoke declaration for the native Blossom V library
    // This would need to be implemented in C++ and compiled as a shared library
    [DllImport("blossomV", CallingConvention = CallingConvention.Cdecl)]
    private static extern void minimum_weight_perfect_matching(
        int nodeNum,
        int edgeNum,
        int[] edges,
        int[] weights,
        int[] matched);

    /// <summary>
    /// Safe wrapper for minimum weight perfect matching using Blossom V library
    /// </summary>
    /// <param name="nodeNum">Number of nodes</param>
    /// <param name="weightedEdges">List of weighted edges (vertex1, vertex2, weight)</param>
    /// <returns>Array where result[i] is the matched vertex for vertex i</returns>
    /// <exception cref="InvalidOperationException">Thrown when invalid input is detected</exception>
    public static List<uint> SafeMinimumWeightPerfectMatching(uint nodeNum, List<(uint, uint, uint)> weightedEdges)
    {
        var edgeNum = weightedEdges.Count;
        var edges = new int[2 * edgeNum];
        var weights = new int[edgeNum];

        // Sanity checks (debug mode)
#if DEBUG
        HashSet<(uint, uint)> existingEdges = [];
        foreach (var (i, j, weight) in weightedEdges)
        {
            if (i == j)
            {
                throw new InvalidOperationException($"Invalid edge between the same vertex {i}");
            }

            var left = i < j ? i : j;
            var right = i < j ? j : i;

            if (existingEdges.Contains((left, right)))
            {
                throw new InvalidOperationException($"Duplicate edge between vertices {i} and {j}");
            }

            existingEdges.Add((left, right));
        }
#endif

        // Prepare edges and weights arrays
        for (var e = 0; e < edgeNum; e++)
        {
            var (i, j, weight) = weightedEdges[e];

            if (i >= nodeNum || j >= nodeNum)
            {
                throw new InvalidOperationException($"Vertex index out of range: i={i}, j={j}, nodeNum={nodeNum}");
            }

            edges[2 * e] = (int)i;
            edges[2 * e + 1] = (int)j;
            weights[e] = (int)weight;
        }

        var output = new int[nodeNum];

        // Call native Blossom V library
        // Note: This will throw DllNotFoundException if the native library is not available
        try
        {
            minimum_weight_perfect_matching((int)nodeNum, edgeNum, edges, weights, output);
        }
        catch (DllNotFoundException)
        {
            throw new InvalidOperationException(
                "Blossom V library not found. Please compile the native Blossom V library. " +
                "See https://pub.ist.ac.at/~vnk/software.html for the Blossom V implementation.");
        }

        // Convert to List<uint>
        var result = new List<uint>((int)nodeNum);
        for (var i = 0; i < nodeNum; i++)
        {
            result.Add((uint)output[i]);
        }

        return result;
    }

    /// <summary>
    /// Fall back to use Blossom V library to solve MWPM (install Blossom V required)
    /// Translated from Rust function blossom_v_mwpm
    /// </summary>
    public static List<uint> BlossomVMwpm(SolverInitializer initializer, List<uint> defectVertices)
    {
        // Sanity check
        if (initializer.VertexNum <= 1)
        {
            throw new InvalidOperationException("At least one vertex required");
        }

        var maxSafeWeight = int.MaxValue / (int)initializer.VertexNum;
        foreach (var (i, j, weight) in initializer.WeightedEdges)
        {
            if (weight > maxSafeWeight)
            {
                throw new InvalidOperationException(
                    $"Edge {i}-{j} has weight {weight} > max safe weight {maxSafeWeight}, " +
                    "it may cause Blossom V library to overflow");
            }
        }

        var completeGraph = new CompleteGraph(initializer.VertexNum, initializer.WeightedEdges);
        return BlossomVMwpmReuse(completeGraph, initializer, defectVertices);
    }

    /// <summary>
    /// Reusable version of BlossomVMwpm that accepts a pre-built CompleteGraph
    /// Translated from Rust function blossom_v_mwpm_reuse
    /// </summary>
    public static List<uint> BlossomVMwpmReuse(
        CompleteGraph completeGraph,
        SolverInitializer initializer,
        List<uint> defectVertices)
    {
        // First collect virtual vertices and real vertices
        var isVirtual = new bool[initializer.VertexNum];
        var isDefect = new bool[initializer.VertexNum];

        foreach (var virtualVertex in initializer.VirtualVertices)
        {
            if (virtualVertex >= initializer.VertexNum)
            {
                throw new InvalidOperationException("Invalid input");
            }
            if (isVirtual[virtualVertex])
            {
                throw new InvalidOperationException("Same virtual vertex appears twice");
            }
            isVirtual[virtualVertex] = true;
        }

        var mappingToDefectVertices = new uint[initializer.VertexNum];
        for (var i = 0; i < mappingToDefectVertices.Length; i++)
        {
            mappingToDefectVertices[i] = uint.MaxValue;
        }

        for (var i = 0; i < defectVertices.Count; i++)
        {
            var defectVertex = defectVertices[i];
            if (defectVertex >= initializer.VertexNum)
            {
                throw new InvalidOperationException("Invalid input");
            }
            if (isVirtual[defectVertex])
            {
                throw new InvalidOperationException("Syndrome vertex cannot be virtual");
            }
            if (isDefect[defectVertex])
            {
                throw new InvalidOperationException("Same syndrome vertex appears twice");
            }
            isDefect[defectVertex] = true;
            mappingToDefectVertices[defectVertex] = (uint)i;
        }

        // For each real vertex, add a corresponding virtual vertex to be matched
        var defectNum = defectVertices.Count;
        var legacyVertexNum = defectNum * 2;
        List<(uint, uint, uint)> legacyWeightedEdges = [];
        List<(uint Vertex, int Weight)?> boundaries = [];

        for (var i = 0; i < defectNum; i++)
        {
            var defectVertex = defectVertices[i];
            var completeGraphEdges = completeGraph.AllEdges(defectVertex);
            (uint Vertex, int Weight)? boundary = null;

            foreach (var (peer, (_, weight)) in completeGraphEdges)
            {
                if (isVirtual[peer] && (boundary == null || weight < boundary.Value.Weight))
                {
                    boundary = (peer, weight);
                }
            }

            if (boundary != null)
            {
                // Connect this real vertex to its corresponding virtual vertex
                legacyWeightedEdges.Add(((uint)i, (uint)(i + defectNum), (uint)boundary.Value.Weight));
            }

            boundaries.Add(boundary); // Save for later resolve legacy matchings

            foreach (var (peer, (_, weight)) in completeGraphEdges)
            {
                if (isDefect[peer])
                {
                    var j = (int)mappingToDefectVertices[peer];
                    if (i < j)
                    {
                        // Remove duplicated edges
                        legacyWeightedEdges.Add(((uint)i, (uint)j, (uint)weight));
                    }
                }
            }

            for (var j = i + 1; j < defectNum; j++)
            {
                // Virtual boundaries are always fully connected with weight 0
                legacyWeightedEdges.Add(((uint)(i + defectNum), (uint)(j + defectNum), 0));
            }
        }

        // Run Blossom V to get matchings
        var matchings = SafeMinimumWeightPerfectMatching((uint)legacyVertexNum, legacyWeightedEdges);
        List<uint> mwpmResult = [];

        for (var i = 0; i < defectNum; i++)
        {
            var j = (int)matchings[i];
            if (j < defectNum)
            {
                // Match to a real vertex
                mwpmResult.Add(defectVertices[j]);
            }
            else
            {
                // Must match to its corresponding virtual vertex
                if (j != i + defectNum)
                {
                    throw new InvalidOperationException(
                        "If not matched to another real vertex, it must match to its corresponding virtual vertex");
                }

                if (boundaries[i] == null)
                {
                    throw new InvalidOperationException("Boundary must exist if match to virtual vertex");
                }

                mwpmResult.Add(boundaries[i]!.Value.Vertex);
            }
        }

        return mwpmResult;
    }
}
