"""
837P (Professional) EDI parser – X12 005010X222A1.

Public API:
  casual_parse_x837p(edi)           → DataFrame of important columns
  full_parse_x837p(edi)             → DataFrame with every loop/segment
  write_to_edi_x837p(df, path, ...) → Stitch DataFrame back to EDI
"""

from parsers.x837p.api import (
    casual_parse_x837p,
    full_parse_x837p,
    write_to_edi_x837p,
)

__all__ = [
    "casual_parse_x837p",
    "full_parse_x837p",
    "write_to_edi_x837p",
]
