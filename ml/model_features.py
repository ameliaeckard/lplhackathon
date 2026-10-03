FEATURE_COLUMNS = [
    "beneficiary_type",
    "estate_ein_status",
    "death_certificate_status",
    "letters_testamentary_status",
    "trust_document_status",
    "guardianship_document_status",
    "w8_ben_status",
    "signature_status",
    "destination_account_present",
    "unknown_field_count"
]


STATUS_FIELDS = [
    "estate_ein_status",
    "death_certificate_status",
    "letters_testamentary_status",
    "trust_document_status",
    "guardianship_document_status",
    "w8_ben_status",
    "signature_status"
]


def count_unknowns(case):

    return sum(
        1
        for field in STATUS_FIELDS
        if case.get(field) == "unknown"
    )


def build_feature_row(case):

    return {
        "beneficiary_type": case.get(
            "beneficiary_type"
        ),

        "estate_ein_status": case.get(
            "estate_ein_status"
        ),

        "death_certificate_status": case.get(
            "death_certificate_status"
        ),

        "letters_testamentary_status": case.get(
            "letters_testamentary_status"
        ),

        "trust_document_status": case.get(
            "trust_document_status"
        ),

        "guardianship_document_status": case.get(
            "guardianship_document_status"
        ),

        "w8_ben_status": case.get(
            "w8_ben_status"
        ),

        "signature_status": case.get(
            "signature_status"
        ),

        "destination_account_present": (
            1
            if case.get(
                "destination_account"
            )
            else 0
        ),

        "unknown_field_count": count_unknowns(
            case
        )
    }