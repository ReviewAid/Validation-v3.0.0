Extraction corpus: EvidenceInference (Lehman et al., NAACL 2019; 2.0).
Full texts are repo-provided .txt files rendered to PDF for ReviewAid's
PDF ingest (PyMuPDF); provenance in extraction_tasks.csv txt_source.
Gold: prompts_merged.csv I/C/O descriptions (pipe-joined alternatives
per article) + annotations_merged.csv majority effect-direction label.
Scoring takes the best token-F1 across the gold alternatives.
