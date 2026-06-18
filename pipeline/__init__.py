"""Offline batch pipeline for cement/concrete technology intelligence.

The live website reads prepared records from a static database. This package
processes corpus slices offline with bounded concurrency so parallel batch
workers can run many shards in parallel later.
"""
