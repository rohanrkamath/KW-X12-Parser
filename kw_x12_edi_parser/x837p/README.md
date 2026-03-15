# X12 837P (Professional) Parser

Python module for parsing and writing X12 837P healthcare professional claims. Supports the 005010X222A1 implementation guide and CMS Companion Guide loop structure.

---

## Public API

### `casual_parse_x837p(edi)`

Parse 837P into a compact DataFrame with the most common columns (one row per claim).

**Use when:** You need quick access to claim IDs, patient/provider info, charges, and diagnosis codes.

**Columns include:**
- `provider_name`, `provider_npi`, `provider_address`, `provider_city_state_zip`
- `claim_id`, `total_charge`, `patient_name`, `payer_name`
- `diagnosis_codes`, `service_line_count`
- `source_file`

```python
from kw_x12_edi_parser import casual_parse_x837p

df = casual_parse_x837p("claims.txt")
# or raw EDI string:
df = casual_parse_x837p(open("claims.txt").read())
```

---

### `full_parse_x837p(edi)`

Parse 837P into a DataFrame with every loop and segment flattened to columns (420+ columns).

**Use when:** You need COB (Coordination of Benefits), SVD/CAS, line-level detail, or any X12 segment not in the casual schema.

**Column naming:** X12-style, e.g. `ISA_*`, `GS_*`, `CLM_*`, `NM1_*`, `SV1_*`, `OTHER_SUBSCRIBER_*`, `OTHER_PAYER_*`.

```python
from kw_x12_edi_parser import full_parse_x837p

df = full_parse_x837p("claims.txt")
```

---

### `write_to_edi_x837p(dataframe, output_path, *, original_edi=None, ...)`

Convert a DataFrame back to 837P EDI format.

**Two modes:**

| Mode | `original_edi` | Behavior |
|------|----------------|----------|
| **Filter** | Provided (path or string) | Keeps only claims whose IDs are in the DataFrame; preserves exact segments from the original file. Ideal for hold/release workflows. |
| **Build from scratch** | `None` | Constructs EDI from DataFrame columns. Requires output from `full_parse_x837p()` (or equivalent schema). |

**Parameters:**
- `dataframe` – Must have `claim_id` column (or custom via `claim_id_column`)
- `output_path` – Output file path
- `original_edi` – Optional. Path or raw EDI string; when set, filters by claim IDs instead of building from scratch
- `claim_id_column` – Column name for claim ID (default: `"claim_id"`)
- `blank_line_between_segments` – Insert newline between segments (default: `True`)

**Workflow:** For filtering mode, you can use output from either `casual_parse_x837p` or `full_parse_x837p` — only `claim_id` is needed. For build-from-scratch, use `full_parse_x837p`.

```python
from kw_x12_edi_parser import casual_parse_x837p, write_to_edi_x837p

df = casual_parse_x837p("original.txt")
released = df[df["claim_id"].isin({"123", "456"})]
write_to_edi_x837p(released, "claims_out.txt", original_edi="original.txt")
```

---

## CLI: `write-claims`

Thin wrapper around `write_to_edi_x837p` for CSV → EDI conversion.

```bash
write-claims claims.csv -o claims.txt
write-claims claims.csv original.txt -o claims.txt   # filter by claim IDs
```

Requires `pip install -e ".[dataframe]"`.

---

## Technical Notes

- **Input resolution:** `edi` can be a file path (`str` or `Path`) or raw EDI content. Raw content is detected when the string starts with `ISA*` or exceeds 260 characters (avoids treating long EDI as a path).
- **Delimiters:** Segment and element delimiters are read from the ISA segment (positions 104–106 per X12 00501).
- **Hierarchy:** HL loop structure follows TR3 005010X222A1; e.g. HL level 20 = Billing Provider, level 22 = Subscriber/Claim.
- **COB:** Full parse and build-from-scratch support Loop 2320/2330 (Other Subscriber, Other Payer). Populate `OTHER_SUBSCRIBER_*` and `OTHER_PAYER_*` columns for COB.

---

## Module Layout

```
x837p/
├── api.py           # Public API (casual_parse_x837p, full_parse_x837p, write_to_edi_x837p)
├── write_claims.py  # write-claims CLI entry point
├── workflow/        # Workflow notebook
├── edi_examples/    # Sample 837P files (25, 50, 75 claims) + generate_samples.py
└── utils/
    ├── segment_parser.py      # X12 segment parsing, delimiters
    ├── hierarchical_parser.py # HL tree → casual/full DataFrames
    ├── claim_models.py        # BillingProvider, SubscriberClaim, ServiceLine
    ├── raw_block_parser.py    # Raw block preservation, filter-by-claim-ID
    ├── full_column_mapper.py  # Segment → DataFrame column mapping
    └── dataframe_to_edi.py    # DataFrame → EDI (build from scratch)
```
