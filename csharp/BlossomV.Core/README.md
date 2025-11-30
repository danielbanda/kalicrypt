# BlossomV.Core - C# Implementation

This project contains a C# translation of the Blossom V algorithm for minimum cost perfect matching in graphs.

## Overview

Blossom V is an implementation of Edmonds' algorithm for computing minimum cost perfect matching. This C# translation is based on the C++ implementation by Vladimir Kolmogorov.

## Original Implementation

- **Author**: Vladimir Kolmogorov
- **Paper**: "Blossom V: A new implementation of a minimum cost perfect matching algorithm"
- **Publication**: Mathematical Programming Computation (MPC), July 2009, 1(1):43-67
- **DOI**: https://doi.org/10.1007/s12532-009-0002-8

## License and Usage Restrictions

⚠️ **IMPORTANT**: The original Blossom V implementation has the following restrictions:

- **For evaluation and non-commercial research purposes only**
- **Commercial use is prohibited**
- **Public redistribution of the code or its derivatives is prohibited**

If you use this implementation in published research, you must cite the original paper:

```
V. Kolmogorov. "Blossom V: A new implementation of a minimum cost perfect matching algorithm."
Mathematical Programming Computation (MPC), July 2009, 1(1):43-67.
```

For commercial licensing, contact the original author through:
- https://pub.ista.ac.at/~vnk/software.html
- UCL Business e-licensing website

## Architecture

This C# implementation includes:

### Core Classes

- **`PerfectMatching`** - Main algorithm class
  - `AddEdge(i, j, cost)` - Add weighted edges
  - `Solve()` - Compute minimum cost matching
  - `GetMatch(i)` - Get matched node for node i
  - `GetSolution(e)` - Check if edge e is in matching

### Data Structures

- **`Node`** - Graph vertices with dual variables and blossom state
- **`Edge`** - Graph edges with costs and slack values
- **`Tree`** - Alternating trees for the algorithm
- **`PriorityQueue`** - For efficient edge selection

### Types

- **`NodeId`** - Type-safe node identifier
- **`EdgeId`** - Type-safe edge identifier
- **`Real`** - Cost/weight type (int or double)

## Usage Example

```csharp
using BlossomV.Core;

// Create matching instance
var pm = new PerfectMatching(nodeCount: 4, edgeMax: 6);

// Add edges with costs
pm.AddEdge(0, 1, 100);
pm.AddEdge(2, 3, 110);
pm.AddEdge(0, 2, 500);
pm.AddEdge(1, 3, 300);

// Solve
pm.Solve();

// Get results
for (int i = 0; i < 4; i++)
{
    var match = pm.GetMatch(i);
    Console.WriteLine($"Node {i} matched to {match}");
}

// Get total cost
var cost = pm.ComputePerfectMatchingCost();
Console.WriteLine($"Total cost: {cost}");
```

## Managed API

The `ManagedPerfectMatching` class provides a simpler API compatible with P/Invoke:

```csharp
using BlossomV.Core;

var edges = new List<(int, int, int)>
{
    (0, 1, 100),
    (2, 3, 110),
    (0, 2, 500),
    (1, 3, 300)
};

var matching = ManagedPerfectMatching.SolveMinimumWeightPerfectMatching(4, edges);
```

## Algorithm Details

The implementation uses the primal-dual method with the following key features:

1. **Dual Variable Updates** - Flexible dual update strategies
2. **Blossom Shrinking** - Handles odd-length cycles
3. **Priority Queues** - Efficient edge selection
4. **Tree Growing** - Builds alternating trees
5. **Augmentation** - Updates matching along augmenting paths

## Translation Notes

This C# translation maintains the structure and algorithm of the original C++ implementation while adapting to C# idioms:

- Uses C# classes instead of C++ structs
- Implements type-safe wrappers for IDs
- Uses C# collections instead of manual memory management
- Provides both low-level and high-level APIs
- Includes modern C# features (collection expressions, etc.)

## Performance

This is a functional translation focused on correctness. For production use, consider:

- Using the original C++ implementation via P/Invoke for best performance
- Or the PyMatching V2 library which has significant optimizations
- This C# implementation is primarily for educational purposes

## References

1. Kolmogorov, V. (2009). Blossom V: A new implementation of a minimum cost perfect matching algorithm. *Mathematical Programming Computation*, 1(1), 43-67.
2. Edmonds, J. (1965). Paths, trees, and flowers. *Canadian Journal of Mathematics*, 17, 449-467.
3. Cook, W., & Rohe, A. (1999). Computing minimum-weight perfect matchings. *INFORMS Journal on Computing*, 11(2), 138-148.

## Related Projects

- **fusion-blossom**: Rust implementation with parallel computation - https://github.com/yuewuo/fusion-blossom/
- **PyMatching V2**: High-performance Python/C++ implementation - https://github.com/oscarhiggott/PyMatching
- **Original Blossom V**: C++ implementation - https://pub.ista.ac.at/~vnk/software.html
