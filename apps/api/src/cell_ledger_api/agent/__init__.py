"""The specialist's two Claude-driven steps.

1. **Discover** (:mod:`.discover`, streamed by ``POST /sessions/{id}/discover``): from the
   user's question, Claude searches GEO (keyword search, and the web through Exa when
   configured) with the tools in :mod:`.tools`, reads the sample records of the series it
   might recommend, and returns candidate series with rules choosing their samples (code turns
   them into GSM lists, :mod:`.samples`), or clarifying questions when the question is too
   broad or ambiguous. Claude never invents an accession: every GSE it reports came back from
   a GEO search or a GEO verification in this very run.

2. **Design** (:mod:`.design`, run by ``cell_ledger_api.pipeline`` as soon as a dataset is
   ready): for one collected series, Claude labels each sample from its GEO record and chooses
   the one two-group contrast that answers the question. Code compiles the labels into a
   validated sample sheet and contrast; nobody confirms the result.

Both steps call Claude through :class:`.llm.TurnRunner`, so tests can script its turns.
"""
