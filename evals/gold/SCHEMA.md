# Gold well schema (Brief §10.1)

One JSON per gold well. SMEs build these from the source documents (target: 10 wells month one,
spanning eras and both jurisdictions; T7.3).

```json
{
  "api_number": "420853123400",      // normalized 12-digit, or null
  "uwi": null,
  "era": "1950s",                    // typed | 1950s | 1980s | modern — drives per-era breakdown
  "jurisdiction": "TXRRC",
  "gold_doc_types": {                 // document_id -> expected §7C class
    "<sha256 or sha:first-last>": "plugging_record"
  },
  "gold_facts": [                     // every fact a perfect extractor should produce
    {"field_path": "wellbore.td_md_ft", "value": "3650", "unit": "ft"},
    {"field_path": "plugging_record.plug",
     "value": "{\"plug_number\": 1, \"top_md_ft\": 3500, \"base_md_ft\": 3650}"}
  ]
}
```

Adversarial set (§10.3) lives in `adversarial/`: wells with conflicting documents, ditto marks,
amended-but-unlabeled forms, depths sans datum. Encode traps as *absence*: a field the model is
tempted to extract but must not is simply omitted from gold_facts — extracting it counts as a
false positive against precision.
