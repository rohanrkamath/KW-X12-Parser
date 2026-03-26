"""
837P full-fidelity parser: preserves every segment and loop for repackaging.
Supports hold/release: parse -> process -> repackage EDI minus held claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .segment_parser import parse_string, Delimiters
from .hierarchical_parser import _parse_837p_from_segments
from .claim_models import (
    Parsed837P,
    Segment,
    SubscriberClaim,
)


def _extract_claim_id_from_raw(raw: str, elem_sep: str, seg_term: str) -> str | None:
    """Extract CLM01 from raw block content."""
    for raw_seg in raw.split(seg_term):
        raw_seg = raw_seg.strip()
        if not raw_seg:
            continue
        parts = raw_seg.split(elem_sep)
        if parts and parts[0].strip() == "CLM":
            return parts[1].strip() if len(parts) > 1 else None
    return None


@dataclass
class EdiBlock:
    """One HL block (billing provider or claim) with full raw EDI content."""

    hl_id: str
    parent_id: str | None
    level_code: str  # 20 = billing provider, 22 = claim
    raw_content: str  # HL + all segments until next HL (no trailing terminator)
    claim_id: str | None = None  # From CLM01 if level 22


@dataclass
class Parsed837PFull(Parsed837P):
    """
    Full-fidelity 837P parse: every segment and loop preserved.
    Use to_edi_string(exclude_claim_ids) or write_edi() to repackage minus held claims.
    """

    delimiters: Delimiters = field(default_factory=lambda: Delimiters("*", ":", "~"))  # Set from parse
    raw_isa: str = ""
    raw_gs: str = ""
    raw_header: str = ""  # ST, BHT, Loop 1000A, 1000B - before first HL
    raw_blocks: list[EdiBlock] = field(default_factory=list)
    raw_se: str = ""
    raw_ge: str = ""
    raw_iea: str = ""

    # Map claim_id -> index in raw_blocks (for filtering)
    _claim_id_to_block_idx: dict[str, int] = field(default_factory=dict, repr=False)

    # Every segment in the file (ISA through IEA) in document order
    complete_segments: list[Segment] = field(default_factory=list, repr=False)

    def iter_every_segment(self):
        """Yield every segment in the file (ISA through IEA) in document order."""
        for seg in self.complete_segments:
            yield seg

    def get_all_claim_ids(self) -> list[str]:
        """Return all claim IDs in order (for hold/release logic)."""
        return [b.claim_id for b in self.raw_blocks if b.claim_id is not None]

    def get_claim_by_id(self, claim_id: str) -> SubscriberClaim | None:
        """Get SubscriberClaim for a given claim_id."""
        for bp in self.billing_providers:
            for c in bp.claims:
                if c.claim_id == claim_id:
                    return c
        return None

    def iter_all_segments_per_claim(self):
        """Yield (claim_id, segment) for every segment in every claim."""
        for bp in self.billing_providers:
            for claim in bp.claims:
                for seg in claim.segments:
                    yield claim.claim_id, seg
                for sl in claim.service_lines:
                    for seg in sl.segments:
                        yield claim.claim_id, seg

    def to_edi_string(
        self,
        *,
        exclude_claim_ids: set[str] | None = None,
        include_claim_ids: set[str] | None = None,
        include_claim_ids_fn: Callable[[str], bool] | None = None,
        isa15_usage_indicator: str | None = None,
    ) -> str:
        """
        Repackage EDI string, optionally excluding held claims.

        Args:
            exclude_claim_ids: Claim IDs to omit (held claims).
            include_claim_ids: If set, only include these claim IDs (released claims).
            include_claim_ids_fn: Callable(claim_id) -> bool; if provided, include claim when True.
            isa15_usage_indicator: Optional ISA15 override ("T" test / "P" production).

        Returns:
            Valid 837P EDI string (minus excluded claims).
        """
        exclude = exclude_claim_ids or set()
        include = include_claim_ids
        fn = include_claim_ids_fn

        def claim_included(block: EdiBlock) -> bool:
            if block.claim_id is None:
                return False
            if block.claim_id in exclude:
                return False
            if include is not None and block.claim_id not in include:
                return False
            if fn is not None and not fn(block.claim_id):
                return False
            return True

        def provider_has_included_claims(hl_id: str) -> bool:
            return any(
                claim_included(b) for b in self.raw_blocks
                if b.parent_id == hl_id and b.claim_id is not None
            )

        def should_include_block(block: EdiBlock) -> bool:
            if block.claim_id is None:
                return provider_has_included_claims(block.hl_id)
            return claim_included(block)

        def _renumber_hl_blocks(blocks: list[EdiBlock]) -> list[EdiBlock]:
            """
            Renumber HL01 sequentially and remap HL02 parent references for included blocks.
            This keeps Loop 2000 HL hierarchy valid after claim filtering.
            """
            e = self.delimiters.element
            old_to_new: dict[str, str] = {}

            # First pass: assign new sequential HL IDs in output order.
            for idx, b in enumerate(blocks, start=1):
                old_to_new[b.hl_id] = str(idx)

            remapped: list[EdiBlock] = []
            for b in blocks:
                segs = [s for s in b.raw_content.split(t) if s.strip()]
                if not segs:
                    remapped.append(b)
                    continue

                hl_parts = segs[0].split(e)
                if len(hl_parts) >= 2:
                    hl_parts[1] = old_to_new.get(b.hl_id, hl_parts[1])
                if len(hl_parts) >= 3:
                    old_parent = hl_parts[2].strip()
                    if old_parent:
                        hl_parts[2] = old_to_new.get(old_parent, hl_parts[2])
                    else:
                        hl_parts[2] = ""
                segs[0] = e.join(hl_parts)

                remapped.append(
                    EdiBlock(
                        hl_id=old_to_new.get(b.hl_id, b.hl_id),
                        parent_id=old_to_new.get(b.parent_id, b.parent_id) if b.parent_id else None,
                        level_code=b.level_code,
                        raw_content=t.join(segs),
                        claim_id=b.claim_id,
                    )
                )
            return remapped

        t = self.delimiters.segment_term
        raw_isa = self.raw_isa
        if isa15_usage_indicator is not None:
            parts = raw_isa.split(self.delimiters.element)
            if len(parts) >= 16:
                parts[15] = isa15_usage_indicator
                raw_isa = self.delimiters.element.join(parts)
        parts: list[str] = [raw_isa, self.raw_gs, self.raw_header]

        included_blocks = [b for b in self.raw_blocks if should_include_block(b)]
        included_blocks = _renumber_hl_blocks(included_blocks)
        for block in included_blocks:
            parts.append(block.raw_content)

        # Recalculate SE01 (segment count)
        header_count = len([s for s in self.raw_header.split(t) if s.strip()])
        block_count = sum(len([s for s in b.raw_content.split(t) if s.strip()]) for b in included_blocks)
        total_seg_count = header_count + block_count + 1  # +1 for SE
        se_parts = self.raw_se.split(self.delimiters.element)
        if len(se_parts) >= 2:
            se_parts[1] = str(total_seg_count)
            parts.append(self.delimiters.element.join(se_parts))
        else:
            parts.append(self.raw_se)

        parts.extend([self.raw_ge, self.raw_iea])
        return t.join(parts)


    def write_edi(
        self,
        path: str | Path,
        *,
        exclude_claim_ids: set[str] | None = None,
        include_claim_ids: set[str] | None = None,
        include_claim_ids_fn: Callable[[str], bool] | None = None,
        isa15_usage_indicator: str | None = None,
    ) -> None:
        """Write repackaged EDI to file. See to_edi_string() for args."""
        content = self.to_edi_string(
            exclude_claim_ids=exclude_claim_ids,
            include_claim_ids=include_claim_ids,
            include_claim_ids_fn=include_claim_ids_fn,
            isa15_usage_indicator=isa15_usage_indicator,
        )
        Path(path).write_text(content, encoding="utf-8")


def parse_837p_full(
    content: str | None = None,
    file_path: str | Path | None = None,
) -> Parsed837PFull:
    """
    Parse 837P with full preservation for repackaging.
    Use to_edi_string(exclude_claim_ids=held) or write_edi() to rebuild EDI minus held claims.
    """
    if content is None and file_path is None:
        raise ValueError("Provide content or file_path")
    if content is not None and file_path is not None:
        raise ValueError("Provide either content or file_path, not both")
    if file_path is not None:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    base = parse_string(content)
    result = _parse_837p_from_segments(base.segments)
    full = Parsed837PFull(
        submitter=result.submitter,
        receiver=result.receiver,
        bht=result.bht,
        billing_providers=result.billing_providers,
        all_segments=result.all_segments,
    )
    full.delimiters = base.delimiters

    # Store every segment (ISA through IEA) for full access
    full.complete_segments = [
        Segment(id=s.id, elements=list(s.elements)) for s in base.segments
    ]

    t = base.delimiters.segment_term
    raw_list = base.raw_segments

    # Find indices
    isa_idx = next((i for i, r in enumerate(raw_list) if r.startswith("ISA")), 0)
    gs_idx = next((i for i, r in enumerate(raw_list) if r.startswith("GS")), 1)
    st_idx = next((i for i, r in enumerate(raw_list) if r.startswith("ST")), 2)
    hl_indices = [i for i, r in enumerate(raw_list) if r.startswith("HL")]
    se_idx = next((i for i, r in enumerate(raw_list) if r.startswith("SE")), -1)
    ge_idx = next((i for i, r in enumerate(raw_list) if r.startswith("GE")), -1)
    iea_idx = next((i for i, r in enumerate(raw_list) if r.startswith("IEA")), -1)

    full.raw_isa = raw_list[isa_idx] if isa_idx < len(raw_list) else ""
    full.raw_gs = raw_list[gs_idx] if gs_idx < len(raw_list) else ""

    first_hl = hl_indices[0] if hl_indices else len(raw_list)
    header_raws = raw_list[st_idx:first_hl]
    full.raw_header = t.join(header_raws)

    for i, hi in enumerate(hl_indices):
        end = hl_indices[i + 1] if i + 1 < len(hl_indices) else se_idx
        if end < 0:
            end = len(raw_list)
        block_raws = raw_list[hi:end]
        raw_content = t.join(block_raws)
        parts = block_raws[0].split(base.delimiters.element)  # HL segment
        hl_id = parts[1].strip() if len(parts) > 1 else ""
        parent_id = parts[2].strip() if len(parts) > 2 else None
        if parent_id == "":
            parent_id = None
        level_code = parts[3].strip() if len(parts) > 3 else ""
        claim_id = (
            _extract_claim_id_from_raw(raw_content, base.delimiters.element, base.delimiters.segment_term)
            if level_code == "22"
            else None
        )
        full.raw_blocks.append(
            EdiBlock(
                hl_id=hl_id,
                parent_id=parent_id,
                level_code=level_code,
                raw_content=raw_content,
                claim_id=claim_id,
            )
        )
        if claim_id:
            full._claim_id_to_block_idx[claim_id] = len(full.raw_blocks) - 1

    full.raw_se = raw_list[se_idx] if 0 <= se_idx < len(raw_list) else ""
    full.raw_ge = raw_list[ge_idx] if 0 <= ge_idx < len(raw_list) else ""
    full.raw_iea = raw_list[iea_idx] if 0 <= iea_idx < len(raw_list) else ""

    return full
