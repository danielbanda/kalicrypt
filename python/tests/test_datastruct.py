"""Unit tests for data structures."""

import random
import unittest

from mwmatching.datastruct import ConcatenableQueue, PriorityQueue


class TestConcatenableQueue(unittest.TestCase):
    """Test ConcatenableQueue."""

    def _check_tree(self, queue):
        """Check tree balancing rules and priority info."""

        self.assertIsNone(queue.tree.parent)
        self.assertIs(queue.tree.owner, queue)

        nodes = [queue.tree]
        while nodes:

            node = nodes.pop()

            if node is not queue.tree:
                self.assertIsNone(node.owner)

            if node.height == 0:
                self.assertEqual(len(node.childs), 0)
                self.assertIs(node.min_node, node)
            else:
                self.assertIn(len(node.childs), (2, 3))
                best_node = set()
                best_prio = None
                for child in node.childs:
                    self.assertIs(child.parent, node)
                    self.assertEqual(child.height, node.height - 1)
                    nodes.append(child)
                    if ((best_prio is None)
                            or (child.min_node.prio < best_prio)):
                        best_node = {child.min_node}
                        best_prio = child.min_node.prio
                    elif child.min_node.prio == best_prio:
                        best_node.add(child.min_node)

                self.assertEqual(node.min_node.prio, best_prio)
                self.assertIn(node.min_node, best_node)

    def test_single(self):
        """Single element."""
        q = ConcatenableQueue("Q")

        with self.assertRaises(Exception):
            q.min_prio()

        with self.assertRaises(Exception):
            q.min_elem()

        n = q.insert("a", 4)
        self.assertIsInstance(n, ConcatenableQueue.Node)

        self._check_tree(q)

        self.assertEqual(n.find(), "Q")
        self.assertEqual(q.min_prio(), 4)
        self.assertEqual(q.min_elem(), "a")

        with self.assertRaises(Exception):
            q.insert("x", 1)

        n.set_prio(8)
        self._check_tree(q)

        self.assertEqual(n.find(), "Q")
        self.assertEqual(q.min_prio(), 8)
        self.assertEqual(q.min_elem(), "a")

        q.clear()

    def test_simple(self):
        """Simple test, 5 elements."""
        q1 = ConcatenableQueue("A")
        n1 = q1.insert("a", 5)

        q2 = ConcatenableQueue("B")
        n2 = q2.insert("b", 6)

        q3 = ConcatenableQueue("C")
        n3 = q3.insert("c", 7)

        q4 = ConcatenableQueue("D")
        n4 = q4.insert("d", 4)

        q5 = ConcatenableQueue("E")
        n5 = q5.insert("e", 3)

        q345 = ConcatenableQueue("P")
        q345.merge([q3, q4, q5])
        self._check_tree(q345)

        self.assertEqual(n1.find(), "A")
        self.assertEqual(n3.find(), "P")
        self.assertEqual(n4.find(), "P")
        self.assertEqual(n5.find(), "P")
        self.assertEqual(q345.min_prio(), 3)
        self.assertEqual(q345.min_elem(), "e")

        with self.assertRaises(Exception):
            q3.min_prio()

        self._check_tree(q345)
        n5.set_prio(6)
        self._check_tree(q345)

        self.assertEqual(q345.min_prio(), 4)
        self.assertEqual(q345.min_elem(), "d")

        q12 = ConcatenableQueue("Q")
        q12.merge([q1, q2])
        self._check_tree(q12)

        self.assertEqual(n1.find(), "Q")
        self.assertEqual(n2.find(), "Q")
        self.assertEqual(q12.min_prio(), 5)
        self.assertEqual(q12.min_elem(), "a")

        q12345 = ConcatenableQueue("R")
        q12345.merge([q12, q345])
        self._check_tree(q12345)

        self.assertEqual(n1.find(), "R")
        self.assertEqual(n2.find(), "R")
        self.assertEqual(n3.find(), "R")
        self.assertEqual(n4.find(), "R")
        self.assertEqual(n5.find(), "R")
        self.assertEqual(q12345.min_prio(), 4)
        self.assertEqual(q12345.min_elem(), "d")

        n4.set_prio(8)
        self._check_tree(q12345)

        self.assertEqual(q12345.min_prio(), 5)
        self.assertEqual(q12345.min_elem(), "a")

        n3.set_prio(2)
        self._check_tree(q12345)

        self.assertEqual(q12345.min_prio(), 2)
        self.assertEqual(q12345.min_elem(), "c")

        q12345.split()
        self._check_tree(q12)
        self._check_tree(q345)

        self.assertEqual(n1.find(), "Q")
        self.assertEqual(n2.find(), "Q")
        self.assertEqual(n3.find(), "P")
        self.assertEqual(n4.find(), "P")
        self.assertEqual(n5.find(), "P")
        self.assertEqual(q12.min_prio(), 5)
        self.assertEqual(q12.min_elem(), "a")
        self.assertEqual(q345.min_prio(), 2)
        self.assertEqual(q345.min_elem(), "c")

        q12.split()
        self._check_tree(q1)
        self._check_tree(q2)

        q345.split()
        self._check_tree(q3)
        self._check_tree(q4)
        self._check_tree(q5)

        self.assertEqual(n1.find(), "A")
        self.assertEqual(n2.find(), "B")
        self.assertEqual(n3.find(), "C")
        self.assertEqual(n4.find(), "D")
        self.assertEqual(n5.find(), "E")
        self.assertEqual(q3.min_prio(), 2)
        self.assertEqual(q3.min_elem(), "c")

        q1.clear()
        q2.clear()
        q3.clear()
        q4.clear()
        q5.clear()
        q12.clear()
        q345.clear()
        q12345.clear()

    def test_medium(self):
        """Medium test, 14 elements."""

        prios = [3, 8, 6, 2, 9, 4, 6, 8, 1, 5, 9, 4, 7, 8]

        queues = []
        nodes = []
        for i in range(14):
            q = ConcatenableQueue(chr(ord("A") + i))
            n = q.insert(chr(ord("a") + i), prios[i])
            queues.append(q)
            nodes.append(n)

        q = ConcatenableQueue("AB")
        q.merge(queues[0:2])
        queues.append(q)
        self._check_tree(q)
        self.assertEqual(q.min_prio(), min(prios[0:2]))

        q = ConcatenableQueue("CDE")
        q.merge(queues[2:5])
        queues.append(q)
        self._check_tree(q)
        self.assertEqual(q.min_prio(), min(prios[2:5]))

        q = ConcatenableQueue("FGHI")
        q.merge(queues[5:9])
        queues.append(q)
        self._check_tree(q)
        self.assertEqual(q.min_prio(), min(prios[5:9]))

        q = ConcatenableQueue("JKLMN")
        q.merge(queues[9:14])
        queues.append(q)
        self._check_tree(q)
        self.assertEqual(q.min_prio(), min(prios[9:14]))

        for i in range(0, 2):
            self.assertEqual(nodes[i].find(), "AB")
        for i in range(2, 5):
            self.assertEqual(nodes[i].find(), "CDE")
        for i in range(5, 9):
            self.assertEqual(nodes[i].find(), "FGHI")
        for i in range(9, 14):
            self.assertEqual(nodes[i].find(), "JKLMN")

        q = ConcatenableQueue("ALL")
        q.merge(queues[14:18])
        queues.append(q)
        self._check_tree(q)
        self.assertEqual(q.min_prio(), 1)
        self.assertEqual(q.min_elem(), "i")

        for i in range(14):
            self.assertEqual(nodes[i].find(), "ALL")

        prios[8] = 5
        nodes[8].set_prio(prios[8])
        self.assertEqual(q.min_prio(), 2)
        self.assertEqual(q.min_elem(), "d")

        q.split()

        for i in range(0, 2):
            self.assertEqual(nodes[i].find(), "AB")
        for i in range(2, 5):
            self.assertEqual(nodes[i].find(), "CDE")
        for i in range(5, 9):
            self.assertEqual(nodes[i].find(), "FGHI")
        for i in range(9, 14):
            self.assertEqual(nodes[i].find(), "JKLMN")

        self.assertEqual(queues[14].min_prio(), min(prios[0:2]))
        self.assertEqual(queues[15].min_prio(), min(prios[2:5]))
        self.assertEqual(queues[16].min_prio(), min(prios[5:9]))
        self.assertEqual(queues[17].min_prio(), min(prios[9:14]))

        for q in queues[14:18]:
            self._check_tree(q)
            q.split()

        for i in range(14):
            self._check_tree(queues[i])
            self.assertEqual(nodes[i].find(), chr(ord("A") + i))
            self.assertEqual(queues[i].min_prio(), prios[i])
            self.assertEqual(queues[i].min_elem(), chr(ord("a") + i))

        for q in queues:
            q.clear()

    def test_random(self):
        """Pseudo-random test."""

        rng = random.Random(23456)

        nodes = []
        prios = []
        queues = {}
        queue_nodes = {}
        queue_subs = {}
        live_queues = set()
        live_merged_queues = set()

        for i in range(4000):
            name = f"q{i}"
            q = ConcatenableQueue(name)
            p = rng.random()
            n = q.insert(f"n{i}", p)
            nodes.append(n)
            prios.append(p)
            queues[name] = q
            queue_nodes[name] = {i}
            live_queues.add(name)

        for i in range(2000):

            for k in range(10):
                t = rng.randint(0, len(nodes) - 1)
                name = nodes[t].find()
                self.assertIn(name, live_queues)
                self.assertIn(t, queue_nodes[name])
                p = rng.random()
                prios[t] = p
                nodes[t].set_prio(p)
                pp = min(prios[tt] for tt in queue_nodes[name])
                tt = prios.index(pp)
                self.assertEqual(queues[name].min_prio(), pp)
                self.assertEqual(queues[name].min_elem(), f"n{tt}")

            k = rng.randint(2, max(2, len(live_queues) // 2 - 400))
            subs = rng.sample(sorted(live_queues), k)

            name = f"Q{i}"
            q = ConcatenableQueue(name)
            q.merge([queues[nn] for nn in subs])
            self._check_tree(q)
            queues[name] = q
            queue_nodes[name] = set().union(*(queue_nodes[nn] for nn in subs))
            queue_subs[name] = set(subs)
            live_queues.difference_update(subs)
            live_merged_queues.difference_update(subs)
            live_queues.add(name)
            live_merged_queues.add(name)

            pp = min(prios[tt] for tt in queue_nodes[name])
            tt = prios.index(pp)
            self.assertEqual(q.min_prio(), pp)
            self.assertEqual(q.min_elem(), f"n{tt}")

            if len(live_merged_queues) >= 100:
                name = rng.choice(sorted(live_merged_queues))
                queues[name].split()

                for nn in queue_subs[name]:
                    self._check_tree(queues[nn])
                    pp = min(prios[tt] for tt in queue_nodes[nn])
                    tt = prios.index(pp)
                    self.assertEqual(queues[nn].min_prio(), pp)
                    self.assertEqual(queues[nn].min_elem(), f"n{tt}")
                    live_queues.add(nn)
                    if nn in queue_subs:
                        live_merged_queues.add(nn)

                live_merged_queues.remove(name)
                live_queues.remove(name)

                del queues[name]
                del queue_nodes[name]
                del queue_subs[name]

        for q in queues.values():
            q.clear()


class TestPriorityQueue(unittest.TestCase):
    """Test PriorityQueue."""

    def test_empty(self):
        """Empty queue."""
        q = PriorityQueue()
        self.assertTrue(q.empty())
        with self.assertRaises(IndexError):
            q.find_min()

    def test_single(self):
        """Single element."""
        q = PriorityQueue()

        n1 = q.insert(5, "a")
        self.assertEqual(n1.prio, 5)
        self.assertEqual(n1.data, "a")
        self.assertFalse(q.empty())
        self.assertIs(q.find_min(), n1)

        q.decrease_prio(n1, 3)
        self.assertEqual(n1.prio, 3)
        self.assertIs(q.find_min(), n1)

        q.delete(n1)
        self.assertTrue(q.empty())

    def test_simple(self):
        """A few elements."""
        prios = [9, 4, 7, 5, 8, 6, 4, 5, 2, 6]
        labels = "abcdefghij"

        q = PriorityQueue()

        elems = [q.insert(prio, data) for (prio, data) in zip(prios, labels)]
        for (n, prio, data) in zip(elems, prios, labels):
            self.assertEqual(n.prio, prio)
            self.assertEqual(n.data, data)

        self.assertIs(q.find_min(), elems[8])

        q.decrease_prio(elems[2], 1)
        self.assertIs(q.find_min(), elems[2])

        q.decrease_prio(elems[4], 3)
        self.assertIs(q.find_min(), elems[2])

        q.delete(elems[2])
        self.assertIs(q.find_min(), elems[8])

        q.delete(elems[8])
        self.assertIs(q.find_min(), elems[4])

        q.delete(elems[4])
        q.delete(elems[1])
        self.assertIs(q.find_min(), elems[6])

        q.delete(elems[3])
        q.delete(elems[9])
        self.assertIs(q.find_min(), elems[6])

        q.delete(elems[6])
        self.assertIs(q.find_min(), elems[7])

        q.delete(elems[7])
        self.assertIs(q.find_min(), elems[5])

        self.assertFalse(q.empty())
        q.clear()
        self.assertTrue(q.empty())

    def test_increase_prio(self):
        """Increase priority of existing element."""

        q = PriorityQueue()

        n1 = q.insert(5, "a")
        q.increase_prio(n1, 8)
        self.assertEqual(n1.prio, 8)
        self.assertIs(q.find_min(), n1)

        q = PriorityQueue()
        n1 = q.insert(9, "a")
        n2 = q.insert(4, "b")
        n3 = q.insert(7, "c")
        n4 = q.insert(5, "d")
        self.assertIs(q.find_min(), n2)

        q.increase_prio(n2, 8)
        self.assertEqual(n2.prio, 8)
        self.assertIs(q.find_min(), n4)

        q.increase_prio(n3, 10)
        self.assertEqual(n3.prio, 10)
        self.assertIs(q.find_min(), n4)

        q.delete(n4)
        self.assertIs(q.find_min(), n2)

        q.delete(n2)
        self.assertIs(q.find_min(), n1)

        q.delete(n1)
        self.assertIs(q.find_min(), n3)
        self.assertEqual(n3.prio, 10)

        q.delete(n3)
        self.assertTrue(q.empty())

    def test_random(self):
        """Pseudo-random test."""
        rng = random.Random(34567)

        num_elem = 1000

        seq = 0
        elems = []
        q = PriorityQueue()

        def check():
            min_prio = min(prio for (n, prio, data) in elems)
            m = q.find_min()
            self.assertIn((m, m.prio, m.data), elems)
            self.assertEqual(m.prio, min_prio)

        for i in range(num_elem):
            seq += 1
            prio = rng.randint(0, 1000000)
            elems.append((q.insert(prio, seq), prio, seq))
            check()

        for i in range(10000):
            p = rng.randint(0, num_elem - 1)
            prio = rng.randint(0, 1000000)
            if prio <= elems[p][1]:
                q.decrease_prio(elems[p][0], prio)
            else:
                q.increase_prio(elems[p][0], prio)
            elems[p] = (elems[p][0], prio, elems[p][2])
            check()

            p = rng.randint(0, num_elem - 1)
            q.delete(elems[p][0])
            elems.pop(p)
            check()

            seq += 1
            prio = rng.randint(0, 1000000)
            elems.append((q.insert(prio, seq), prio, seq))
            check()

        for i in range(num_elem):
            p = rng.randint(0, num_elem - 1 - i)
            q.delete(elems[p][0])
            elems.pop(p)
            if elems:
                check()

        self.assertTrue(q.empty())


if __name__ == "__main__":
    unittest.main()
