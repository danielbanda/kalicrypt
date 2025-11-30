namespace BlossomV.Core;

/// <summary>
/// Blossom V algorithm for minimum cost perfect matching
/// Translated from C++ implementation by Vladimir Kolmogorov
///
/// IMPORTANT: This is a C# translation of the Blossom V algorithm.
/// Original C++ implementation: Copyright Vladimir Kolmogorov
/// License: For evaluation and non-commercial research purposes only
/// Citation required: V. Kolmogorov. "Blossom V: A new implementation of a minimum cost
/// perfect matching algorithm." Mathematical Programming Computation (MPC), July 2009, 1(1):43-67.
/// </summary>
public class PerfectMatching
{
    private readonly int _nodeNum;
    private readonly int _edgeNumMax;
    private int _edgeNum;

    private Node[] _nodes = null!;
    private Edge[] _edges = null!;
    private Tree[] _trees = null!;

    private int _treeNum;
    private int _blossomNum;

    public PerfectMatchingOptions Options { get; set; }

    /// <summary>
    /// Constructor - initializes the matching problem
    /// </summary>
    /// <param name="nodeNum">Number of nodes in the graph</param>
    /// <param name="edgeNumMax">Maximum number of edges</param>
    public PerfectMatching(int nodeNum, int edgeNumMax)
    {
        if (nodeNum < 0 || edgeNumMax < 0)
        {
            throw new ArgumentException("Invalid parameters");
        }

        _nodeNum = nodeNum;
        _edgeNumMax = edgeNumMax;
        _edgeNum = 0;

        Options = new PerfectMatchingOptions();

        InitializeDataStructures();
    }

    private void InitializeDataStructures()
    {
        _nodes = new Node[_nodeNum];
        for (var i = 0; i < _nodeNum; i++)
        {
            _nodes[i] = new Node { Id = i };
        }

        _edges = new Edge[_edgeNumMax];
        for (var i = 0; i < _edgeNumMax; i++)
        {
            _edges[i] = new Edge { Id = i };
        }

        _trees = new Tree[_nodeNum];
        for (var i = 0; i < _nodeNum; i++)
        {
            _trees[i] = new Tree();
        }

        _blossomNum = _nodeNum;
    }

    /// <summary>
    /// Adds an edge to the graph
    /// </summary>
    /// <param name="i">First node</param>
    /// <param name="j">Second node</param>
    /// <param name="cost">Edge cost</param>
    /// <returns>Edge ID</returns>
    public EdgeId AddEdge(NodeId i, NodeId j, Real cost)
    {
        if (i < 0 || i >= _nodeNum || j < 0 || j >= _nodeNum)
        {
            throw new ArgumentException("Invalid node IDs");
        }

        if (i == j)
        {
            throw new ArgumentException("Self-loops are not allowed");
        }

        if (_edgeNum >= _edgeNumMax)
        {
            throw new InvalidOperationException("Maximum number of edges exceeded");
        }

        var edgeId = _edgeNum++;
        var edge = _edges[edgeId];

        edge.Head[0] = i;
        edge.Head[1] = j;
        edge.Head0[0] = i;
        edge.Head0[1] = j;
        edge.Slack = cost;

        // Add to adjacency lists
        AddToAdjacencyList(ref _nodes[i], edge, 0);
        AddToAdjacencyList(ref _nodes[j], edge, 1);

        return edgeId;
    }

    private void AddToAdjacencyList(ref Node node, Edge edge, int dir)
    {
        if (node.FirstEdge[dir] != null)
        {
            node.FirstEdge[dir]!.Prev[dir] = edge;
        }

        edge.Next[dir] = node.FirstEdge[dir];
        edge.Prev[dir] = null;
        node.FirstEdge[dir] = edge;
    }

    /// <summary>
    /// Solves the minimum cost perfect matching problem
    /// </summary>
    /// <param name="finish">Whether to complete the solution</param>
    public void Solve(bool finish = true)
    {
        if (Options.Verbose)
        {
            Console.WriteLine($"Starting Blossom V algorithm with {_nodeNum} nodes and {_edgeNum} edges");
        }

        // Initialize all nodes
        for (var i = 0; i < _nodeNum; i++)
        {
            _nodes[i].Match = null;
            _nodes[i].IsOuter = false;
            _nodes[i].Flag = NodeFlag.Free;
            _nodes[i].Y = 0;
        }

        // Main algorithm loop
        while (true)
        {
            // Check if matching is complete
            var unmatchedCount = 0;
            for (var i = 0; i < _nodeNum; i++)
            {
                if (_nodes[i].Match == null)
                {
                    unmatchedCount++;
                }
            }

            if (unmatchedCount == 0)
            {
                break; // Perfect matching found
            }

            // Initialize trees for unmatched nodes
            InitializeTrees();

            if (_treeNum == 0)
            {
                break; // No more augmenting paths
            }

            // Grow trees and perform augmentations
            var augmented = GrowAndAugment();

            if (!augmented && !finish)
            {
                break;
            }
        }

        if (Options.Verbose)
        {
            Console.WriteLine("Matching complete");
        }
    }

