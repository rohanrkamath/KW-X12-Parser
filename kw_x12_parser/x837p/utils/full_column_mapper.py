"""
Build one row per claim with semantic X12-style column names.
Maps segments/elements to human-readable columns like:
  BHT_Date, CLM_Claim_Submitters_Identifier, NM1_BILLING_PROVIDER_Name_First,
  DTP_472_Date, SV1_1_HCPCS_CODE, SV1_1_LINE_CHARGE, etc.
"""

from __future__ import annotations

from typing import Any

from .claim_models import BillingProvider, Segment, SubscriberClaim

# NM101 Entity Identifier -> column prefix (837P common roles)
NM1_QUALIFIER_TO_PREFIX: dict[str, str] = {
    "41": "SUBMITTER",
    "40": "RECEIVER",
    "85": "BILLING_PROVIDER",
    "87": "PAY_TO_ADDRESS",
    "XV": "PAY_TO_PLAN",
    "IL": "SUBSCRIBER",
    "QC": "PATIENT",
    "PR": "PAYER",
    "DN": "REFERRING_PROVIDER",
    "DK": "RENDERING_PROVIDER",
    "82": "RENDERING_PROVIDER",  # alternate
    "77": "SERVICE_FACILITY_LOCATION",
    "DQ": "ORDERING_PROVIDER",  # or SUPERVISING_PROVIDER
    "45": "AMBULANCE_DROP_OFF_LOCATION",
    "PW": "AMBULANCE_PICK_UP_LOCATION",
}

# DTP qualifiers to capture (DTP01) -> column suffix
DTP_QUALIFIERS = frozenset(
    "11 50 297 304 431 435 439 444 454 455 461 463 471 472 485 565 573 738 739".split()
)

# Max service lines to expand into columns (SV1_1 .. SV1_N)
MAX_SV1_LINES = 20


def _parse_sv1_composite(sv1_01: str | None) -> dict[str, str | None]:
    """Parse SV1-01 composite HC:qualifier:code:mod1:mod2:mod3:mod4:desc"""
    out: dict[str, str | None] = {
        "HCPCS_CODE": None,
        "MODIFIER_1": None,
        "MODIFIER_2": None,
        "MODIFIER_3": None,
        "MODIFIER_4": None,
    }
    if not sv1_01:
        return out
    parts = str(sv1_01).split(":")
    # HC:code or HC:code:mod or HC:code:mod:mod...
    if len(parts) >= 2:
        out["HCPCS_CODE"] = parts[1]
    for i, p in enumerate(parts[2:6]):
        if p:
            out[f"MODIFIER_{i+1}"] = p
    return out


