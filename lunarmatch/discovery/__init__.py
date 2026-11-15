"""Earth analog discovery infrastructure (Stage A: coarse terrain screening).

This package partitions the Earth search space, computes comparable terrain
descriptors per geographic window, caches them, filters on data quality and
explicit user constraints, and reports real progress and search coverage.

It deliberately computes no Moon-Earth similarity, scores or rankings: those
are governed by CLAUDE.md and the experiment catalog and are not enabled.
"""
