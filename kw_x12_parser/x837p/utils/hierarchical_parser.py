"""
837P (Professional) hierarchical parser.
Follows ASC X12N TR3 005010X222A1 and CMS 837P Companion Guide loop/segment rules.
"""

from __future__ import annotations

from pathlib import Path

from .segment_parser import parse_string, Segment
from .claim_models import (
    BillingProvider,
    HLNode,
    LoopSegmentGroup,
    Parsed837P,
    ServiceLine,
    SubscriberClaim,
)

# Segment IDs that start a new HL's content (only HL does)
# Segment IDs that start a service line
SERVICE_LINE_START = "LX"

# Segment IDs that terminate a claim loop (next HL)
# We detect by HL segment


def _parse_segment_from_parsed(seg: "Segment") -> Segment:
    """Ensure we use our Segment type."""
    from .claim_models import Segment as X837Segment
    return X837Segment(id=seg.id, elements=list(seg.elements))


def _build_hl_nodes(segments: list) -> list[tuple[HLNode, list]]:
    """
    Build HL nodes and assign segments to each.
    Returns list of (HLNode, segments_belonging_to_this_node).
    """
    nodes: list[tuple[HLNode, list]] = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        if seg.id != "HL":
            i += 1
            continue
        # Create HL node
        hl_id = seg.get(1) or ""
        parent_id = seg.get(2) or None
        if parent_id == "":
            parent_id = None
        level_code = seg.get(3) or ""
        child_code = seg.get(4) or "0"
        node = HLNode(
            hl_id=hl_id,
            parent_id=parent_id,
            level_code=level_code,
            child_code=child_code,
            segments=[],
        )
        # Collect segments until next HL (excluding control segments)
        node_segments: list = []
        i += 1
        while i < len(segments):
            s = segments[i]
            if s.id == "HL":
                break
            if s.id in ("SE", "GE", "IEA"):
                break
            node_segments.append(_parse_segment_from_parsed(s))
            i += 1
        node.segments = node_segments
        nodes.append((node, node_segments))
    return nodes


def _split_service_lines(segments: list) -> tuple[list, list[list]]:
    """
    Split claim-level segments into header segments and service line groups.
    Returns (claim_header_segments, [service_line_1_segments, service_line_2_segments, ...])
    """
    header: list = []
    lines: list[list] = []
    current_line: list | None = None
    for s in segments:
        if s.id == SERVICE_LINE_START:
            if current_line is not None:
                lines.append(current_line)
            current_line = [s]
        else:
            if current_line is not None:
                current_line.append(s)
            else:
                header.append(s)
    if current_line is not None:
        lines.append(current_line)
    return header, lines


def _parse_837p_from_segments(segments: list) -> Parsed837P:
    """
    Build hierarchical 837P structure from flat segment list.
    Expects segments from ST through SE (transaction set only).
    """
    # Find transaction set boundary (ST ... SE)
    start_idx = 0
    end_idx = len(segments)
    for i, s in enumerate(segments):
        if s.id == "ST":
            start_idx = i
            break
    for i in range(len(segments) - 1, -1, -1):
        if segments[i].id == "SE":
            end_idx = i + 1
            break
    txn_segments = segments[start_idx:end_idx]

    # Collect header (before first HL): BHT, NM1*41, PER, NM1*40
    submitter = LoopSegmentGroup()
    receiver = LoopSegmentGroup()
    bht_seg = None
    i = 0
    while i < len(txn_segments):
        s = txn_segments[i]
        if s.id == "HL":
            break
        seg = _parse_segment_from_parsed(s)
        if s.id == "BHT":
            bht_seg = seg
        elif s.id == "NM1":
            if s.get(1) == "41":  # Submitter (NM101)
                submitter.segments.append(seg)
                i += 1
                while i < len(txn_segments) and txn_segments[i].id not in ("NM1", "HL"):
                    submitter.segments.append(_parse_segment_from_parsed(txn_segments[i]))
                    i += 1
                continue
            elif s.get(1) == "40":  # Receiver (NM101)
                receiver.segments.append(seg)
                i += 1
                while i < len(txn_segments) and txn_segments[i].id not in ("NM1", "HL"):
                    receiver.segments.append(_parse_segment_from_parsed(txn_segments[i]))
                    i += 1
                continue
        i += 1

    # Build HL nodes from remaining segments (from first HL)
    hl_start = 0
    for j, s in enumerate(txn_segments):
        if s.id == "HL":
            hl_start = j
            break
    remaining = txn_segments[hl_start:]
    nodes = _build_hl_nodes(remaining)

    # Build hierarchy: level 20 = BillingProvider, level 22 = SubscriberClaim
    billing_providers: list[BillingProvider] = []
    bp_by_id: dict[str, BillingProvider] = {}

    for node, node_segments in nodes:
        if node.level_code == "20":
            bp = BillingProvider(hl_node=node, segments=node_segments)
            billing_providers.append(bp)
            bp_by_id[node.hl_id] = bp
        elif node.level_code == "22" and node.parent_id:
            parent_bp = bp_by_id.get(node.parent_id)
            if parent_bp:
                header_segs, line_groups = _split_service_lines(node_segments)
                claim = SubscriberClaim(
                    hl_node=node,
                    segments=header_segs,
                    service_lines=[ServiceLine(segments=g) for g in line_groups],
                )
                parent_bp.claims.append(claim)

    # Extract envelope segments (ISA, GS, GE, IEA, SE) from full segment list
    isa_seg = next((_parse_segment_from_parsed(s) for s in segments if s.id == "ISA"), None)
    gs_seg = next((_parse_segment_from_parsed(s) for s in segments if s.id == "GS"), None)
    se_seg = next((_parse_segment_from_parsed(s) for s in segments if s.id == "SE"), None)
    ge_seg = next((_parse_segment_from_parsed(s) for s in segments if s.id == "GE"), None)
    iea_seg = next((_parse_segment_from_parsed(s) for s in segments if s.id == "IEA"), None)

    return Parsed837P(
        submitter=submitter,
        receiver=receiver,
        bht=bht_seg,
        billing_providers=billing_providers,
        all_segments=[_parse_segment_from_parsed(s) for s in txn_segments],
        isa_segment=isa_seg,
        gs_segment=gs_seg,
        se_segment=se_seg,
        ge_segment=ge_seg,
        iea_segment=iea_seg,
    )