def _extract_nm1_n3_n4(
    segments: list[Segment],
    cob_detection: bool = False,
) -> dict[str, dict[str, str | None]]:
    """
    Extract NM1/N3/N4 by entity. Returns {PREFIX: {Name_First, Name_Last, Address_Line1, City, State, Zip, ...}}

    When cob_detection=True (claim segments), NM1*IL and NM1*PR after SBR*P (patient/COB block)
    are stored as OTHER_SUBSCRIBER and OTHER_PAYER instead of overwriting SUBSCRIBER/PAYER.
    """
    entities: dict[str, dict[str, str | None]] = {}
    current_prefix: str | None = None
    current_entity: dict[str, str | None] | None = None
    in_cob_block = False
    seen_sbr_s = False
    cob_prefix_map = {"IL": "OTHER_SUBSCRIBER", "PR": "OTHER_PAYER"} if cob_detection else {}

    i = 0
    while i < len(segments):
        s = segments[i]
        if s.id == "SBR" and cob_detection:
            q = (s.get(1) or "").strip()
            if q == "S":
                seen_sbr_s = True
            elif q == "P":
                in_cob_block = seen_sbr_s  # Only COB block when SBR*S was first
            i += 1
        elif s.id == "LX" and cob_detection:
            in_cob_block = False
            current_prefix = None
            current_entity = None
            i += 1
        elif s.id == "NM1":
            q = s.get(1) or ""
            prefix = cob_prefix_map.get(q, NM1_QUALIFIER_TO_PREFIX.get(q, q)) if in_cob_block else NM1_QUALIFIER_TO_PREFIX.get(q, q)
            current_prefix = prefix
            current_entity = {
                "Entity_Type_Qualifier": s.get(2),
                "Name_Last_or_Organization_Name": s.get(3),
                "Name_First": s.get(4),
                "Name_Middle": s.get(5),
                "Identification_Code_Qualifier": s.get(8),
                "Identification_Code": s.get(9),
                "Address_Line1": None,
                "Address_Line2": None,
                "City": None,
                "State": None,
                "Zip": None,
            }
            # Merge if same prefix appears multiple times (e.g. RENDERING per line)
            if prefix not in entities or not entities[prefix].get("Name_Last_or_Organization_Name"):
                entities[prefix] = current_entity.copy()
            i += 1
        elif s.id == "N3" and current_entity:
            a1 = s.get(1)
            a2 = s.get(2)
            if current_prefix and current_prefix in entities:
                entities[current_prefix]["Address_Line1"] = a1
                entities[current_prefix]["Address_Line2"] = a2
            i += 1
        elif s.id == "N4" and current_entity:
            city = s.get(1)
            state = s.get(2)
            zip_ = s.get(3)
            if current_prefix and current_prefix in entities:
                entities[current_prefix]["City"] = city
                entities[current_prefix]["State"] = state
                entities[current_prefix]["Zip"] = zip_
            i += 1
        else:
            current_prefix = None
            current_entity = None
            i += 1
    return entities


def _extract_per(segments: list[Segment]) -> dict[str, str | None]:
    """Extract first PER segment. Returns ContactQualifier, Name, Comm1_Qual, Comm1_Number, etc."""
    per = next((s for s in segments if s.id == "PER"), None)
    if not per:
        return {}
    return {
        "ContactQualifier": per.get(1),
        "Name": per.get(2),
        "Comm1_Qualifier": per.get(3),
        "Comm1_Number": per.get(4),
        "Comm2_Qualifier": per.get(5),
        "Comm2_Number": per.get(6),
        "Comm3_Qualifier": per.get(7),
        "Comm3_Number": per.get(8),
    }


def _extract_ref_by_qualifier(segments: list[Segment]) -> dict[str, list[str | None]]:
    """Extract REF segments by qualifier. Returns {EI: [val], G2: [val1, val2], 1G: [val], ...}"""
    out: dict[str, list[str | None]] = {}
    for s in segments:
        if s.id != "REF":
            continue
        q = (s.get(1) or "").strip()
        if q:
            if q not in out:
                out[q] = []
            out[q].append(s.get(2))
    return out


def _extract_hi(segments: list[Segment]) -> dict[str, Any]:
    """Extract HI segment. Returns Codes (pipe-joined) and HI_01..HI_12."""
    hi = next((s for s in segments if s.id == "HI"), None)
    if not hi:
        return {}
    codes = []
    result: dict[str, Any] = {}
    for i in range(1, 13):
        v = hi.get(i)
        result[f"HI_{i:02d}"] = v
        if v:
            codes.append(v)
    result["HI_Codes"] = "|".join(codes) if codes else None
    return result


def _extract_prv(segments: list[Segment]) -> dict[str, str | None]:
    """Extract PRV segment."""
    prv = next((s for s in segments if s.id == "PRV"), None)
    if not prv:
        return {}
    return {
        "ProviderCode": prv.get(1),
        "ReferenceQualifier": prv.get(2),
        "ReferenceId": prv.get(3),
    }


def _extract_amt_by_qualifier(segments: list[Segment]) -> dict[str, str | None]:
    """Extract AMT segments by qualifier."""
    out: dict[str, str | None] = {}
    for s in segments:
        if s.id != "AMT":
            continue
        q = (s.get(1) or "").strip()
        if q:
            out[q] = s.get(2)
    return out


