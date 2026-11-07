from cell_ledger.geo import parse_soft

SOFT = """\
^DATABASE = GeoMiame
!Database_name = Gene Expression Omnibus (GEO)
^SERIES = GSE1
!Series_title = Sepsis vs healthy
!Series_summary = Part one.
!Series_summary = Part two.
!Series_overall_design = 2 vs 2
!Series_pubmed_id = 123
!Series_supplementary_file = ftp://x/GSE1_RAW.tar
^PLATFORM = GPL1
!Platform_title = Illumina
#ID = probe id
!platform_table_begin
ID
!platform_table_end
^SAMPLE = GSM1
!Sample_title = Control 1
!Sample_source_name_ch1 = blood
!Sample_organism_ch1 = Homo sapiens
!Sample_characteristics_ch1 = disease state: none
!Sample_characteristics_ch1 = tissue: blood
!Sample_characteristics_ch1 = tissue: blood again
!Sample_library_strategy = RNA-Seq
!Sample_platform_id = GPL1
^SAMPLE = GSM2
!Sample_title = Sepsis 1
!Sample_characteristics_ch1 = disease state: sepsis
!Sample_characteristics_ch1 = free text without a key
"""


def test_parse_soft_series_and_samples() -> None:
    s = parse_soft(SOFT)
    assert s.gse == "GSE1"
    assert s.title == "Sepsis vs healthy"
    assert s.summary == "Part one. Part two."
    assert s.overall_design == "2 vs 2"
    assert s.pubmed_ids == ["123"]
    assert s.supplementary_files == ["ftp://x/GSE1_RAW.tar"]
    assert [x.gsm for x in s.samples] == ["GSM1", "GSM2"]
    a, b = s.samples
    assert (a.title, a.source_name, a.organism, a.library_strategy, a.platform) == (
        "Control 1",
        "blood",
        "Homo sapiens",
        "RNA-Seq",
        "GPL1",
    )
    assert a.characteristics_dict() == {
        "disease state": "none",
        "tissue": "blood",
        "tissue.2": "blood again",
    }
    assert b.characteristics_dict() == {
        "disease state": "sepsis",
        "characteristics": "free text without a key",
    }


def test_parse_soft_keeps_protocols_description_and_relations() -> None:
    s = parse_soft(
        "^SERIES = GSE9\n"
        "!Series_relation = SubSeries of: GSE8\n"
        "^SAMPLE = GSM9\n"
        "!Sample_description = first line\n"
        "!Sample_description = second line\n"
        "!Sample_growth_protocol_ch1 = Organoids in Matrigel\n"
        "!Sample_treatment_protocol_ch1 = shRNA knockdown of CLIC1\n"
        "!Sample_extract_protocol_ch1 = TRIzol\n"
        "!Sample_extract_protocol_ch1 = polyA selection\n"
        "!Sample_molecule_ch1 = total RNA\n"
        "!Sample_library_source = transcriptomic\n"
    )
    assert s.relations == ["SubSeries of: GSE8"]
    (x,) = s.samples
    assert x.description == "first line second line"
    assert x.growth_protocol == "Organoids in Matrigel"
    assert x.treatment_protocol == "shRNA knockdown of CLIC1"
    assert x.extract_protocol == "TRIzol polyA selection"
    assert (x.molecule, x.library_source) == ("total RNA", "transcriptomic")
