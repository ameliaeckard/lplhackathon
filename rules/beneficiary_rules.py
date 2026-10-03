def make_finding(
    code,
    field,
    message,
    recommended_action,
    severity="attention"
):
    return {
        "code": code,
        "field": field,
        "severity": severity,
        "message": message,
        "recommended_action": recommended_action
    }


def evaluate_beneficiary_case(case):
    """
    Apply explicit beneficiary-claim requirements.

    These rules do not alter Claude's extraction.
    They evaluate the extracted facts.
    """

    findings = []

    # ----------------------------------
    # Death certificate
    # Required for beneficiary claims
    # ----------------------------------

    death_status = case.get(
        "death_certificate_status"
    )

    if death_status == "not_found":

        findings.append(
            make_finding(
                code="MISSING_DEATH_CERTIFICATE",
                field="death_certificate_status",
                message=(
                    "A certified death certificate "
                    "was not found in the case package."
                ),
                recommended_action=(
                    "Request a certified copy of the "
                    "death certificate."
                )
            )
        )

    elif death_status == "unknown":

        findings.append(
            make_finding(
                code="REVIEW_DEATH_CERTIFICATE",
                field="death_certificate_status",
                message=(
                    "Resolve could not determine whether "
                    "a certified death certificate is present."
                ),
                recommended_action=(
                    "Review the case package for a "
                    "certified death certificate."
                ),
                severity="review"
            )
        )

    # ----------------------------------
    # Signature
    # ----------------------------------

    signature_status = case.get(
        "signature_status"
    )

    if signature_status == "not_found":

        findings.append(
            make_finding(
                code="MISSING_SIGNATURE",
                field="signature_status",
                message=(
                    "A completed signature was not "
                    "found on the beneficiary form."
                ),
                recommended_action=(
                    "Request a completed signed "
                    "beneficiary claim form."
                )
            )
        )

    elif signature_status == "unknown":

        findings.append(
            make_finding(
                code="REVIEW_SIGNATURE",
                field="signature_status",
                message=(
                    "Resolve could not determine "
                    "whether the form is signed."
                ),
                recommended_action=(
                    "Review the submitted form "
                    "for a completed signature."
                ),
                severity="review"
            )
        )

    # ----------------------------------
    # Estate-specific rules
    # ----------------------------------

    beneficiary_type = (
        case.get("beneficiary_type")
        or ""
    ).lower()

    if beneficiary_type == "estate":

        # EIN
        ein = case.get(
            "estate_ein"
        )

        ein_status = case.get(
            "estate_ein_status"
        )

        if (
            ein_status == "not_found"
            or not ein
        ):

            findings.append(
                make_finding(
                    code="MISSING_ESTATE_EIN",
                    field="estate_ein",
                    message=(
                        "An Estate EIN was not found "
                        "in the case package."
                    ),
                    recommended_action=(
                        "Request the Estate Tax ID "
                        "Number / EIN."
                    )
                )
            )

        elif ein_status == "unknown":

            findings.append(
                make_finding(
                    code="REVIEW_ESTATE_EIN",
                    field="estate_ein_status",
                    message=(
                        "Resolve could not determine "
                        "whether the Estate EIN is present."
                    ),
                    recommended_action=(
                        "Review the case for the "
                        "Estate Tax ID Number / EIN."
                    ),
                    severity="review"
                )
            )

        # Letters Testamentary
        letters_status = case.get(
            "letters_testamentary_status"
        )

        if letters_status == "not_found":

            findings.append(
                make_finding(
                    code="MISSING_LETTERS_TESTAMENTARY",
                    field="letters_testamentary_status",
                    message=(
                        "Court-certified Letters of "
                        "Testamentary were not found "
                        "in the case package."
                    ),
                    recommended_action=(
                        "Request court-certified "
                        "Letters of Testamentary "
                        "from the executor."
                    )
                )
            )

        elif letters_status == "unknown":

            findings.append(
                make_finding(
                    code="REVIEW_LETTERS_TESTAMENTARY",
                    field="letters_testamentary_status",
                    message=(
                        "Resolve could not determine "
                        "whether Letters of Testamentary "
                        "are present."
                    ),
                    recommended_action=(
                        "Review the package for "
                        "court-certified Letters "
                        "of Testamentary."
                    ),
                    severity="review"
                )
            )

    # ----------------------------------
    # Overall Resolve status
    # ----------------------------------

    attention_findings = [
        finding
        for finding in findings
        if finding["severity"] == "attention"
    ]

    review_findings = [
        finding
        for finding in findings
        if finding["severity"] == "review"
    ]

    if attention_findings:

        status = "needs_attention"

    elif review_findings:

        status = "unable_to_determine"

    else:

        status = "no_detected_exception"

    return {
        "case_id": case.get("case_id"),
        "workflow_type": case.get(
            "workflow_type"
        ),
        "account_number": case.get(
            "account_number"
        ),

        "beneficiary_name": case.get(
            "beneficiary_name"
        ),

        "beneficiary_type": case.get(
            "beneficiary_type"
        ),

        "status": status,

        "findings": findings
    }