using Xunit;

namespace BlossomV.Tests;

/// <summary>
/// Test cases for Blossom V algorithm
/// Translated from Rust tests in src/blossom_v.rs
/// </summary>
public class BlossomVTests
{
    /// <summary>
    /// Basic test for Blossom V algorithm
    /// Translated from blossom_v_test_1
    ///
    /// NOTE: This test will be skipped if the native Blossom V library is not available.
    /// To run this test, you need to:
    /// 1. Download Blossom V from https://pub.ist.ac.at/~vnk/software.html
    /// 2. Compile it as a shared library (blossomV.dll on Windows, libblossomV.so on Linux, libblossomV.dylib on macOS)
    /// 3. Place the library in the test output directory or in a system library path
    /// </summary>
    [Fact(Skip = "Requires native Blossom V library to be installed")]
    public void BlossomVTest1()
    {
        // Arrange
        uint nodeNum = 4;
        var edges = new List<(uint, uint, uint)>
        {
            (0, 1, 100),
            (2, 3, 110),
            (0, 2, 500),
            (1, 3, 300)
        };

        // Act
        var output = BlossomVSolver.SafeMinimumWeightPerfectMatching(nodeNum, edges);

        // Assert
        Assert.Equal(4, output.Count);
        Assert.Equal(1u, output[0]); // Vertex 0 matches with vertex 1
        Assert.Equal(0u, output[1]); // Vertex 1 matches with vertex 0
        Assert.Equal(3u, output[2]); // Vertex 2 matches with vertex 3
        Assert.Equal(2u, output[3]); // Vertex 3 matches with vertex 2

        // Verify it's a perfect matching
        for (int i = 0; i < nodeNum; i++)
        {
            var matched = (int)output[i];
            Assert.True(matched >= 0 && matched < nodeNum, $"Matched vertex {matched} is out of range");
            Assert.Equal(i, (int)output[matched]); // Symmetry check
        }
    }

    /// <summary>
    /// Test that duplicate edges are detected
    /// </summary>
    [Fact]
    public void TestDuplicateEdgeDetection()
    {
        // Arrange
        uint nodeNum = 4;
        var edges = new List<(uint, uint, uint)>
        {
            (0, 1, 100),
            (0, 1, 200), // Duplicate edge
            (2, 3, 110)
        };

        // Act & Assert
        #if DEBUG
        Assert.Throws<InvalidOperationException>(() =>
            BlossomVSolver.SafeMinimumWeightPerfectMatching(nodeNum, edges));
        #endif
    }

    /// <summary>
    /// Test that self-loops are detected
    /// </summary>
    [Fact]
    public void TestSelfLoopDetection()
    {
        // Arrange
        uint nodeNum = 4;
        var edges = new List<(uint, uint, uint)>
        {
            (0, 0, 100), // Self-loop
            (1, 2, 200)
        };

        // Act & Assert
        #if DEBUG
        Assert.Throws<InvalidOperationException>(() =>
            BlossomVSolver.SafeMinimumWeightPerfectMatching(nodeNum, edges));
        #endif
    }

    /// <summary>
    /// Test BlossomVMwpm with virtual vertices
    /// </summary>
    [Fact(Skip = "Requires native Blossom V library to be installed")]
    public void TestBlossomVMwpmWithVirtualVertices()
    {
        // Arrange
        var initializer = new SolverInitializer
        {
            VertexNum = 6,
            WeightedEdges = new List<(uint, uint, int)>
            {
                (0, 1, 100),
                (1, 2, 200),
                (2, 3, 150),
                (3, 4, 100),
                (0, 5, 50),  // Virtual vertex 5
                (4, 5, 50)
            },
            VirtualVertices = new List<uint> { 5 }
        };

        var defectVertices = new List<uint> { 0, 2, 4 }; // Odd number, needs virtual boundary

        // Act
        var result = BlossomVSolver.BlossomVMwpm(initializer, defectVertices);

        // Assert
        Assert.Equal(defectVertices.Count, result.Count);
        // Each defect vertex should be matched to something
        foreach (var match in result)
        {
            Assert.True(match < initializer.VertexNum);
        }
    }
}

