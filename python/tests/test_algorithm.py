"""Unit tests for maximum weight matching."""

import math
import unittest
from unittest.mock import Mock

from mwmatching import (
    maximum_weight_matching as mwm,
    adjust_weights_for_maximum_cardinality_matching as adj)
from mwmatching.algorithm import (
    MatchingError, GraphInfo, Blossom, NonTrivialBlossom, MatchingContext,
    verify_optimum)


class TestMaximumWeightMatching(unittest.TestCase):
    """Test maximum_weight_matching() function."""

    def test10_empty(self):
        """empty input graph"""
        self.assertEqual(mwm([]), [])

    def test11_singleedge(self):
        """single edge"""
        self.assertEqual(mwm([(0,1,1)]), [(0,1)])

    def test12(self):
        self.assertEqual(mwm([(1,2,10), (2,3,11)]), [(2,3)])

    def test13(self):
        self.assertEqual(
            mwm([(1,2,5), (2,3,11), (3,4,5)]),
            [(2,3)])

    def test15_float(self):
        """floating point weigths"""
        self.assertEqual(
            mwm([(1,2,3.1415), (2,3,2.7183), (1,3,3.0), (1,4,1.4142)]),
            [(2,3), (1,4)])

    def test16_negative(self):
        """negative weights"""
        self.assertEqual(
            mwm([(1,2,2), (1,3,-2), (2,3,1), (2,4,-1), (3,4,-6)]),
            [(1,2)])

    def test20_sblossom(self):
        """create S-blossom and use it for augmentation"""
        self.assertEqual(
            mwm([(1,2,8), (1,3,9), (2,3,10), (3,4,7)]),
            [(1,2), (3,4)])

    def test20a_sblossom(self):
        """create S-blossom and use it for augmentation"""
        self.assertEqual(
            mwm([(1,2,8), (1,3,9), (2,3,10), (3,4,7), (1,6,5), (4,5,6)]),
            [(2,3), (1,6), (4,5)])

    def test21_tblossom(self):
        """create S-blossom, relabel as T-blossom, use for augmentation"""
        self.assertEqual(
            mwm([(1,2,9), (1,3,8), (2,3,10), (1,4,5), (4,5,4), (1,6,3)]),
            [(2,3),(4,5),(1,6)])

    def test21a_tblossom(self):
        """create S-blossom, relabel as T-blossom, use for augmentation"""
        self.assertEqual(
            mwm([(1,2,9), (1,3,8), (2,3,10), (1,4,5), (4,5,3), (1,6,4)]),
            [(2,3), (4,5), (1,6)])

    def test21b_tblossom(self):
        """create S-blossom, relabel as T-blossom, use for augmentation"""
        self.assertEqual(
            mwm([(1,2,9), (1,3,8), (2,3,10), (1,4,5), (4,5,3), (3,6,4)]),
            [(1,2), (4,5), (3,6)])

    def test22_s_nest(self):
        """create nested S-blossom, use for augmentation"""
        self.assertEqual(
            mwm([(1,2,9), (1,3,9), (2,3,10), (2,4,8), (3,5,8), (4,5,10), (5,6,6)]),
            [(1,3), (2,4), (5,6)])

    def test23_s_relabel_nest(self):
        """create S-blossom, relabel as S, include in nested S-blossom"""
        self.assertEqual(
            mwm([(1,2,10), (1,7,10), (2,3,12), (3,4,20), (3,5,20), (4,5,25), (5,6,10), (6,7,10), (7,8,8)]),
            [(1,2), (3,4), (5,6), (7,8)])

    def test24_s_nest_expand(self):
        """create nested S-blossom, augment, expand recursively"""
        self.assertEqual(
            mwm([(1,2,8), (1,3,8), (2,3,10), (2,4,12), (3,5,12), (4,5,14), (4,6,12), (5,7,12), (6,7,14), (7,8,12)]),
            [(1,2), (3,5), (4,6), (7,8)])

    def test25_s_t_expand(self):
        """create S-blossom, relabel as T, expand"""
        self.assertEqual(
            mwm([(1,2,23), (1,5,22), (1,6,15), (2,3,25), (3,4,22), (4,5,25), (4,8,14), (5,7,13)]),
            [(1,6), (2,3), (4,8), (5,7)])

    def test26_s_nest_t_expand(self):
        """create nested S-blossom, relabel as T, expand"""
        self.assertEqual(
            mwm([(1,2,19), (1,3,20), (1,8,8), (2,3,25), (2,4,18), (3,5,18), (4,5,13), (4,7,7), (5,6,7)]),
            [(1,8), (2,3), (4,7), (5,6)])

    def test30_tnasty_expand(self):
        """create blossom, relabel as T in more than one way, expand, augment"""
        self.assertEqual(
            mwm([(1,2,45), (1,5,45), (2,3,50), (3,4,45), (4,5,50), (1,6,30), (3,9,35), (4,8,35), (5,7,26), (9,10,5)]),
            [(2,3), (1,6), (4,8), (5,7), (9,10)])

    def test31_tnasty2_expand(self):
        """again but slightly different"""
        self.assertEqual(
            mwm([(1,2,45), (1,5,45), (2,3,50), (3,4,45), (4,5,50), (1,6,30), (3,9,35), (4,8,26), (5,7,40), (9,10,5)]),
            [(2,3), (1,6), (4,8), (5,7), (9,10)])

    def test32_t_expand_leastslack(self):
        """create blossom, relabel as T, expand such that a new least-slack S-to-free edge is produced, augment"""
        self.assertEqual(
            mwm([(1,2,45), (1,5,45), (2,3,50), (3,4,45), (4,5,50), (1,6,30), (3,9,35), (4,8,28), (5,7,26), (9,10,5)]),
            [(2,3), (1,6), (4,8), (5,7), (9,10)])

    def test33_nest_tnasty_expand(self):
        """create nested blossom, relabel as T in more than one way, expand outer blossom such that inner blossom ends up on an augmenting path"""
        self.assertEqual(
            mwm([(1,2,45), (1,7,45), (2,3,50), (3,4,45), (4,5,95), (4,6,94), (5,6,94), (6,7,50), (1,8,30), (3,11,35), (5,9,36), (7,10,26), (11,12,5)]),
            [(2,3), (4,6), (1,8), (5,9), (7,10), (11,12)])

    def test34_nest_relabel_expand(self):
        """create nested S-blossom, relabel as S, expand recursively"""
        self.assertEqual(
            mwm([(1,2,40), (1,3,40), (2,3,60), (2,4,55), (3,5,55), (4,5,50), (1,8,15), (5,7,30), (7,6,10), (8,10,10), (4,9,30)]),
            [(1,2), (3,5), (7,6), (8,10), (4,9)])

    def test41_nonmax_card(self):
        """leave some nodes unmatched"""
        self.assertEqual(
            mwm([(0,1,2), (0,4,3), (1,2,7), (1,5,2), (2,3,9), (2,5,4), (3,4,8), (3,5,4)]),
            [(1,2), (3,4)])

    def test42_s_nest_partial_expand(self):
        """create nested S-blossom, augment, expand only outer"""
        #
        #    [0]--8--[1]--6--[3]--5--[5]
        #      \      |       |
        #       \     9       8
        #        8    |       |
        #         \--[2]--7--[4]
        #
        self.assertEqual(
            mwm([(0,1,8), (0,2,8), (1,2,9), (1,3,6), (2,4,7), (3,4,8), (3,5,5)]),
            [(0,1), (2,4), (3,5)])

    def test43_s_nest_noexpand(self):
        """leave nested S-blossom with inner zero dual"""
        #
        #    [1]--9--[2]
        #     |      /
        #     7  ___7
        #     | /
        #    [0]        [5]--2--[6]
        #     | \___
        #     7     7
        #     |      \
        #    [3]--9--[4]
        #
        self.assertEqual(
            mwm([(0,1,7), (0,2,7), (1,2,9), (0,3,7), (0,4,7), (3,4,9), (5,6,2)]),
            [(1,2), (3,4), (5,6)])

    def test44_blossom_redundant_edge(self):
        """drop redundant edge while making a blossom"""
        #
        #         [1]----9---[2]
        #        /            | \
        #       7             8  \
        #      /              |   1
        #    [0]--6--[4]--9--[3]   |
        #              \           |
        #               \----1----[5]
        #
        self.assertEqual(
            mwm([(0,1,7), (0,4,6), (1,2,9), (2,3,8), (3,4,9), (2,5,1), (4,5,1)]),
            [(1,2), (3,4)])

    def test45_flip_order(self):
        """test that order of edges and vertices is irrelevant"""
        edges = [(0,1,2), (0,4,3), (1,2,7), (1,5,1), (2,3,9), (2,5,4), (3,4,8), (3,5,4)]
        self.assertEqual(mwm(edges), [(1,2), (3,4)])
        self.assertEqual(mwm(list(reversed(edges))), [(3,4), (1,2)])
        self.assertEqual(mwm([(y, x, w) for (x, y, w) in edges]), [(2,1), (4,3)])
        edges = [(0,2,4), (0,3,4), (0,4,1), (1,2,8), (1,5,3), (2,3,9), (3,4,7), (4,5,2)]
        self.assertEqual(mwm(edges), [(1,2), (3,4)])

    def test46_expand_unlabeled_blossom(self):
        """expand blossom before assigning label T"""
        #
        #              3--[1]
        #             /    |
        #  [2]--1--[4]     7
        #             \    |
        #              5--[3]--5--[5]
        #
        self.assertIn(
            mwm([(1,3,7), (1,4,3), (2,4,1), (3,4,5), (3,5,5)]),
            ([(1,3), (2,4)], [(1,4), (3,5)]))

    def test47_expand_unlabeled_outer(self):
        """expand outer blossom before assigning label T"""
        #
        #  [3]--10--[1]--15--[2]--12--[5]
        #          _/  \_     |        |
        #        11      16_  8       15
        #       /           \ |        |
        #    [4]             [6]---7--[7]
        #
        self.assertEqual(
            mwm([(1,2,15), (1,3,10), (1,4,11), (1,6,17), (2,5,12), (2,6,8), (5,7,15), (6,7,7)]),
            [(1,4), (2,6), (5,7)])

    def test48_expand_unlabeled_nested(self):
        """expand nested blossom before assigning label T"""
        #
        #  [5]--11--[1]--11     14--[3]
        #            |     \   /     |
        #           12      [4]     14
        #            |     /   \     |
        #  [6]--11--[2]--12     11--[7]
        #
        self.assertEqual(
            mwm([(1,2,12), (1,4,11), (1,5,11), (2,4,12), (2,6,11), (3,4,14), (3,7,14), (4,7,11)]),
            [(1,5), (2,4), (3,7)])

    def test51_augment_blossom_nested(self):
        """augment nested blossoms with common base vertex"""
        #
        #               19--[1]--17--[4]--11--[7]
        #              /     |        |
        #  [3]--15--[2]     19       18
        #              \     |        |
        #               21--[5]--19--[6]
        #
        self.assertEqual(
            mwm([(1,2,19), (1,4,17), (1,5,19), (2,3,15), (2,5,21), (4,6,18), (4,7,11), (5,6,19)]),
            [(1,5), (2,3), (4,6)])

    def test52_augment_blossom_nested2(self):
        """augment nested blossoms"""
        #
        #   [4]--15     19--[2]
        #    |     \   /     |
        #   16      [1]     21
        #    |     /   \     |
        #   [5]--17     19--[3]
        #    |
        #   10
        #    |
        #   [6]
        #
        self.assertEqual(
            mwm([(1,2,19), (1,3,19), (1,4,15), (1,5,17), (2,3,21), (4,5,16), (5,6,10)]),
            [(1,4), (2,3), (5,6)])

    def test61_triangles_n9(self):
        """t.f 9 nodes"""
        #
        #  [1]------[4]      [7]
        #   | \      | \      | \
        #   |  [3]   |  [6]   |  [9]
        #   | /      | /      | /
        #  [2]      [5]------[8]
        #
        result = mwm([(1,2,1), (1,3,1), (2,3,1), (4,5,1), (4,6,1), (5,6,1), (7,8,1), (7,9,1), (8,9,1), (1,4,1), (5,8,1)])
        self.assertEqual(len(result), 4)

    def test_fail_bad_input(self):
        """bad input values"""
        with self.assertRaises(TypeError):
            mwm(15)
        with self.assertRaises(TypeError):
            mwm([15])
        with self.assertRaises((TypeError, ValueError)):
            mwm([(1,2)])
        with self.assertRaises(TypeError):
            mwm([(1.1, 2.5, 3)])
        with self.assertRaises(ValueError):
            mwm([(1, -2, 3)])
        with self.assertRaises(TypeError):
            mwm([(1, 2, "3")])
        with self.assertRaises(ValueError):
            mwm([(1, 2, math.inf)])
        with self.assertRaises(ValueError):
            mwm([(1, 2, 1e308)])

    def test_fail_bad_graph(self):
        """bad input graph structure"""
        with self.assertRaises(ValueError):
            mwm([(0, 1, 2), (1, 1, 1)])
        with self.assertRaises(ValueError):
            mwm([(0, 1, 2), (1, 2, 1), (2, 1, 1)])


