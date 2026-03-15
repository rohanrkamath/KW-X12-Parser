# X12 837P Sample Files

Notional EDI files for testing and documentation. Data is synthetic; structure adheres to X12 005010X222A1 837P.

| File | Claims | Richness | ~Cols (full_parse) |
|------|--------|----------|--------------------|
| `edi_sample_25_claims.txt` | 25 | minimal | ~284 |
| `edi_sample_50_claims.txt` | 50 | medium (COB, NM1*82, REF*6R) | ~327 |
| `edi_sample_75_claims.txt` | 75 | full (COB, SVD/CAS, DTP*573, REF*0B) | ~450 |

Samples vary in structure so concatenated DataFrames get different column unions (similar to mixing zircaid vs home_trdplntr).

## Regenerate

```bash
python kw_x12_edi_parser/x837p/edi_examples/generate_samples.py
```
