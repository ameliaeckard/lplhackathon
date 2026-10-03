from rules.beneficiary_rules import evaluate_beneficiary_case


def base_case():
    return {
        "beneficiary_type": "individual",
        "death_certificate_status": "present",
        "signature_status": "present",
        "letters_testamentary_status": "not_applicable",
        "estate_ein_status": "not_applicable",
        "trust_document_status": "not_applicable",
        "guardianship_document_status": "not_applicable",
        "w8_ben_status": "not_applicable",
        "nonresident_alien": False,
    }


def test_individual_clear():
    result = evaluate_beneficiary_case(base_case())
    assert result["status"] == "no_detected_exception"


def test_missing_death_certificate():
    case = base_case()
    case["death_certificate_status"] = "not_found"
    result = evaluate_beneficiary_case(case)
    assert result["status"] == "needs_attention"
    assert "MISSING_DEATH_CERTIFICATE" in [f["code"] for f in result["findings"]]


def test_estate_needs_letters_and_ein():
    case = base_case()
    case.update({
        "beneficiary_type": "estate",
        "letters_testamentary_status": "not_found",
        "estate_ein_status": "not_found",
    })
    result = evaluate_beneficiary_case(case)
    codes = [f["code"] for f in result["findings"]]
    assert "MISSING_LETTERS_TESTAMENTARY" in codes
    assert "MISSING_ESTATE_EIN" in codes
