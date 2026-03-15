"""
write-claims CLI: convert DataFrame of claims to EDI.
Uses write_to_edi_x837p under the hood.
"""

from kw_x12_edi_parser.x837p import write_to_edi_x837p


def write_claims_to_edi(
    claims_df,
    *,
    edi_path: str | None = None,
    claim_id_column: str = "claim_id",
    output_path: str = "claims.txt",
    blank_line_between_segments: bool = True,
) -> None:
    """Write EDI file from claims DataFrame. See write_to_edi_x837p."""
    write_to_edi_x837p(
        claims_df,
        output_path,
        original_edi=edi_path,
        claim_id_column=claim_id_column,
        blank_line_between_segments=blank_line_between_segments,
    )


def main() -> None:
    """CLI entry point for write-claims command."""
    import argparse

    import pandas as pd  # type: ignore[import-untyped]

    parser = argparse.ArgumentParser(
        description="Convert claims DataFrame to EDI"
    )
    parser.add_argument(
        "csv",
        help="Path to CSV of claims (claim_id column; full schema for from-scratch)",
    )
    parser.add_argument(
        "edi",
        nargs="?",
        default=None,
        help="Optional: path to original EDI (filters by claim IDs; else builds from scratch)",
    )
    parser.add_argument("-o", "--output", default="claims.txt", help="Output path")
    parser.add_argument("--claim-id-column", default="claim_id", help="Claim ID column")
    parser.add_argument(
        "--no-blank-lines",
        action="store_true",
        help="Do not insert blank line between segments",
    )
    args = parser.parse_args()
    df = pd.read_csv(args.csv)
    write_claims_to_edi(
        claims_df=df,
        edi_path=args.edi,
        claim_id_column=args.claim_id_column,
        output_path=args.output,
        blank_line_between_segments=not args.no_blank_lines,
    )
    print(f"Wrote {len(df)} claims to {args.output}")


__all__ = ["main", "write_claims_to_edi"]
