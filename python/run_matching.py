#!/usr/bin/env python3

"""
Calculate maximum weighted matching of graphs in DIMACS format.
"""

from __future__ import annotations

import sys
import argparse
import math
import os
import os.path
from collections.abc import Sequence
from typing import Optional, TextIO

from mwmatching import (maximum_weight_matching,
                        adjust_weights_for_maximum_cardinality_matching)


def parse_int_or_float(s: str) -> float:
    """Convert a string to integer or float value."""
    try:
        return int(s)
    except ValueError:
        pass
    return float(s)


def read_dimacs_graph(f: TextIO) -> list[tuple[int, int, float]]:
    """Read a graph in DIMACS edge list format."""

    edges: list[tuple[int, int, float]] = []

    for line in f:
        s = line.strip()
        words = s.split()

        if not words[0]:
            # Skip empty line.
            continue

        if words[0].startswith("c"):
            # Skip comment line.
            pass

        elif words[0] == "p":
            # Handle "problem" line.
            if len(words) != 4:
                raise ValueError(
                    f"Expecting DIMACS edge format but got {s!r}")
            if words[1] != "edge":
                raise ValueError(
                    f"Expecting DIMACS edge format but got {words[1]!r}")

        elif words[0] == "e":
            # Handle "edge" line.
            if len(words) != 4:
                raise ValueError(f"Expecting edge but got {s!r}")
            x = int(words[1])
            y = int(words[2])
            if (x < 1) or (y < 1):
                raise ValueError(f"Invalid vertex index {s!r}")
            w = parse_int_or_float(words[3])
            edges.append((x - 1, y - 1, w))

        else:
            raise ValueError(f"Unknown line type {words[0]!r}")

    return edges


def read_dimacs_graph_file(filename: str) -> list[tuple[int, int, float]]:
    """Read a graph from file or stdin."""
    if filename:
        with open(filename, "r", encoding="ascii") as f:
            try:
                return read_dimacs_graph(f)
            except ValueError as exc:
                raise ValueError(f"{exc} in {filename!r}") from None
    else:
        try:
            return read_dimacs_graph(sys.stdin)
        except ValueError as exc:
            raise ValueError(f"{exc} in (stdin)") from None


def read_dimacs_matching(
        f: TextIO
        ) -> tuple[float, list[tuple[int, int]]]:
    """Read a matching solution in DIMACS format."""

    have_weight = False
    weight: float = 0
    pairs: list[tuple[int, int]] = []

    for line in f:
        s = line.strip()
        words = s.split()

        if not words[0]:
            # Skip empty line.
            continue

        if words[0].startswith("c"):
            # Skip comment line.
            pass

        elif words[0] == "s":
            # Handle "solution" line.
            if len(words) != 2:
                raise ValueError(
                    f"Expecting solution line but got {s!r}")
            if have_weight:
                raise ValueError("Duplicate solution line")
            have_weight = True
            weight = parse_int_or_float(words[1])

        elif words[0] == "m":
            # Handle "matching" line.
            if len(words) != 3:
                raise ValueError(
                    f"Expecting matched edge but got {s!r}")
            x = int(words[1])
            y = int(words[2])
            if (x < 1) or (y < 1):
                raise ValueError(f"Invalid vertex index {s!r}")
            pairs.append((x - 1, y - 1))

        else:
            raise ValueError(f"Unknown line type {words[0]!r}")

    if not have_weight:
        raise ValueError("Missing solution line")

    return (weight, pairs)


def read_dimacs_matching_file(
        filename: str
        ) -> tuple[float, list[tuple[int, int]]]:
    """Read a matching from file."""
    with open(filename, "r", encoding="ascii") as f:
        try:
            return read_dimacs_matching(f)
        except ValueError as exc:
            raise ValueError(f"{exc} in {filename!r}") from None


def write_dimacs_matching(
        f: TextIO,
        weight: float,
        pairs: list[tuple[int, int]]
        ) -> None:
    """Write a matching solution in DIMACS format."""

    if isinstance(weight, int):
        print("s", weight, file=f)
    else:
        print("s", f"{weight:.12g}", file=f)

    for (x, y) in pairs:
        print("m", x + 1, y + 1, file=f)


def write_dimacs_matching_file(
        filename: str,
        weight: float,
        pairs: list[tuple[int, int]]
        ) -> None:
    """Write a matching to file or stdout."""
    if filename:
        with open(filename, "x", encoding="ascii") as f:
            write_dimacs_matching(f, weight, pairs)
    else:
        write_dimacs_matching(sys.stdout, weight, pairs)


def calc_matching_weight(
        edges: list[tuple[int, int, float]],
        pairs: list[tuple[int, int]]
        ) -> float:
    """Verify that the matching is valid and calculate its weight.

    Matched pairs are assumed to be in the same order as edges.
    """

    weight: float = 0

    edge_pos = 0
    for pair in pairs:
        while edge_pos < len(edges):
            if edges[edge_pos][0:2] == pair:
                break
            edge_pos += 1
        assert edge_pos <= len(edges)
        (x, y, w) = edges[edge_pos]
        assert pair == (x, y)
        weight += w
        edge_pos += 1

    return weight