def parse_837p(file_path: str | Path) -> Parsed837P:
    """
    Parse an 837P (Professional) EDI file with hierarchical loop structure.

    Args:
        file_path: Path to the EDI file.

    Returns:
        Parsed837P with billing providers, claims, and service lines structured
        per 837P loop rules (TR3 005010X222A1 / CMS Companion Guide).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"EDI file not found: {path}")
    content = path.read_text(encoding="utf-8", errors="replace")
    return parse_837p_string(content)


def parse_837p_string(content: str) -> Parsed837P:
    """
    Parse 837P content from a string with hierarchical structure.
    """
    parsed = parse_string(content)
    return _parse_837p_from_segments(parsed.segments)


def parse_837p_to_claims_dataframe(
    file_path: str | Path | None = None,
    content: str | None = None,
    source_file: str | None = None,
):
    """
    Parse 837P and return a pandas DataFrame (one row per claim).
    For Palantir Foundry: use spark.createDataFrame(df) on the result.

    Args:
        file_path: Path to EDI file (mutually exclusive with content).
        content: Raw EDI content string (mutually exclusive with file_path).
        source_file: Optional filename for the source_file column (e.g. for batch processing).

    Returns:
        pandas.DataFrame with columns: provider_name, provider_npi, claim_id,
        total_charge, patient_name, payer_name, diagnosis_codes, service_line_count,
        and optionally source_file.
    """
    if file_path is not None and content is not None:
        raise ValueError("Provide either file_path or content, not both")
    if file_path is not None:
        result = parse_837p(file_path)
        src = source_file or str(Path(file_path).name)
    elif content is not None:
        result = parse_837p_string(content)
        src = source_file
    else:
        raise ValueError("Provide either file_path or content")
    return result.to_claims_dataframe(source_file=src)


def parse_837p_to_claims_dataframe_full(
    file_path: str | Path | None = None,
    content: str | None = None,
    source_file: str | None = None,
):
    """
    Parse 837P and return a pandas DataFrame with full X12-style columns (one row per claim).
    Includes ISA/GS/SE/GE/IEA, HL, BHT, CLM, NM1/N3/N4 for all entities, SBR, REF,
    per-line SV1/DTP/NM1, and COB OTHER_SUBSCRIBER/OTHER_PAYER when present.

    For COB claims: use this (not parse_837p_to_claims_dataframe) so OTHER_* columns
    are populated for df_to_edi / write_claims.

    Args:
        file_path: Path to EDI file (mutually exclusive with content).
        content: Raw EDI content string (mutually exclusive with file_path).
        source_file: Optional filename for the source_file column.

    Returns:
        pandas.DataFrame with full schema (ISA_elem_*, CLM_*, NM1_*, etc.).
    """
    if file_path is not None and content is not None:
        raise ValueError("Provide either file_path or content, not both")
    if file_path is not None:
        result = parse_837p(file_path)
        src = source_file or str(Path(file_path).name)
    elif content is not None:
        result = parse_837p_string(content)
        src = source_file
    else:
        raise ValueError("Provide either file_path or content")
    return result.to_claims_dataframe_full(source_file=src)


def parse_837p_to_service_lines_dataframe(
    file_path: str | Path | None = None,
    content: str | None = None,
    source_file: str | None = None,
):
    """
    Parse 837P and return a pandas DataFrame (one row per service line).
    For Palantir Foundry: use spark.createDataFrame(df) on the result.

    Args:
        file_path: Path to EDI file (mutually exclusive with content).
        content: Raw EDI content string (mutually exclusive with file_path).
        source_file: Optional filename for the source_file column.

    Returns:
        pandas.DataFrame with columns: provider_name, claim_id, line_number,
        procedure_code, line_charge_amount, service_date, etc., and optionally source_file.
    """
    if file_path is not None and content is not None:
        raise ValueError("Provide either file_path or content, not both")
    if file_path is not None:
        result = parse_837p(file_path)
        src = source_file or str(Path(file_path).name)
    elif content is not None:
        result = parse_837p_string(content)
        src = source_file
    else:
        raise ValueError("Provide either file_path or content")
    return result.to_service_lines_dataframe(source_file=src)
