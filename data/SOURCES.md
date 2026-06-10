# Acquired data sources (Brief §4) — endpoints verified live 2026-06-10 (T2.6)

| Source | What | Access basis | Notes |
|---|---|---|---|
| BSEE/BOEM data.bsee.gov | Borehole master, API lookup/changes, APD, eWell APD/APM/EOR/WAR, scanned-docs index, decom cost estimates (bulk zips) | Public records | Catalog: /Main/RawData.aspx (drift canary — `wellclose corpus verify-endpoints`). The old APDAPMRawData.zip / eWellSundryRawData.zip are gone; replaced per-report-type. |
| BSEE scanned well files | Historical well-file PDFs | Public records, **query-only** | Served via the eWell File Request System (human-fulfilled) — NOT crawled. DESCOPED for MVP: FRS requests filed manually for the ~10 gold P&A wells; delivered PDFs ingested with `wellclose ingest`. ScannedDocsRawData.zip is the index used to target requests. |
| Texas RRC imaged records | W-2/G-1, W-3, casing/cement records, schematics (scanned PDFs) | Public records | Neubus NDE service (rrcsearch3.neubus.com, robots allows; anonymous public-user JWT). Flow: search → view-record → tab-files → file-server GET. Cache-and-never-refetch. This is the OCR hardening corpus. |
| Texas RRC orphan inventory | ~12k orphan wells (API, district, lease, operator, P-5 inactivity) | Public records (published bulk download) | Monthly-slugged zip scraped from the orphan-wells page. Primary TX well-selection source. |
| Texas RRC CMPL completions search | — | **robots.txt `Disallow: /`** | NOT crawled (Brief §4.5 requires honoring robots). Consequence: all 200 TX corpus wells are drawn from the orphan inventory (≥30 required by §4.2 — exceeded); era strata are validated from acquired document dates instead of completion-date queries. |
| Equinor Volve | Well technical reports / drilling & completion report PDFs (subset; full set is TB-scale) | Equinor Open Data License | Manual download from data.equinor.com/dataset/Volve into data/volve/ (LOCAL PATH ONLY — never redistributed). `wellclose corpus volve-verify` gates manifest inclusion on license acceptance in LICENSES.md. |

Provenance per document: source URL, fetch timestamp, response headers, sha256 (Document.fetch_meta).
Politeness (§4.5): ≤1 rps BSEE, ≤0.5 rps RRC/Neubus; exponential backoff; circuit breaker;
robots.txt honored (RFC 9309 semantics); honest User-Agent (`WC_USER_AGENT`).
