# KW X12 EDI Parser

A Python library for parsing and writing X12 EDI files.

**Repository:** [github.com/rohanrkamath/KW-X12-EDI-Parser](https://github.com/rohanrkamath/KW-X12-EDI-Parser)

## Installation

```bash
pip install -e .
# For DataFrame support (required for parsing and write-claims CLI):
pip install -e ".[dataframe]"
```

## Usage

### 1. casual_parse_x837p – key columns

DataFrame with essential columns (one row per claim): provider_name, claim_id, patient_name, total_charge, etc.

```python
from kw_x12_edi_parser import casual_parse_x837p

df = casual_parse_x837p("path/to/837p_file.txt")
# or: casual_parse_x837p(open("file.txt").read())
print(df[["claim_id", "patient_name", "total_charge"]])
```

### 2. full_parse_x837p – full schema

DataFrame with every loop and segment (420+ columns): ISA_*, GS_*, CLM_*, NM1_*, SV1_*, OTHER_SUBSCRIBER_*, etc.

```python
from kw_x12_edi_parser import full_parse_x837p

df = full_parse_x837p("path/to/837p_file.txt")
# Use for COB claims or when you need complete data
```

### 3. write_to_edi_x837p – DataFrame to EDI

Convert a DataFrame back to 837P EDI. Two modes: filter original EDI by claim IDs (preserves segments) or build from scratch.

```python
from kw_x12_edi_parser import casual_parse_x837p, write_to_edi_x837p

df = casual_parse_x837p("original.txt")
released = df[df["claim_id"].isin({"123", "456"})]
write_to_edi_x837p(released, "claims_out.txt", original_edi="original.txt")
```

## CLI

```bash
write-claims claims.csv -o claims.txt
write-claims claims.csv original.txt -o claims.txt   # filter by claim IDs
```

Requires `pip install -e ".[dataframe]"`.

## Project structure

```
kw_x12_edi_parser/
└── x837p/
    ├── api.py          # casual_parse_x837p, full_parse_x837p, write_to_edi_x837p
    ├── write_claims.py # write-claims CLI
    ├── workflow/       # Workflow notebook
    ├── edi_examples/   # Sample 837P files
    └── utils/          # Parser internals
```

## Supported formats

- X12 837P (005010X222A1)
- Delimiters auto-detected from ISA segment
