# KW X12 EDI Parser

[![Python](https://img.shields.io/badge/python-3.8%20%7C%203.9%20%7C%203.10%20%7C%203.11-blue)](https://pypi.org/project/kw-x12-parser/)
[![PyPI package](https://img.shields.io/pypi/v/kw-x12-parser?label=pypi%20package&color=brightgreen)](https://pypi.org/project/kw-x12-parser/)

A Python library for parsing and writing X12 healthcare EDI files.

**PyPI:** [pypi.org/project/kw-x12-parser](https://pypi.org/project/kw-x12-parser/) · **Source:** [github.com/rohanrkamath/KW-X12-Parser](https://github.com/rohanrkamath/KW-X12-Parser)

## Installation

```bash
pip install kw-x12-parser
# With DataFrame support and write-claims CLI:
pip install kw-x12-parser[dataframe]
```

From source (development):

```bash
pip install -e .
pip install -e ".[dataframe]"
```

## Usage

### 1. casual_parse_x837p – key columns

DataFrame with essential columns (one row per claim): provider_name, claim_id, patient_name, total_charge, etc.

```python
from kw_x12_parser import casual_parse_x837p

df = casual_parse_x837p("path/to/837p_file.txt")
# or: casual_parse_x837p(open("file.txt").read())
print(df[["claim_id", "patient_name", "total_charge"]])
```

### 2. full_parse_x837p – full schema

DataFrame with every loop and segment (420+ columns): ISA_*, GS_*, CLM_*, NM1_*, SV1_*, OTHER_SUBSCRIBER_*, etc.

```python
from kw_x12_parser import full_parse_x837p

df = full_parse_x837p("path/to/837p_file.txt")
# Use for COB claims or when you need complete data
```

### 3. write_to_edi_x837p – DataFrame to EDI

Convert a DataFrame back to 837P EDI. Two modes: filter original EDI by claim IDs (preserves segments) or build from scratch.

```python
from kw_x12_parser import casual_parse_x837p, write_to_edi_x837p

df = casual_parse_x837p("original.txt")
released = df[df["claim_id"].isin({"123", "456"})]
write_to_edi_x837p(released, "claims_out.txt", original_edi="original.txt")
```

## CLI

```bash
write-claims claims.csv -o claims.txt
write-claims claims.csv original.txt -o claims.txt   # filter by claim IDs
```

Requires `pip install kw-x12-parser[dataframe]`.

## Project structure

```
kw_x12_parser/
└── x837p/
    ├── api.py          # casual_parse_x837p, full_parse_x837p, write_to_edi_x837p
    ├── write_claims.py # write-claims CLI
    ├── workflow/       # Workflow notebook
    ├── edi_examples/   # Sample 837P files
    └── utils/          # Parser internals
```

## Ultimate goal

Support parsing of all healthcare X12 EDI formats:

| Code | Name | Purpose | Dev status |
|------|------|---------|------------|
| 270 | Eligibility inquiry | Ask payer if patient is eligible for coverage | — |
| 271 | Eligibility response | Payer’s response to 270 | — |
| 276 | Claim status request | Request status of a claim | — |
| 277 | Claim status response | Payer’s claim status response | — |
| 278 | Prior authorization | Request/response for prior authorization (inbound/outbound) | — |
| 820 | Premium payment | Pay health plan premiums | — |
| 834 | Benefit enrollment | Enroll or update member benefits | — |
| 835 | Payment/remittance | Payer payment and remittance advice (ERA) | — |
| 837P | Professional claim | Medical/professional claims | ✅ |
| 837I | Institutional claim | Hospital/facility claims | — |
| 837D | Dental claim | Dental claims | — |

## Current supported formats

- X12 837P (005010X222A1)

## Contributing

Issues and pull requests: [github.com/rohanrkamath/KW-X12-Parser/issues](https://github.com/rohanrkamath/KW-X12-Parser/issues)