class TestCornerCases(unittest.TestCase):
    """Test cases that would catch certain errors in the algorithm.

    These graphs were generated semi-automatically to fail when
    specific bugs are introduced in the code.
    """

    def test1(self):
        pairs = mwm([(0,4,26), (1,3,31), (1,4,49)])
        self.assertEqual(pairs, [(0,4), (1,3)])

    def test2(self):
        pairs = mwm([(0,2,42), (0,4,36), (2,3,26)])
        self.assertEqual(pairs, [(0,4), (2,3)])

    def test3(self):
        pairs = mwm([(0,4,43), (1,4,28), (2,4,38)])
        self.assertEqual(pairs, [(0,4)])

    def test4(self):
        pairs = mwm([(0,1,50), (0,3,46), (0,4,45)])
        self.assertEqual(pairs, [(0,1)])

    def test5(self):
        pairs = mwm([(0,1,35), (0,3,36), (0,4,46)])
        self.assertEqual(pairs, [(0,4)])

    def test6(self):
        pairs = mwm([(0,1,50), (0,4,51), (0,5,34), (1,2,43), (1,4,57), (2,5,47), (3,4,17)])
        self.assertEqual(pairs, [(0,1), (2,5), (3,4)])

    def test7(self):
        pairs = mwm([(0,1,34), (0,3,19), (1,2,45), (1,3,30), (1,4,37), (2,4,36)])
        self.assertEqual(pairs, [(0,1), (2,4)])

    def test8(self):
        pairs = mwm([(0,1,48), (0,3,42), (0,4,57), (1,3,51), (1,5,36), (2,3,23), (4,5,46)])
        self.assertEqual(pairs, [(0,1), (2,3), (4,5)])

    def test9(self):
        pairs = mwm([(0,1,21), (0,2,25), (0,5,42), (1,4,40), (2,3,10), (2,5,40), (3,5,31), (4,5,58)])
        self.assertEqual(pairs, [(0,2), (1,4), (3,5)])

    def test10(self):
        pairs = mwm([(0,2,7), (0,5,20), (1,2,50), (1,4,46), (2,3,35), (2,4,8), (2,5,25), (3,5,47)])
        self.assertEqual(pairs, [(0,5), (1,4), (2,3)])

    def test11(self):
        pairs = mwm([(0,1,42), (0,2,60), (1,3,34), (1,4,58), (1,5,52), (2,5,60), (3,5,34), (4,5,57)])
        self.assertEqual(pairs, [(0,2), (1,4), (3,5)])

    def test12(self):
        pairs = mwm([(0,1,23), (0,2,26), (0,3,22), (0,4,41), (2,4,36)])
        self.assertEqual(pairs, [(0,1), (2,4)])

    def test13(self):
        pairs = mwm([(0,3,58), (0,4,49), (1,5,34), (2,3,22), (2,5,42), (4,5,36)])
        self.assertEqual(pairs, [(0,4), (1,5), (2,3)])

    def test14(self):
        pairs = mwm([(0,1,29), (0,3,35), (0,4,42), (1,2,12), (2,4,29), (3,4,44)])
        self.assertEqual(pairs, [(0,1), (3,4)])

    def test15(self):
        pairs = mwm([(0,4,53), (0,5,42), (1,4,45), (2,4,59), (2,6,39), (4,5,69), (4,6,52)])
        self.assertEqual(pairs, [(0,5), (1,4), (2,6)])

    def test16(self):
        pairs = mwm([(0,2,13), (1,2,11), (2,3,39), (2,4,17), (3,4,35)])
        self.assertEqual(pairs, [(0,2), (3,4)])

    def test17(self):
        pairs = mwm([(0,1,48), (0,2,44), (0,4,48), (1,4,36), (3,4,31)])
        self.assertEqual(pairs, [(0,2), (1,4)])


