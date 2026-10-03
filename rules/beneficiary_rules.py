REVIEW_STATUS = "unable_to_determine"
ATTENTION_STATUS = "needs_attention"
CLEAR_STATUS = "no_detected_exception"

MISSING = "not_found"
UNKNOWN = "unknown"


def _finding(code, message, action, severity="blocking", field=None):
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "recommended_action": action,
        "field": field,
    }


def _check_required(findings, case, field, missing_code, review_code, missing_message, review_message, action):
    value = str(case.get(field) or UNKNOWN).lower()

    if value == MISSING:
        findings.append(_finding(
            missing_code,
            missing_message,
            action,
            severity="blocking",
            field=field,
        ))
    elif value == UNKNOWN:
        findings.append(_finding(
            review_code,
            review_message,
            f"Verify {field.replace('_status', '').replace('_', ' ')} in the document package.",
            severity="review",
            field=field,
        ))


def evaluate_beneficiary_case(case):
    """Deterministic checks for the beneficiary-claim prototype."""
    findings = []
    beneficiary_type = str(case.get("beneficiary_type") or "unknown").lower()

    _check_required(
        findings,
        case,
        "death_certificate_status",
        "MISSING_DEATH_CERTIFICATE",
        "REVIEW_DEATH_CERTIFICATE",
        "Certified death certificate was not found.",
        "Death certificate status could not be determined.",
        "Request or verify a certified copy of the death certificate.",
    )

    _check_required(
        findings,
        case,
        "signature_status",
        "MISSING_SIGNATURE",
        "REVIEW_SIGNATURE",
        "Required beneficiary signature was not found.",
        "Signature status could not be determined.",
        "Request or verify the required signature.",
    )

    if "estate" in beneficiary_type:
        _check_required(
            findings,
            case,
            "letters_testamentary_status",
            "MISSING_LETTERS_TESTAMENTARY",
            "REVIEW_LETTERS_TESTAMENTARY",
            "Estate beneficiary is missing court-certified Letters of Testamentary.",
            "Letters of Testamentary status could not be determined for the estate beneficiary.",
            "Request or verify court-certified Letters of Testamentary.",
        )
        _check_required(
            findings,
            case,
            "estate_ein_status",
            "MISSING_ESTATE_EIN",
            "REVIEW_ESTATE_EIN",
            "Estate Tax ID Number / EIN was not found.",
            "Estate EIN status could not be determined.",
            "Request or verify the estate Tax ID Number / EIN.",
        )

    if "trust" in beneficiary_type:
        _check_required(
            findings,
            case,
            "trust_document_status",
            "MISSING_TRUST_DOCUMENT",
            "REVIEW_TRUST_DOCUMENT",
            "Required trust documentation was not found.",
            "Trust-document status could not be determined.",
            "Request or verify a complete copy of the trust.",
        )

    child_like = any(token in beneficiary_type for token in ("child", "minor", "conservator", "guardian"))
    if child_like:
        _check_required(
            findings,
            case,
            "guardianship_document_status",
            "MISSING_GUARDIANSHIP_DOCUMENTATION",
            "REVIEW_GUARDIANSHIP_DOCUMENTATION",
            "Required guardianship or conservatorship documentation was not found.",
            "Guardianship or conservatorship documentation could not be determined.",
            "Request or verify Letters of Guardianship or Conservatorship.",
        )

    if case.get("nonresident_alien") is True:
        _check_required(
            findings,
            case,
            "w8_ben_status",
            "MISSING_W8_BEN",
            "REVIEW_W8_BEN",
            "Form W-8BEN was not found for the non-resident beneficiary.",
            "Form W-8BEN status could not be determined.",
            "Request or verify Form W-8BEN.",
        )

    has_blocking = any(f["severity"] == "blocking" for f in findings)
    has_review = any(f["severity"] == "review" for f in findings)

    if has_blocking:
        status = ATTENTION_STATUS
    elif has_review:
        status = REVIEW_STATUS
    else:
        status = CLEAR_STATUS

    return {"status": status, "findings": findings}