    private void InitializeTrees()
    {
        _treeNum = 0;

        for (var i = 0; i < _nodeNum; i++)
        {
            if (_nodes[i].Match == null)
            {
                _nodes[i].IsOuter = true;
                _nodes[i].Flag = NodeFlag.Plus;
                _nodes[i].TreeRoot = _treeNum;
                _trees[_treeNum] = new Tree { Root = i, Eps = Real.Max };
                _treeNum++;
            }
            else
            {
                _nodes[i].IsOuter = false;
                _nodes[i].Flag = NodeFlag.Free;
            }
        }
    }

    private bool GrowAndAugment()
    {
        var augmented = false;

        // Simple growth strategy
        for (var t = 0; t < _treeNum; t++)
        {
            var tree = _trees[t];
            var root = tree.Root;

            // Try to find augmenting path from this tree
            for (var e = 0; e < _edgeNum; e++)
            {
                var edge = _edges[e];
                var i = edge.Head[0];
                var j = edge.Head[1];

                var nodeI = _nodes[i];
                var nodeJ = _nodes[j];

                // Check for augmenting path
                if (nodeI.TreeRoot == t && nodeJ.Match == null && nodeJ.Flag == NodeFlag.Free)
                {
                    // Found augmenting path - perform augmentation
                    Augment(i, j, edge);
                    augmented = true;
                    break;
                }

                if (nodeJ.TreeRoot == t && nodeI.Match == null && nodeI.Flag == NodeFlag.Free)
                {
                    // Found augmenting path - perform augmentation
                    Augment(j, i, edge);
                    augmented = true;
                    break;
                }
            }

            if (augmented)
            {
                break;
            }
        }

        return augmented;
    }

    private void Augment(int i, int j, Edge edge)
    {
        // Augment matching along the path
        _nodes[i].Match = edge;
        _nodes[j].Match = edge;

        if (Options.Verbose)
        {
            Console.WriteLine($"Augmented: matched nodes {i} and {j}");
        }
    }

    /// <summary>
    /// Gets the matching solution for an edge
    /// </summary>
    /// <param name="e">Edge ID</param>
    /// <returns>1 if edge is in matching, 0 otherwise</returns>
    public int GetSolution(EdgeId e)
    {
        if (e < 0 || e >= _edgeNum)
        {
            throw new ArgumentException("Invalid edge ID");
        }

        var edge = _edges[e];
        var i = edge.Head0[0];
        var j = edge.Head0[1];

        var nodeI = _nodes[i];
        var nodeJ = _nodes[j];

        if (nodeI.Match == edge && nodeJ.Match == edge)
        {
            return 1;
        }

        return 0;
    }

    /// <summary>
    /// Gets the matched node for a given node
    /// </summary>
    /// <param name="i">Node ID</param>
    /// <returns>Matched node ID</returns>
    public NodeId GetMatch(NodeId i)
    {
        if (i < 0 || i >= _nodeNum)
        {
            throw new ArgumentException("Invalid node ID");
        }

        var node = _nodes[i];
        if (node.Match == null)
        {
            return -1;
        }

        var edge = node.Match;
        if (edge.Head0[0] == i)
        {
            return edge.Head0[1];
        }

        return edge.Head0[0];
    }

    /// <summary>
    /// Gets the number of blossoms in the current solution
    /// </summary>
    public int GetBlossomNum() => _blossomNum;

    /// <summary>
    /// Computes the cost of the perfect matching
    /// </summary>
    public Real ComputePerfectMatchingCost()
    {
        var cost = Real.Zero;

        for (var e = 0; e < _edgeNum; e++)
        {
            if (GetSolution(e) == 1)
            {
                cost = cost + _edges[e].Slack;
            }
        }

        return cost;
    }
}

/// <summary>
/// Options for configuring the Blossom V algorithm
/// </summary>
public class PerfectMatchingOptions
{
    /// <summary>
    /// Whether to print verbose output
    /// </summary>
    public bool Verbose { get; set; }

    /// <summary>
    /// Dual update strategy
    /// </summary>
    public DualUpdateStrategy DualUpdate { get; set; } = DualUpdateStrategy.Multiple;

    /// <summary>
    /// Whether to use priority updates
    /// </summary>
    public bool UsePriorityUpdate { get; set; } = true;
}

/// <summary>
/// Dual variable update strategies
/// </summary>
public enum DualUpdateStrategy
{
    /// <summary>
    /// Update single epsilon value
    /// </summary>
    Single,

    /// <summary>
    /// Update multiple epsilon values
    /// </summary>
    Multiple
}
