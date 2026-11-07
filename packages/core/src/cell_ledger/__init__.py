"""cell_ledger: find, triage, harmonize and analyze public GEO RNA-seq data.

Subpackages, in pipeline order:

- ``geo``          search GEO and fetch series metadata and supplementary files
- ``triage``       decide whether a dataset is actually usable
- ``samplesheet``  harmonize per-sample metadata into one ``SampleSheet``
- ``analysis``     bulk (pydeseq2) and single-cell (scanpy) steps as pure functions
- ``report``       turn results into a serializable report
"""

__version__ = "0.1.0"
