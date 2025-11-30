# Blossom V Algorithm - C# Translation

This directory contains a C# translation of the Blossom V algorithm wrapper and related code from the [fusion-blossom](https://github.com/yuewuo/fusion-blossom/) Rust repository.

## Overview

The Blossom V algorithm is used for finding minimum weight perfect matchings in general graphs. This implementation provides a C# wrapper around the native Blossom V library, along with supporting data structures and algorithms.

## Translated Components

### Source Files Translated

From the fusion-blossom repository, the following components have been translated:

#### 1. **blossom_v.rs** → **BlossomVSolver.cs**
   - `safe_minimum_weight_perfect_matching()` → `SafeMinimumWeightPerfectMatching()`
   - `blossom_v_mwpm()` → `BlossomVMwpm()`
   - `blossom_v_mwpm_reuse()` → `BlossomVMwpmReuse()`
   - Test case `blossom_v_test_1` → `BlossomVTest1()`

#### 2. **complete_graph.rs** → **CompleteGraph.cs**
   - `CompleteGraph` struct and all methods
   - `CompleteGraphVertex` struct
   - Dijkstra's algorithm implementation for finding shortest paths
   - Methods: `new()`, `reset()`, `all_edges()`, `get_path()`, etc.

#### 3. **util.rs** → Multiple C# files
   - `SolverInitializer` struct → **SolverInitializer.cs**
   - `SyndromePattern` struct → **SyndromePattern.cs**
   - Type aliases → **Types.cs**

#### 4. **dual_module.rs** → **EdgeWeightModifier.cs**
   - `EdgeWeightModifier` struct with methods for tracking edge weight modifications

#### 5. Supporting Data Structures
   - **PriorityElement.cs** - Priority queue element for Dijkstra's algorithm
   - **PriorityQueue.cs** - Generic priority queue implementation

### Test Files Translated

- **BlossomVTests.cs** - Comprehensive test suite including:
  - Basic Blossom V algorithm test
  - Duplicate edge detection test
  - Self-loop detection test
  - Complete graph tests
  - Solver initializer tests
  - Edge weight modifier tests

## Project Structure

```
csharp/
├── BlossomV/                      # Main library project
│   ├── BlossomV.csproj
│   ├── BlossomVSolver.cs          # Main Blossom V wrapper
│   ├── CompleteGraph.cs           # Complete graph with Dijkstra's algorithm
│   ├── SolverInitializer.cs       # Graph initialization
│   ├── SyndromePattern.cs         # Syndrome pattern for defect vertices
│   ├── EdgeWeightModifier.cs      # Edge weight modification tracking
│   ├── PriorityQueue.cs           # Priority queue for Dijkstra
│   ├── PriorityElement.cs         # Priority queue element
│   └── Types.cs                   # Type aliases and definitions
├── BlossomV.Tests/                # Test project
│   ├── BlossomV.Tests.csproj
│   └── BlossomVTests.cs           # Comprehensive test suite
├── BlossomV.sln                   # Visual Studio solution file
└── README.md                      # This file
```

## Building the Project

### Prerequisites

- .NET 8.0 SDK or later
- (Optional) Native Blossom V library for running tests

### Build Commands

```bash
# Build the solution
dotnet build csharp/BlossomV.sln

# Run tests (most tests are skipped without native library)
dotnet test csharp/BlossomV.sln

# Build release version
dotnet build csharp/BlossomV.sln --configuration Release
```

## Native Library Requirements

The Blossom V algorithm requires a native C++ library to function. This library is **not included** due to licensing restrictions.

### Obtaining the Blossom V Library

1. Download the Blossom V source code from: https://pub.ist.ac.at/~vnk/software.html
2. Compile it as a shared library:
   - **Windows**: `blossomV.dll`
   - **Linux**: `libblossomV.so`
   - **macOS**: `libblossomV.dylib`
3. Place the compiled library in the test output directory or system library path

### Building the Native Library

You'll need to create a C wrapper for the Blossom V library. Example code can be found in the original fusion-blossom repository at `blossomV/blossomV.cpp`.

## Usage Example

```csharp
using BlossomV;

// Create a graph with 4 vertices
uint nodeNum = 4;
var edges = new List<(uint, uint, uint)>
{
    (0, 1, 100),
    (2, 3, 110),
    (0, 2, 500),
    (1, 3, 300)
};

// Find minimum weight perfect matching
// Note: Requires native Blossom V library
var matching = BlossomVSolver.SafeMinimumWeightPerfectMatching(nodeNum, edges);

// matching[i] contains the vertex that vertex i is matched to
Console.WriteLine($"Vertex 0 matched to vertex {matching[0]}");
```

## Translation Notes

### Key Differences from Rust

1. **Memory Management**: C# uses garbage collection instead of Rust's ownership system
2. **Type System**: Used C# structs for simple types, classes for complex types
3. **Error Handling**: Converted Rust's `panic!` and `assert!` to C# exceptions
4. **Generics**: Adapted Rust's generic types to C# equivalents
5. **Unsafe Code**: The P/Invoke declaration uses C#'s interop capabilities

### Design Decisions

1. **Types.cs**: Created wrapper structs for type safety (VertexIndex, EdgeIndex, Weight)
2. **PriorityQueue**: Implemented using SortedSet for simplicity (not the most performant, but correct)
3. **CompleteGraph**: Translated the full Dijkstra's algorithm implementation
4. **Tests**: Added comprehensive tests, most skipped by default due to native library requirement

## References

- Original Rust implementation: https://github.com/yuewuo/fusion-blossom/
- Blossom V paper: https://doi.org/10.1007/s12532-009-0002-8
- Blossom V library: https://pub.ist.ac.at/~vnk/software.html

## License

The C# translation follows the same license as the original fusion-blossom repository. Please refer to the original repository for licensing information.

Note: The Blossom V library itself has its own license which must be obtained separately from the authors.
