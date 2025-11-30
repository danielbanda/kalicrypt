namespace BlossomV.Core;

/// <summary>
/// Managed wrapper for PerfectMatching that provides a simple interface
/// compatible with the native BlossomV library API
/// </summary>
public static class ManagedPerfectMatching
{
    /// <summary>
    /// Solves minimum weight perfect matching problem
    /// </summary>
    /// <param name="nodeNum">Number of nodes</param>
    /// <param name="edgeNum">Number of edges</param>
    /// <param name="edges">Edge array (packed as i0, j0, i1, j1, ...)</param>
    /// <param name="weights">Edge weights</param>
    /// <param name="matched">Output array for matched nodes</param>
    public static void MinimumWeightPerfectMatching(
        int nodeNum,
        int edgeNum,
        int[] edges,
        int[] weights,
        int[] matched)
    {
        if (nodeNum <= 0)
        {
            throw new ArgumentException("Node count must be positive", nameof(nodeNum));
        }

        if (edgeNum < 0)
        {
            throw new ArgumentException("Edge count cannot be negative", nameof(edgeNum));
        }

        if (edges.Length < edgeNum * 2)
        {
            throw new ArgumentException("Edges array too small", nameof(edges));
        }

        if (weights.Length < edgeNum)
        {
            throw new ArgumentException("Weights array too small", nameof(weights));
        }

        if (matched.Length < nodeNum)
        {
            throw new ArgumentException("Matched array too small", nameof(matched));
        }

        // Create matching instance
        var pm = new PerfectMatching(nodeNum, edgeNum);

        // Add all edges
        for (var e = 0; e < edgeNum; e++)
        {
            var i = edges[2 * e];
            var j = edges[2 * e + 1];
            var weight = weights[e];

            pm.AddEdge(i, j, weight);
        }

        // Solve
        pm.Solve();

        // Extract solution
        for (var i = 0; i < nodeNum; i++)
        {
            matched[i] = pm.GetMatch(i);
        }
    }

    /// <summary>
    /// Convenience method that returns the matching as a list
    /// </summary>
    public static List<int> SolveMinimumWeightPerfectMatching(
        int nodeNum,
        List<(int i, int j, int weight)> edges)
    {
        var edgeNum = edges.Count;
        var edgeArray = new int[edgeNum * 2];
        var weightArray = new int[edgeNum];

        for (var e = 0; e < edgeNum; e++)
        {
            edgeArray[2 * e] = edges[e].i;
            edgeArray[2 * e + 1] = edges[e].j;
            weightArray[e] = edges[e].weight;
        }

        var matched = new int[nodeNum];
        MinimumWeightPerfectMatching(nodeNum, edgeNum, edgeArray, weightArray, matched);

        return [.. matched];
    }
}
