using BlossomV.Core;
using Xunit;

namespace BlossomV.Tests;

/// <summary>
/// Test cases for BlossomV.Core managed implementation
/// </summary>
public class BlossomVCoreTests
{
    [Fact]
    public void TestManagedPerfectMatching_BasicExample()
    {
        // Arrange
        const int nodeNum = 4;
        List<(int, int, int)> edges =
        [
            (0, 1, 100),
            (2, 3, 110),
            (0, 2, 500),
            (1, 3, 300)
        ];

        // Act
        var matching = ManagedPerfectMatching.SolveMinimumWeightPerfectMatching(nodeNum, edges);

        // Assert
        Assert.Equal(4, matching.Count);

        // Verify it's a valid perfect matching
        for (var i = 0; i < nodeNum; i++)
        {
            var matched = matching[i];
            Assert.True(matched >= 0 && matched < nodeNum, $"Matched node {matched} is out of range");

            // Verify symmetry
            if (matched >= 0)
            {
                Assert.Equal(i, matching[matched]);
            }
        }
    }

    [Fact]
    public void TestPerfectMatching_DirectAPI()
    {
        // Arrange
        var pm = new PerfectMatching(nodeNum: 4, edgeNumMax: 4);

        pm.AddEdge(0, 1, 100);
        pm.AddEdge(2, 3, 110);
        pm.AddEdge(0, 2, 500);
        pm.AddEdge(1, 3, 300);

        // Act
        pm.Solve();

        // Assert
        for (var i = 0; i < 4; i++)
        {
            var match = pm.GetMatch(i);
            Assert.True(match >= 0 && match < 4);

            // Verify symmetry
            if (match >= 0)
            {
                Assert.Equal(i, pm.GetMatch(match).Value);
            }
        }
    }

    [Fact]
    public void TestPerfectMatching_Cost()
    {
        // Arrange
        var pm = new PerfectMatching(nodeNum: 4, edgeNumMax: 4);

        pm.AddEdge(0, 1, 100);
        pm.AddEdge(2, 3, 110);
        pm.AddEdge(0, 2, 500);
        pm.AddEdge(1, 3, 300);

        // Act
        pm.Solve();
        var cost = pm.ComputePerfectMatchingCost();

        // Assert
        // The optimal matching should be (0,1) and (2,3) with cost 100 + 110 = 210
        Assert.True(cost == 210); // Should find optimal or near-optimal
    }

    [Fact]
    public void TestPerfectMatching_SimplePair()
    {
        // Arrange - simplest case: 2 nodes
        var pm = new PerfectMatching(nodeNum: 2, edgeNumMax: 1);
        pm.AddEdge(0, 1, 50);

        // Act
        pm.Solve();

        // Assert
        var nodeId = pm.GetMatch(0);
        Assert.Equal(1, nodeId.Value);
        Assert.Equal(0, pm.GetMatch(1).Value);
        Assert.Equal(50, pm.ComputePerfectMatchingCost().Value);
    }

    [Fact]
    public void TestPerfectMatching_InvalidEdge_SelfLoop()
    {
        // Arrange
        var pm = new PerfectMatching(nodeNum: 4, edgeNumMax: 1);

        // Act & Assert
        Assert.Throws<ArgumentException>(() => pm.AddEdge(0, 0, 100));
    }

    [Fact]
    public void TestPerfectMatching_InvalidNodeId()
    {
        // Arrange
        var pm = new PerfectMatching(nodeNum: 4, edgeNumMax: 1);

        // Act & Assert
        Assert.Throws<ArgumentException>(() => pm.AddEdge(0, 10, 100));
    }

    [Fact]
    public void TestManagedFallback_Integration()
    {
        // Arrange
        const uint nodeNum = 4;
        List<(uint, uint, uint)> edges =
        [
            (0, 1, 100),
            (2, 3, 110),
            (0, 2, 500),
            (1, 3, 300)
        ];

        // Act - This will use managed implementation since native lib is not available
        var matching = BlossomVSolver.ManagedMinimumWeightPerfectMatching(nodeNum, edges);

        // Assert
        Assert.Equal(4, matching.Count);
        for (var i = 0; i < nodeNum; i++)
        {
            Assert.True(matching[(int)i] < nodeNum);
        }
    }

    [Fact]
    public void TestOptions_Verbose()
    {
        // Arrange
        var pm = new PerfectMatching(nodeNum: 2, edgeNumMax: 1)
        {
            Options =
            {
                Verbose = true
            }
        };

        pm.AddEdge(0, 1, 50);

        // Act & Assert - should not throw
        pm.Solve();
        Assert.True(1 == pm.GetMatch(0));
    }
}