class TestAdjustWeightForMaxCardinality(unittest.TestCase):
    """Test adjust_weights_for_maximum_cardinality_matching() function."""

    def test_empty(self):
        self.assertEqual(adj([]), [])

    def test_chain(self):
        self.assertEqual(
            adj([(0,1,2), (1,2,8), (2,3,3), (3,4,9), (4,5,1), (5,6,7), (6,7,4)]),
            [(0,1,65), (1,2,71), (2,3,66), (3,4,72), (4,5,64), (5,6,70), (6,7,67)])

    def test_chain_preadjusted(self):
        self.assertEqual(
            adj([(0,1,65), (1,2,71), (2,3,66), (3,4,72), (4,5,64), (5,6,70), (6,7,67)]),
            [(0,1,65), (1,2,71), (2,3,66), (3,4,72), (4,5,64), (5,6,70), (6,7,67)])

    def test_flat(self):
        self.assertEqual(
            adj([(0,1,0), (0,4,0), (1,2,0), (1,5,0), (2,3,0), (2,5,0), (3,4,0), (3,5,0)]),
            [(0,1,1), (0,4,1), (1,2,1), (1,5,1), (2,3,1), (2,5,1), (3,4,1), (3,5,1)])

    def test14_maxcard(self):
        self.assertEqual(
            adj([(1,2,5), (2,3,11), (3,4,5)]),
            [(1,2,30), (2,3,36), (3,4,30)])

    def test16_negative(self):
        self.assertEqual(
            adj([(1,2,2), (1,3,-2), (2,3,1), (2,4,-1), (3,4,-6)]),
            [(1,2,48), (1,3,44), (2,3,47), (2,4,45), (3,4,40)])


