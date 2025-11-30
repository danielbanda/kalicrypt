namespace BlossomV.Core;

/// <summary>
/// Node flags for the Blossom V algorithm
/// </summary>
public enum NodeFlag
{
    /// <summary>
    /// Free node (not in tree)
    /// </summary>
    Free = 0,

    /// <summary>
    /// Plus node (outer node in tree)
    /// </summary>
    Plus = 1,

    /// <summary>
    /// Minus node (inner node in tree)
    /// </summary>
    Minus = 2
}

/// <summary>
/// Represents a node in the matching graph
/// Translated from C++ PerfectMatching::Node
/// </summary>
public class Node
{
    public int Id { get; set; }

    // Bit flags
    public bool IsOuter { get; set; }
    public NodeFlag Flag { get; set; }
    public bool IsTreeRoot { get; set; }
    public bool IsProcessed { get; set; }
    public bool IsBlossom { get; set; }
    public bool IsMarked { get; set; }
    public bool IsRemoved { get; set; }

    // Adjacency lists (one per direction)
    public Edge?[] FirstEdge { get; set; } = new Edge?[2];

    // Matching information
    public Edge? Match { get; set; }

    // Dual variable
    public Real Y { get; set; }

    // Blossom hierarchy
    public Node? BlossomParent { get; set; }
    public Node? BlossomSibling { get; set; }
    public Node? BlossomGrandparent { get; set; }
    public Real BlossomEps { get; set; }

    // Tree structure (for outer nodes)
    public int TreeRoot { get; set; } = -1;
    public Node? FirstTreeChild { get; set; }
    public Node? TreeSiblingPrev { get; set; }
    public Node? TreeSiblingNext { get; set; }
    public Edge? TreeParent { get; set; }

    // LCA (Lowest Common Ancestor) support
    public int LcaPreorder { get; set; }
    public int LcaSize { get; set; }

    public Node()
    {
        Id = -1;
        Y = Real.Zero;
        BlossomEps = Real.Zero;
    }
}

/// <summary>
/// Represents an edge in the matching graph
/// Translated from C++ PerfectMatching::Edge
/// </summary>
public class Edge
{
    public int Id { get; set; }

    // Endpoint nodes (current and original)
    public int[] Head { get; set; } = new int[2];
    public int[] Head0 { get; set; } = new int[2];

    // Adjacency list pointers (one per direction)
    public Edge?[] Next { get; set; } = new Edge?[2];
    public Edge?[] Prev { get; set; } = new Edge?[2];

    // Edge cost and slack
    public Real Slack { get; set; }

    // Priority queue support
    public int PqIndex { get; set; } = -1;

    public Edge()
    {
        Id = -1;
        Slack = Real.Zero;
    }
}

/// <summary>
/// Represents an alternating tree in the matching algorithm
/// Translated from C++ PerfectMatching::Tree
/// </summary>
public class Tree
{
    /// <summary>
    /// Root node of the tree
    /// </summary>
    public int Root { get; set; } = -1;

    /// <summary>
    /// Epsilon value for dual updates
    /// </summary>
    public Real Eps { get; set; }

    /// <summary>
    /// Epsilon delta for dual updates
    /// </summary>
    public Real EpsDelta { get; set; }

    /// <summary>
    /// First edge in the tree
    /// </summary>
    public TreeEdge? FirstEdge { get; set; }

    /// <summary>
    /// Tree ID for DFS
    /// </summary>
    public int Id { get; set; } = -1;

    /// <summary>
    /// Parent tree in DFS
    /// </summary>
    public Tree? DfsParent { get; set; }

    public Tree()
    {
        Eps = Real.Zero;
        EpsDelta = Real.Zero;
    }
}

/// <summary>
/// Represents an edge between trees
/// Translated from C++ PerfectMatching::TreeEdge
/// </summary>
public class TreeEdge
{
    /// <summary>
    /// Connected trees
    /// </summary>
    public int[] Head { get; set; } = new int[2];

    /// <summary>
    /// Next edge in the list
    /// </summary>
    public TreeEdge?[] Next { get; set; } = new TreeEdge?[2];

    /// <summary>
    /// Previous edge in the list
    /// </summary>
    public TreeEdge?[] Prev { get; set; } = new TreeEdge?[2];
}

/// <summary>
/// Priority queue pointers for different edge types
/// Translated from C++ PerfectMatching::PQPointers
/// </summary>
public class PQPointers
{
    /// <summary>
    /// Priority queue for ++ edges
    /// </summary>
    public PriorityQueue<int>? Pq00 { get; set; }

    /// <summary>
    /// Priority queues for +- edges (one per direction)
    /// </summary>
    public PriorityQueue<int>?[] Pq01 { get; set; } = new PriorityQueue<int>?[2];

    /// <summary>
    /// Priority queue for +free edges
    /// </summary>
    public PriorityQueue<int>? Pq0 { get; set; }

    /// <summary>
    /// Priority queue for blossoms
    /// </summary>
    public PriorityQueue<int>? PqBlossoms { get; set; }
}

/// <summary>
/// Simple priority queue implementation for edge management
/// </summary>
/// <typeparam name="T">Element type</typeparam>
public class PriorityQueue<T> where T : IComparable<T>
{
    private readonly SortedDictionary<T, int> _items = [];
    private int _count;

    public int Count => _count;

    public bool IsEmpty => _count == 0;

    public void Add(T item)
    {
        if (!_items.ContainsKey(item))
        {
            _items[item] = 0;
        }

        _items[item]++;
        _count++;
    }

    public T? GetMin()
    {
        if (_count == 0)
        {
            return default;
        }

        return _items.Keys.First();
    }

    public T? RemoveMin()
    {
        if (_count == 0)
        {
            return default;
        }

        var min = _items.Keys.First();
        _items[min]--;
        _count--;

        if (_items[min] == 0)
        {
            _items.Remove(min);
        }

        return min;
    }

    public void Clear()
    {
        _items.Clear();
        _count = 0;
    }
}
