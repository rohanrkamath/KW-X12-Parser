"""
837P (Professional) EDI parser – public API.

Three main functions:
  1. casual_parse_x837p(edi)    → DataFrame of important columns (one row per claim)
  2. full_parse_x837p(edi)      → DataFrame with every loop/segment captured
  3. write_to_edi_x837p(df, output_path, original_edi=None)  → Stitch DataFrame back to EDI
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

from .utils.hierarchical_parser import (
    parse_837p,
    parse_837p_string,
    parse_837p_to_claims_dataframe,
    parse_837p_to_claims_dataframe_full,
)
from .utils.raw_block_parser import parse_837p_full
from .utils.dataframe_to_edi import write_edi_from_dataframe

# Type for EDI input: file path or raw content
EdiInput = Union[str, Path]


def _normalize_claim_id(value: object) -> str:
    """Normalize claim ID string for stable matching across parse/write paths."""
    s = str(value).strip()
    # Common DataFrame coercion: numeric IDs can become "<id>.0"
    if s.endswith(".0") and s[:-2].isdigit():
        return s[:-2]
    return s


def _resolve_edi(edi: EdiInput) -> tuple[str, str | None]:
    """Return (content, source_file). source_file is filename for path, else None."""
    s = str(edi)
    # Raw EDI content: starts with ISA* or is too long for a path (avoids OSError: File name too long)
    if s.strip().startswith("ISA*") or len(s) > 260:
        return s, None
    try:
        p = Path(s)
        if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8", errors="replace"), p.name
    except OSError:
        # e.g. Errno 63 File name too long when s is raw EDI passed as path
        pass
    return s, None


def casual_parse_x837p(edi: EdiInput):
    """
    Parse 837P and return a DataFrame of the most important columns (one row per claim).

    Columns include: provider_name, provider_npi, claim_id, total_charge,
    patient_name, payer_name, diagnosis_codes, service_line_count, etc.

    Args:
        edi: Path to EDI file, or raw EDI content string.

    Returns:
        pandas.DataFrame (requires: pip install edi-parser[dataframe])
    """
    content, src = _resolve_edi(edi)
    return parse_837p_to_claims_dataframe(content=content, source_file=src or "unknown")


def full_parse_x837p(edi: EdiInput):
    """
    Parse 837P and capture every loop and segment. Returns a DataFrame with full
    X12-style columns (ISA_*, GS_*, CLM_*, NM1_*, SV1_*, OTHER_SUBSCRIBER_*, etc.).

    Use this when you need complete data, including COB (Coordination of Benefits).

    Args:
        edi: Path to EDI file, or raw EDI content string.

    Returns:
        pandas.DataFrame with full schema (one row per claim).
    """
    content, src = _resolve_edi(edi)
    return parse_837p_to_claims_dataframe_full(content=content, source_file=src or "unknown")


def write_to_edi_x837p(
    dataframe,
    output_path: str | Path,
    *,
    original_edi: EdiInput | None = None,
    claim_id_column: str = "claim_id",
    blank_line_between_segments: bool = True,
    isa15_usage_indicator: str | None = None,
) -> None:
    """
    Convert a DataFrame back to 837P EDI format. Supports redacted data: if some
    claims were removed from the original, provide original_edi to preserve
    structure and filter by claim IDs from the DataFrame.

    Args:
        dataframe: DataFrame with claims (must have claim_id column).
            For from-scratch build, use output from full_parse_x837p().
        output_path: Where to write the output EDI file.
        original_edi: Optional. If provided (path or content):
            filters original EDI by claim IDs in the DataFrame (preserves exact segments).
            If omitted: builds EDI from scratch from the DataFrame.
        claim_id_column: Column name for claim ID (default: "claim_id").
        blank_line_between_segments: Insert blank line between segments (default True).
        isa15_usage_indicator: Optional ISA15 override ("T" test / "P" production).
    """
    import pandas as pd  # type: ignore[import-untyped]

    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("dataframe must be a pandas DataFrame")
    if claim_id_column not in dataframe.columns:
        raise ValueError(f"Missing required column: {claim_id_column}")
    if isa15_usage_indicator is not None:
        isa15_usage_indicator = str(isa15_usage_indicator).strip().upper()
        if isa15_usage_indicator not in {"T", "P"}:
            raise ValueError("isa15_usage_indicator must be 'T' or 'P'")

    if original_edi is not None:
        content, _ = _resolve_edi(original_edi)
        claim_ids = [
            _normalize_claim_id(v)
            for v in dataframe[claim_id_column].dropna().tolist()
            if str(v).strip()
        ]
        released_set = set(claim_ids)
        p = parse_837p_full(content=content)
        p.write_edi(
            output_path,
            include_claim_ids=released_set,
            isa15_usage_indicator=isa15_usage_indicator,
        )
    else:
        write_edi_from_dataframe(
            dataframe,
            output_path,
            blank_line_between_segments=blank_line_between_segments,
            isa15_usage_indicator=isa15_usage_indicator,
        )