class TestMaximumCardinalityMatching(unittest.TestCase):
    """Test maximum cardinality matching."""

    def test14_maxcard(self):
        """maximum cardinality"""
        self.assertEqual(
            mwm(adj([(1,2,5), (2,3,11), (3,4,5)])),
            [(1,2), (3,4)])

    def test16_negative(self):
        """negative weights"""
        self.assertEqual(
            mwm(adj([(1,2,2), (1,3,-2), (2,3,1), (2,4,-1), (3,4,-6)])),
            [(1,3), (2,4)])

    def test43_maxcard(self):
        """maximum cardinality"""
        self.assertIn(
            mwm(adj([(0,1,2), (0,4,3), (1,2,7), (1,5,2), (2,3,9), (2,5,4), (3,4,8), (3,5,4)])),
            ([(0,1), (2,5), (3,4)],
             [(0,4), (1,2), (3,5)]))


class TestGraphInfo(unittest.TestCase):
    """Test GraphInfo helper class."""

    def test_empty(self):
        graph = GraphInfo([])
        self.assertEqual(graph.num_vertex, 0)
        self.assertEqual(graph.edges, [])
        self.assertEqual(graph.adjacent_edges, [])


class TestVerificationFail(unittest.TestCase):
    """Test failure handling in verification routine."""

    def _make_context(
            self,
            edges,
            vertex_mate,
            vertex_dual_2x,
            nontrivial_blossom):
        ctx = Mock(spec=MatchingContext)
        ctx.graph = GraphInfo(edges)
        ctx.vertex_mate = vertex_mate
        ctx.vertex_dual_2x = vertex_dual_2x
        ctx.nontrivial_blossom = nontrivial_blossom
        return ctx

    def test_success(self):
        edges = [(0,1,10), (1,2,11)]
        ctx = self._make_context(
            edges,
            vertex_mate=[-1, 2, 1],
            vertex_dual_2x=[0, 20, 2],
            nontrivial_blossom=[])
        verify_optimum(ctx)

    def test_asymmetric_matching(self):
        edges = [(0,1,10), (1,2,11)]
        ctx = self._make_context(
            edges,
            vertex_mate=[-1, 2, 0],
            vertex_dual_2x=[0, 20, 2],
            nontrivial_blossom=[])
        with self.assertRaises(MatchingError):
            verify_optimum(ctx)

    def test_nonexistent_matched_edge(self):
        edges = [(0,1,10), (1,2,11)]
        ctx = self._make_context(
            edges,
            vertex_mate=[2, -1, 0],
            vertex_dual_2x=[11, 11, 11],
            nontrivial_blossom=[])
        with self.assertRaises(MatchingError):
            verify_optimum(ctx)

    def test_negative_vertex_dual(self):
        edges = [(0,1,10), (1,2,11)]
        ctx = self._make_context(
            edges,
            vertex_mate=[-1, 2, 1],
            vertex_dual_2x=[-2, 22, 0],
            nontrivial_blossom=[])
        with self.assertRaises(MatchingError):
            verify_optimum(ctx)

    def test_unmatched_nonzero_dual(self):
        edges = [(0,1,10), (1,2,11)]
        ctx = self._make_context(
            edges,
            vertex_mate=[-1, 2, 1],
            vertex_dual_2x=[9, 11, 11],
            nontrivial_blossom=[])
        with self.assertRaises(MatchingError):
            verify_optimum(ctx)

    def test_negative_edge_slack(self):
        edges = [(0,1,10), (1,2,11)]
        ctx = self._make_context(
            edges,
            vertex_mate=[-1, 2, 1],
            vertex_dual_2x=[0, 11, 11],
            nontrivial_blossom=[])
        with self.assertRaises(MatchingError):
            verify_optimum(ctx)

    def test_matched_edge_slack(self):
        edges = [(0,1,10), (1,2,11)]
        ctx = self._make_context(
            edges,
            vertex_mate=[-1, 2, 1],
            vertex_dual_2x=[0, 20, 11],
            nontrivial_blossom=[])
        with self.assertRaises(MatchingError):
            verify_optimum(ctx)

    def test_negative_blossom_dual(self):
        #
        # [0]--7--[1]--9--[2]--6--[3]
        #   \            /
        #    \----8-----/
        #
        edges = [(0,1,7), (0,2,8), (1,2,9), (2,3,6)]
        blossom = NonTrivialBlossom(
            subblossoms=[Blossom(0), Blossom(1), Blossom(2)],
            edges=[0,2,1])
        for sub in blossom.subblossoms:
            sub.parent = blossom
        blossom.dual_var = -1
        ctx = self._make_context(
            edges,
            vertex_mate=[1, 0, 3, 2],
            vertex_dual_2x=[4, 6, 8, 4],
            nontrivial_blossom=[blossom])
        with self.assertRaises(MatchingError):
            verify_optimum(ctx)

    def test_blossom_not_full(self):
        #
        # [3]     [4]
        #  |       |
        #  8       8
        #  |       |
        # [0]--7--[1]--5--[2]
        #   \            /
        #    \----2-----/
        #
        edges = [(0,1,7), (0,2,2), (1,2,5), (0,3,8), (1,4,8)]
        blossom = NonTrivialBlossom(
            subblossoms=[Blossom(0), Blossom(1), Blossom(2)],
            edges=[0,2,1])
        for sub in blossom.subblossoms:
            sub.parent = blossom
        blossom.dual_var = 2
        ctx = self._make_context(
            edges,
            vertex_mate=[3, 4, -1, 0, 1],
            vertex_dual_2x=[4, 10, 0, 12, 6],
            nontrivial_blossom=[blossom])
        with self.assertRaises(MatchingError):
            verify_optimum(ctx)


