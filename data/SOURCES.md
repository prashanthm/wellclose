# Acquired data sources (Brief §4)
| Source | What | Access basis | Notes |
|---|---|---|---|
| BSEE/BOEM data.bsee.gov | GoM borehole, APD/APM, sundry, scanned well files | Public records | bulk zips + per-doc fetch; verify endpoints (T2.6) |
| Texas RRC | wellbore queries, completions, imaged W-2/W-3, orphan list | Public records | cache-and-never-refetch; OCR hardening corpus |
| Equinor Volve | full North Sea well files | Equinor license | LOCAL PATH ONLY — never redistributed |
Provenance per document: source URL, fetch timestamp, response headers, sha256 (Document.fetch_meta).
