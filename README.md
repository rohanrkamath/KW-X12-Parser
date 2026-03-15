# EDI Parser

A Python library to parse X12 837P (Professional) EDI files.

## Installation

```bash
pip install -e .
# For DataFrame support:
pip install -e ".[dataframe]"
```

## Usage

Three main functions:

### 1. casual_parse_x837p – important columns

DataFrame with key columns (one row per claim): provider_name, claim_id, patient_name, total_charge, etc.

```python
from parsers import casual_parse_x837p

df = casual_parse_x837p("path/to/837p_file.txt")
# or: casual_parse_x837p(open("file.txt").read())
print(df[["claim_id", "patient_name", "total_charge"]])
```

### 2. full_parse_x837p – everything

DataFrame with every loop and segment (420+ columns): ISA_*, GS_*, CLM_*, NM1_*, SV1_*, OTHER_SUBSCRIBER_*, etc.

```python
from parsers import full_parse_x837p

df = full_parse_x837p("path/to/837p_file.txt")
# Use for COB claims or when you need complete data
```

### 3. write_to_edi_x837p – stitch DataFrame back to EDI

Convert a DataFrame to 837P EDI. Use when claims are redacted and you need to output a valid file.

```python
from parsers import full_parse_x837p, write_to_edi_x837p

# Option A: Build from scratch (no original EDI)
df = full_parse_x837p("original.txt")
released = df[df["claim_id"].isin({"123", "456"})]
write_to_edi_x837p(released, "released.txt")

# Option B: Filter original EDI by claim IDs (preserves exact segments)
write_to_edi_x837p(released, "released.txt", original_edi="original.txt")
```

## CLI

```bash
write-claims csv_file.csv -o claims.txt
write-claims csv_file.csv original_edi.txt -o claims.txt
```

## Project structure

```
parsers/
└── x837p/           # 837P (Professional)
    ├── api.py       # casual_parse_x837p, full_parse_x837p, write_to_edi_x837p
    └── utils/       # parser, x837, x837_full, df_to_edi, ...
```

## Supported formats

- X12 837P (005010X222A1)
- Delimiters auto-detected from ISA segment
