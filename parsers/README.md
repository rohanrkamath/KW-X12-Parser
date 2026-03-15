# Parsers

X12 EDI parsing library. Each subpackage corresponds to a transaction type.

## Subpackages

| Package | Description |
|---------|-------------|
| **x837p** | 837P (Professional) healthcare claims – parse and write 005010X222A1 |

## Usage

```python
from parsers import casual_parse_x837p, full_parse_x837p, write_to_edi_x837p

df = casual_parse_x837p("claims.txt")
```

See [parsers/x837p/README.md](x837p/README.md) for full API documentation.