def generate_matching(
        input_filename: str,
        output_filename: str,
        maxcard: bool
        ) -> None:
    """Calculate matching of one graph instance."""

    edges = read_dimacs_graph_file(input_filename)

    if maxcard:
        edges_adj = adjust_weights_for_maximum_cardinality_matching(edges)
        pairs = maximum_weight_matching(edges_adj)
    else:
        pairs = maximum_weight_matching(edges)

    weight = calc_matching_weight(edges, pairs)

    write_dimacs_matching_file(output_filename, weight, pairs)


def run_generate(
        filenames: list[str],
        outdir: Optional[str],
        maxcard: bool
        ) -> int:
    """Calculate matching(s) and write output to disk or stdout."""

    if len(filenames) == 0:
        # Read from stdin; write to stdout.
        generate_matching("", "", maxcard)

    elif not outdir:
        # Read from file, write to stdout.
        assert len(filenames) == 1
        generate_matching(filenames[0], "", maxcard)

    else:
        # Read from file, write to file.
        for filename in filenames:
            output_filename = os.path.join(
                outdir,
                os.path.splitext(os.path.basename(filename))[0] + ".out")
            print(f"Processing {filename!r} -> {output_filename!r} ...",
                  end=" ")
            sys.stdout.flush()

            generate_matching(filename, output_filename, maxcard)

            print(" OK")
            sys.stdout.flush()

    return 0


def verify_matching(filename: str, maxcard: bool, wfactor: float) -> bool:
    """Verify matching of one graph instance."""

    print("Verifying", repr(filename), "...", end=" ")
    sys.stdout.flush()

    matching_filename = os.path.splitext(filename)[0] + ".out"

    edges = read_dimacs_graph_file(filename)
    (gold_weight, gold_pairs) = read_dimacs_matching_file(matching_filename)

    edges_adj: Sequence[tuple[int, int, float]] = edges

    if wfactor != 1.0:
        if wfactor.is_integer():
            wfactor = round(wfactor)
        edges_adj = [(i, j, w * wfactor) for (i, j, w) in edges_adj]

    if maxcard:
        edges_adj = adjust_weights_for_maximum_cardinality_matching(edges_adj)

    pairs = maximum_weight_matching(edges_adj)
    weight = calc_matching_weight(edges, pairs)

    if maxcard:
        if len(pairs) != len(gold_pairs):
            print("FAILED",
                  f"(got {len(pairs)} pairs, expected {len(gold_pairs)}")
            return False

    if isinstance(weight, int) and isinstance(gold_weight, int):
        good = (weight == gold_weight)
    else:
        good = math.isclose(weight, gold_weight, rel_tol=1e-9, abs_tol=1e-9)

    if not good:
        print(f"FAILED (got weight {weight}, expected {gold_weight}")
        return False

    print("OK")
    return True


def run_verify(filenames: list[str], maxcard: bool, wfactor: float) -> int:
    """Verify matching(s)."""

    num_passed = 0
    failed_tests: list[str] = []

    for filename in filenames:
        if verify_matching(filename, maxcard, wfactor):
            num_passed += 1
        else:
            failed_tests.append(filename)
        sys.stdout.flush()

    print("done.")
    print(num_passed, "tests passed")
    if failed_tests:
        print(len(failed_tests), "tests failed:")
        for filename in failed_tests:
            print("   ", filename, "FAILED")
    else:
        print("All tests passed")
    sys.stdout.flush()

    return 1 if failed_tests else 0


def main() -> int:
    """Main program."""

    parser = argparse.ArgumentParser()
    parser.description = (
        "Calculate maximum weighted matching of graphs in DIMACS format.")

    parser.add_argument("--verify",
                        action="store_true",
                        help="verify existing output file(s)")
    parser.add_argument("--maxcard",
                        action="store_true",
                        help="calculate maximum-cardinality matching")
    parser.add_argument("--wfactor",
                        action="store",
                        type=float,
                        default=1.0,
                        help="adjust weights by specified factor")
    parser.add_argument("--outdir",
                        action="store",
                        type=str,
                        help="directory to write output")
    parser.add_argument("input",
                        nargs="*",
                        help="input file(s); leave empty to read from stdin")

    args = parser.parse_args()

    if (not args.input) and os.isatty(sys.stdin.fileno()):
        print("ERROR: Expecting input from stdin but stdin is a terminal",
              file=sys.stderr)
        print(file=sys.stderr)
        parser.print_help(sys.stderr)
        return 1

    if (not args.input) and args.verify:
        print("ERROR: Can not verify when reading from stdin",
              file=sys.stderr)
        return 1

    if len(args.input) > 1 and (not args.verify) and (not args.outdir):
        print("ERROR: Need --outdir or --verify to process multiple inputs",
              file=sys.stderr)
        return 1

    try:
        if args.verify:
            return run_verify(args.input, args.maxcard, args.wfactor)
        else:
            return run_generate(args.input, args.outdir, args.maxcard)
    except (OSError, ValueError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