class TestValueRange(unittest.TestCase):
    """Test graphs that force big values for dual variables or edge slack."""

    def test_big_blossom_dual(self):
        """Force modified blossom dual close to 2*maxweight."""
        #
        #              [3]
        #              / \
        #          W-4/   \W
        #      7     /     \
        #  [1]-----[2]-----[4]
        #          |   W-4
        #         5|
        #          |   1
        #         [5]-----[6]
        #
        w = 100000
        pairs = mwm([(1,2,7), (2,3,w-4), (2,4,w-4), (2,5,5), (3,4,w), (5,6,1)])
        self.assertEqual(pairs, [(1,2), (3,4), (5,6)])

    def test_negative_blossom_dual(self):
        """Force modified blossom dual close to -maxweight."""
        #
        #              [3]
        #              / \
        #            5/   \7
        #       1    /     \
        #  [1]-----[2]-----[4]
        #           |   5
        #          1|
        #           |   W
        #          [5]-----[6]
        #
        w = 100000
        pairs = mwm([(1,2,1), (2,3,5), (2,4,5), (2,5,1), (3,4,7), (5,6,w)])
        self.assertEqual(pairs, [(1,2), (3,4), (5,6)])

    def test_big_edge_slack(self):
        """Force modified edge slack close to 3*maxweight."""
        #
        #      6       W      W-2      5
        # [1]-----[2]-----[3]-----[4]-----[5]
        #  |               |
        #  |1              |1
        #  |               |
        # [6]-----[7]-----[8]-----[9]-----[10]
        #      6       W      W-2      5
        #
        w = 100000
        pairs = mwm([(1,2,6), (1,6,1), (2,3,w), (3,4,w-2), (3,8,1), (4,5,5),
                     (6,7,6), (7,8,w), (8,9,w-2), (9,10,5)])
        self.assertEqual(pairs, [(1,6), (2,3), (4,5), (7,8), (9,10)])


if __name__ == "__main__":
    unittest.main()