/// <summary>
/// Test cases for CompleteGraph
/// </summary>
public class CompleteGraphTests
{
    [Fact]
    public void TestCompleteGraphCreation()
    {
        // Arrange
        uint vertexNum = 4;
        var edges = new List<(uint, uint, int)>
        {
            (0, 1, 100),
            (1, 2, 200),
            (2, 3, 150)
        };

        // Act
        var graph = new CompleteGraph(vertexNum, edges);

        // Assert
        Assert.Equal(vertexNum, graph.VertexNum);
        Assert.Equal(4, graph.Vertices.Count);
        Assert.Equal(100, graph.Vertices[0].Edges[1]);
        Assert.Equal(100, graph.Vertices[1].Edges[0]); // Symmetry
    }

    [Fact]
    public void TestCompleteGraphAllEdges()
    {
        // Arrange
        uint vertexNum = 4;
        var edges = new List<(uint, uint, int)>
        {
            (0, 1, 10),
            (1, 2, 20),
            (2, 3, 30),
            (0, 3, 100)
        };

        var graph = new CompleteGraph(vertexNum, edges);

        // Act - Find all edges from vertex 0
        var allEdges = graph.AllEdges(0);

        // Assert
        Assert.Contains(1u, allEdges.Keys); // Direct edge to 1
        Assert.Contains(2u, allEdges.Keys); // Path through 1
        Assert.Contains(3u, allEdges.Keys); // Direct edge to 3
    }

    [Fact]
    public void TestCompleteGraphReset()
    {
        // Arrange
        uint vertexNum = 3;
        var edges = new List<(uint, uint, int)>
        {
            (0, 1, 100),
            (1, 2, 200)
        };

        var graph = new CompleteGraph(vertexNum, edges);
        var erasures = new List<uint> { 0 }; // Erase first edge

        // Act
        graph.LoadErasures(erasures);
        Assert.Equal(0, graph.Vertices[0].Edges[1]); // Should be 0 after erasure

        graph.Reset();

        // Assert
        Assert.Equal(100, graph.Vertices[0].Edges[1]); // Should be restored
    }

    [Fact]
    public void TestGetPath()
    {
        // Arrange
        uint vertexNum = 4;
        var edges = new List<(uint, uint, int)>
        {
            (0, 1, 10),
            (1, 2, 20),
            (2, 3, 30)
        };

        var graph = new CompleteGraph(vertexNum, edges);

        // Act
        var (path, totalWeight) = graph.GetPath(0, 3);

        // Assert
        Assert.True(path.Count > 0);
        Assert.Equal(60, totalWeight); // 10 + 20 + 30
        Assert.Equal(3u, path[^1].Vertex); // Last vertex should be 3
    }
}

/// <summary>
/// Test cases for SolverInitializer
/// </summary>
public class SolverInitializerTests
{
    [Fact]
    public void TestSolverInitializerCreation()
    {
        // Arrange & Act
        var initializer = new SolverInitializer
        {
            VertexNum = 4,
            WeightedEdges = new List<(uint, uint, int)>
            {
                (0, 1, 100),
                (2, 3, 200)
            },
            VirtualVertices = new List<uint> { 3 }
        };

        // Assert
        Assert.Equal(4u, initializer.VertexNum);
        Assert.Equal(2, initializer.WeightedEdges.Count);
        Assert.Single(initializer.VirtualVertices);
        Assert.Equal(3u, initializer.VirtualVertices[0]);
    }
}

/// <summary>
/// Test cases for EdgeWeightModifier
/// </summary>
public class EdgeWeightModifierTests
{
    [Fact]
    public void TestEdgeWeightModifierPushPop()
    {
        // Arrange
        var modifier = new EdgeWeightModifier();

        // Act
        modifier.PushModifiedEdge(0, 100);
        modifier.PushModifiedEdge(1, 200);

        // Assert
        Assert.True(modifier.HasModifiedEdges());

        var (edgeIndex1, weight1) = modifier.PopModifiedEdge();
        Assert.Equal(1u, edgeIndex1);
        Assert.Equal(200, weight1);

        var (edgeIndex2, weight2) = modifier.PopModifiedEdge();
        Assert.Equal(0u, edgeIndex2);
        Assert.Equal(100, weight2);

        Assert.False(modifier.HasModifiedEdges());
    }

    [Fact]
    public void TestEdgeWeightModifierEmptyPop()
    {
        // Arrange
        var modifier = new EdgeWeightModifier();

        // Act & Assert
        Assert.Throws<InvalidOperationException>(() => modifier.PopModifiedEdge());
    }
}
