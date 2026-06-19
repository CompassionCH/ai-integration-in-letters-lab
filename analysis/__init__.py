"""Aggregation functions over the evaluation data.

Each module here is a PURE function over rows the caller has already fetched
(and joined) from SQLite — no module in this package opens the database or reads
settings. The admin route resolves the active prompt_version, runs the queries,
and passes the rows in. This keeps the aggregations trivially unit-testable with
in-memory fixtures and free of I/O.
"""
