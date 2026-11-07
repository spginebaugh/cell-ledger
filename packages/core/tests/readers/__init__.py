"""Read-only integrity checks over pipeline outputs, used by the core tests.

These are not evals: they verify that an analysis or comparison folder is internally
consistent (files present, hashes match, AnnData agrees with the tables). They never score
biology. The discovery evals live in ``evals/``.
"""

from packages.core.tests.readers.analysis import Inspection, read_analysis, read_collection
from packages.core.tests.readers.comparison import read_comparison

__all__ = ["Inspection", "read_analysis", "read_collection", "read_comparison"]