def _extract_dtp_by_qualifier(segments: list[Segment]) -> dict[str, dict[str, str | None]]:
    """Extract DTP segments by qualifier. Returns {qualifier: {Date, Format, Qualifier}}"""
    out: dict[str, dict[str, str | None]] = {}
    for s in segments:
        if s.id != "DTP":
            continue
        q = s.get(1) or ""
        if q in DTP_QUALIFIERS or True:  # include any DTP
            out[q] = {
                "Qualifier": q,
                "Format": s.get(2),
                "Date": s.get(3),
            }
    return out


def _add_envelope_columns(
    row: dict[str, Any],
    isa_seg: Segment | None,
    gs_seg: Segment | None,
    se_seg: Segment | None,
    ge_seg: Segment | None,
    iea_seg: Segment | None,
) -> None:
    """Add ISA, GS, SE, GE, IEA columns (common for all claims in file)."""
    for seg, prefix in [(isa_seg, "ISA"), (gs_seg, "GS"), (se_seg, "SE"), (ge_seg, "GE"), (iea_seg, "IEA")]:
        if seg:
            for i in range(1, min(len(seg.elements) + 1, 17)):
                row[f"{prefix}_elem_{i:02d}"] = seg.get(i)


def _build_full_claim_row(
    bp: BillingProvider,
    claim: SubscriberClaim,
    submitter_segments: list[Segment],
    receiver_segments: list[Segment],
    bht: Segment | None,
    st_seg: Segment | None,
    source_file: str | None,
    isa_seg: Segment | None = None,
    gs_seg: Segment | None = None,
    se_seg: Segment | None = None,
    ge_seg: Segment | None = None,
    iea_seg: Segment | None = None,
) -> dict[str, Any]:
    """Build one row with semantic columns for a single claim."""
    row: dict[str, Any] = {}

    # Envelope (ISA, GS, GE, IEA, SE) - common for all claims in file
    _add_envelope_columns(row, isa_seg, gs_seg, se_seg, ge_seg, iea_seg)

    # HL hierarchy
    row["HL_Claim_ID"] = claim.hl_node.hl_id
    row["HL_Claim_Parent_ID"] = claim.hl_node.parent_id
    row["HL_Claim_Level_Code"] = claim.hl_node.level_code
    row["HL_Claim_Child_Code"] = claim.hl_node.child_code
    row["HL_BillingProvider_ID"] = bp.hl_node.hl_id
    row["HL_BillingProvider_Parent_ID"] = bp.hl_node.parent_id
    row["HL_BillingProvider_Level_Code"] = bp.hl_node.level_code

    # Segment order (for reconstruction)
    row["SEGMENT_ORDER"] = "|".join(s.id for s in claim.all_segments)

    # ST
    if st_seg:
        row["ST_Transaction_Set_Identifier_Code"] = st_seg.get(1)
        row["ST_Transaction_Set_Control_Number"] = st_seg.get(2)

    # PER (submitter, receiver)
    per_sub = _extract_per(submitter_segments)
    if per_sub:
        for k, v in per_sub.items():
            row[f"PER_SUBMITTER_{k}"] = v
    per_rec = _extract_per(receiver_segments)
    if per_rec:
        for k, v in per_rec.items():
            row[f"PER_RECEIVER_{k}"] = v

    # BHT
    if bht:
        row["BHT_Transaction_Set_Purpose_Code"] = bht.get(1)
        row["BHT_Transaction_Type_Code"] = bht.get(2)
        row["BHT_Reference_Identification"] = bht.get(3)
        row["BHT_Date"] = bht.get(4)
        row["BHT_Time"] = bht.get(5)
        row["BHT_Hierarchical_Structure_Code"] = bht.get(6)

    # CLM
    clm = claim.get_one("CLM")
    if clm:
        row["CLM_Claim_Submitters_Identifier"] = clm.get(1)
        row["CLM_Monetary_Amount"] = clm.get(2)
        row["CLM_HEALTH_CARE_SERVICE_LOCATION_INFORMATION"] = clm.get(5)
        row["CLM_Provider_Accept_Assignment_Code"] = clm.get(6)
        row["CLM_Yes_No_Condition_or_Response_Code_1"] = clm.get(7)
        row["CLM_Release_of_Information_Code"] = clm.get(8)
        row["CLM_Patient_Signature_Source_Code"] = clm.get(9)
        row["CLM_Claim_Frequency_Type_Code"] = clm.get(12)
        row["CLM_Related_Causes_Code_1"] = clm.get(13)
        row["CLM_Related_Causes_Code_2"] = clm.get(14)
        row["CLM_Special_Program_Code"] = clm.get(15)
        row["CLM_Yes_No_Condition_or_Response_Code_2"] = clm.get(16)
        row["CLM_Related_Causes_Code_3"] = clm.get(17)
        row["CLM_Delay_Reason_Code"] = clm.get(18)
        row["CLM_State_or_Province_Code"] = clm.get(19)
        row["CLM_Country_Code"] = clm.get(20)
        row["CLM_Facility_Code_Qualifier"] = clm.get(21)
        row["CLM_Facility_Code_Value"] = clm.get(22)
        row["CLM_RELATED_CAUSES_INFORMATION"] = clm.get(13)  # composite

    # DMG
    dmg = claim.get_one("DMG")
    if dmg:
        row["DMG_Date_Time_Period_Format_Qualifier"] = dmg.get(1)
        row["DMG_Date_Time_Period"] = dmg.get(2)
        row["DMG_Gender_Code"] = dmg.get(3)

    # SBR (use qualifier P/S from element 1, not position)
    sbr_list = claim.get("SBR")
    for sbr in sbr_list or []:
        q = (sbr.get(1) or "").strip()
        if q == "P":
            row["SBR_P_Payer_Responsibility"] = sbr.get(1)
            row["SBR_P_Relationship_Code"] = sbr.get(2)
            row["SBR_P_Subscriber_GroupNumber"] = sbr.get(3)
            row["SBR_P_Subscriber_PatientRelationship"] = sbr.get(9)
        elif q == "S":
            row["SBR_S_Payer_Responsibility"] = sbr.get(1)
            row["SBR_S_Relationship_Code"] = sbr.get(2)
            row["SBR_S_Subscriber_GroupNumber"] = sbr.get(3)
            row["SBR_S_Subscriber_PatientRelationship"] = sbr.get(9)

    # Submit claim + provider segments for NM1/N3/N4
    all_claim_segs = list(claim.segments)
    for sl in claim.service_lines:
        all_claim_segs.extend(sl.segments)

    # REF by qualifier (support multiple values: REF_1G_1, REF_1G_2, REF_1G_All)
    ref_bp = _extract_ref_by_qualifier(bp.segments)
    ref_claim = _extract_ref_by_qualifier(all_claim_segs)
    ref_merged: dict[str, list[str | None]] = {}
    for q, vals in ref_bp.items():
        ref_merged.setdefault(q, []).extend(vals)
    for q, vals in ref_claim.items():
        ref_merged.setdefault(q, []).extend(vals)
    for q, vals in ref_merged.items():
        for i, v in enumerate(vals[:10]):  # up to 10 per qualifier
            row[f"REF_{q}_{i+1}"] = v
        if vals:
            row[f"REF_{q}_All"] = "|".join(str(v or "") for v in vals)

    # HI (diagnosis)
    hi_data = _extract_hi(all_claim_segs)
    for k, v in hi_data.items():
        row[k] = v  # HI_01, HI_02, ..., HI_Codes

    # PRV (billing provider)
    prv_data = _extract_prv(bp.segments)
    for k, v in prv_data.items():
        row[f"PRV_{k}"] = v

    # AMT by qualifier
    amt_bp = _extract_amt_by_qualifier(bp.segments)
    amt_claim = _extract_amt_by_qualifier(all_claim_segs)
    for q, v in {**amt_bp, **amt_claim}.items():
        row[f"AMT_{q}"] = v

    # NM1/N3/N4 from header (submitter, receiver)
    submitter_entities = _extract_nm1_n3_n4(submitter_segments)
    receiver_entities = _extract_nm1_n3_n4(receiver_segments)
    bp_entities = _extract_nm1_n3_n4(bp.segments)
    claim_entities = _extract_nm1_n3_n4(all_claim_segs, cob_detection=True)

    def _add_nm1_columns(entities: dict):
        nm1_fields = ("Entity_Type_Qualifier", "Name_Last_or_Organization_Name", "Name_First",
                      "Name_Middle", "Identification_Code_Qualifier", "Identification_Code")
        for ent_name, ent_data in entities.items():
            d = ent_data or {}
            for k in nm1_fields:
                row[f"NM1_{ent_name}_{k}"] = d.get(k)
        for ent_name, ent_data in entities.items():
            d = ent_data or {}
            row[f"N3_{ent_name}_Address_Line1"] = d.get("Address_Line1")
            row[f"N3_{ent_name}_Address_Line2"] = d.get("Address_Line2")
        for ent_name, ent_data in entities.items():
            d = ent_data or {}
            row[f"N4_{ent_name}_City"] = d.get("City")
            row[f"N4_{ent_name}_State"] = d.get("State")
            row[f"N4_{ent_name}_Zip"] = d.get("Zip")

    _add_nm1_columns(submitter_entities)
    _add_nm1_columns(receiver_entities)
    _add_nm1_columns(bp_entities)
    _add_nm1_columns(claim_entities)

    # DTP by qualifier
    dtp_map = _extract_dtp_by_qualifier(all_claim_segs)
    for q, d in dtp_map.items():
        row[f"DTP_{q}_Qualifier"] = d.get("Qualifier")
        row[f"DTP_{q}_Format"] = d.get("Format")
        row[f"DTP_{q}_Date"] = d.get("Date")

    # LX, SV1, DTP, CAS, SVD per service line (1..20)
    line_charges: list[str] = []
    line_hcpcs: list[str] = []
    line_qty: list[str] = []
    line_uom: list[str] = []
    total_charge = 0.0
    for idx, sl in enumerate(claim.service_lines[:MAX_SV1_LINES]):
        n = idx + 1
        # LX
        lx = sl.get_one("LX")
        if lx:
            row[f"LX_{n}_LineNumber"] = lx.get(1)
        # SV1
        sv1 = sl.get_one("SV1")
        dtp472 = sl.get_one("DTP")
        svc_date = None
        if dtp472 and dtp472.get(1) == "472":
            svc_date = dtp472.get(3)
        # DTP (all qualifiers per line)
        for d in sl.get("DTP"):
            q = d.get(1) or ""
            if q:
                row[f"DTP_Line{n}_{q}_Date"] = d.get(3)
                row[f"DTP_Line{n}_{q}_Format"] = d.get(2)
        # CAS
        for cas_idx, cas in enumerate(sl.get("CAS")[:3]):  # up to 3 CAS per line
            cn = f"{n}" if cas_idx == 0 else f"{n}_{cas_idx+1}"
            row[f"CAS_{cn}_GroupCode"] = cas.get(1)
            row[f"CAS_{cn}_ClaimAdjustmentGroupCode"] = cas.get(2)
            row[f"CAS_{cn}_Amount"] = cas.get(3)
        # SVD
        svd = sl.get_one("SVD")
        if svd:
            row[f"SVD_{n}_PayerIdentifier"] = svd.get(1)
            row[f"SVD_{n}_Amount"] = svd.get(2)
            row[f"SVD_{n}_Composite"] = svd.get(3)

        # Per-line NM1/N3/N4 for RENDERING (DK) - may differ by service line
        sl_nm1 = sl.get_one("NM1")
        if sl_nm1 and (sl_nm1.get(1) in ("DK", "82")):
            row[f"NM1_RENDERING_{n}_Name_Last_or_Organization_Name"] = sl_nm1.get(3)
            row[f"NM1_RENDERING_{n}_Name_First"] = sl_nm1.get(4)
            row[f"NM1_RENDERING_{n}_Identification_Code"] = sl_nm1.get(9)
        sl_n3 = sl.get_one("N3")
        if sl_n3:
            row[f"N3_RENDERING_{n}_Address_Line1"] = sl_n3.get(1)
            row[f"N3_RENDERING_{n}_Address_Line2"] = sl_n3.get(2)
        sl_n4 = sl.get_one("N4")
        if sl_n4:
            row[f"N4_RENDERING_{n}_City"] = sl_n4.get(1)
            row[f"N4_RENDERING_{n}_State"] = sl_n4.get(2)
            row[f"N4_RENDERING_{n}_Zip"] = sl_n4.get(3)

        if sv1:
            comp = _parse_sv1_composite(sv1.get(1))
            row[f"SV1_{n}_HCPCS_CODE"] = comp["HCPCS_CODE"]
            row[f"SV1_{n}_MODIFIER_1"] = comp["MODIFIER_1"]
            row[f"SV1_{n}_MODIFIER_2"] = comp["MODIFIER_2"]
            row[f"SV1_{n}_MODIFIER_3"] = comp["MODIFIER_3"]
            row[f"SV1_{n}_MODIFIER_4"] = comp["MODIFIER_4"]
            row[f"SV1_{n}_LINE_CHARGE"] = sv1.get(2)
            row[f"SV1_{n}_UNIT_OF_MEASURE"] = sv1.get(3)
            row[f"SV1_{n}_QUANTITY"] = sv1.get(4)
            row[f"SV1_{n}_PLACE_OF_SERVICE"] = sv1.get(5)
            row[f"SV1_{n}_SERVICE_DATE"] = svc_date
            ch = sv1.get(2)
            if ch:
                try:
                    total_charge += float(ch)
                except ValueError:
                    pass
            line_charges.append(ch or "")
            line_hcpcs.append(comp["HCPCS_CODE"] or "")
            line_qty.append(sv1.get(4) or "")
            line_uom.append(sv1.get(3) or "")

    row["SV1_LINE_COUNT"] = len(claim.service_lines)
    row["SV1_TOTAL_CHARGE"] = str(total_charge) if total_charge else None
    row["SV1_HCPCS_CODES"] = "|".join(line_hcpcs) if line_hcpcs else None
    row["SV1_LINE_CHARGES"] = "|".join(line_charges) if line_charges else None
    row["SV1_QUANTITIES"] = "|".join(line_qty) if line_qty else None
    row["SV1_UNITS_OF_MEASURE"] = "|".join(line_uom) if line_uom else None

    row["TRANSACTION_ID"] = bht.get(3) if bht else claim.claim_id
    row["claim_id"] = claim.claim_id
    row["provider_name"] = bp.name
    row["provider_npi"] = bp.npi

    if source_file:
        row["source_file"] = source_file
        row["file_name"] = source_file

    row["EDI_FILE_TYPE"] = "837P"

    # Catch-all: add every segment as SEG_<id>_<n>_elem_01..elem_25
    HANDLED = frozenset("ST BHT PER CLM DMG SBR REF HI PRV AMT NM1 N3 N4 DTP LX SV1 CAS SVD HL".split())
    all_segs = submitter_segments + receiver_segments + bp.segments + all_claim_segs
    seg_counts: dict[str, int] = {}
    for seg in all_segs:
        if seg.id in HANDLED:
            continue
        seg_counts[seg.id] = seg_counts.get(seg.id, 0) + 1
        n = seg_counts[seg.id]
        prefix = f"SEG_{seg.id}_{n}"
        for i, val in enumerate(seg.elements[:25]):
            row[f"{prefix}_elem_{i+1:02d}"] = val or None

    return row
