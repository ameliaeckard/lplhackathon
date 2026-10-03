import sys
from pathlib import Path

import joblib
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.document_extractor import extract_case
from rules.beneficiary_rules import evaluate_beneficiary_case
from ml.model_features import FEATURE_COLUMNS, build_feature_row

MODEL_PATH = PROJECT_ROOT / "ml" / "models" / "resolve_model.joblib"

DISPLAY_FIELDS = [
    "beneficiary_type",
    "beneficiary_name",
    "representative_name",
    "representative_capacity",
    "estate_ein_status",
    "destination_account",
    "death_certificate_status",
    "letters_testamentary_status",
    "trust_document_status",
    "guardianship_document_status",
    "w8_ben_status",
    "signature_status",
]

STATUS_LABELS = {
    "needs_attention": "Needs Attention",
    "no_detected_exception": "No Detected Exception",
    "unable_to_determine": "Unable to Determine",
}


def build_extraction_summary(extracted):
    return {field: extracted.get(field) for field in DISPLAY_FIELDS}


def predict_with_saved_model(extracted):
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Resolve model not found: {MODEL_PATH}. Run python3 main.py first."
        )

    model = joblib.load(MODEL_PATH)
    features = build_feature_row(extracted)
    frame = pd.DataFrame([features], columns=FEATURE_COLUMNS)

    prediction = int(model.predict(frame)[0])
    probability = float(model.predict_proba(frame)[0][1])

    return {
        "prediction": (
            "needs_attention" if prediction == 1 else "no_detected_exception"
        ),
        "model_score": round(probability, 4),
        "score_note": (
            "Experimental model score from the controlled synthetic training set. "
            "It is not a calibrated probability of real-world workflow failure."
        ),
    }


def process_case(pdf_path, source_name=None):
    """Run one new PDF through live Resolve inference. No retraining occurs."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    extracted = extract_case(pdf_path)
    fallback_id = Path(source_name or pdf_path.name).stem
    case_id = extracted.get("case_id") or fallback_id
    extracted["case_id"] = case_id

    rules_result = evaluate_beneficiary_case(extracted)
    ml_result = predict_with_saved_model(extracted)

    rules_status = rules_result.get("status", "unable_to_determine")
    status_label = STATUS_LABELS.get(rules_status, "Unable to Determine")
    findings = rules_result.get("findings", []) or []
    uncertainties = extracted.get("uncertainties", []) or []

    comparable = rules_status in {"needs_attention", "no_detected_exception"}
    agreement = (
        ml_result["prediction"] == rules_status if comparable else None
    )
    human_review = bool(
        rules_status == "unable_to_determine"
        or uncertainties
        or agreement is False
    )

    issue_codes = [f.get("code") for f in findings if f.get("code")]
    issues = [f.get("message") or f.get("code") for f in findings]
    recommended_actions = []
    for finding in findings:
        action = finding.get("recommended_action")
        if action and action not in recommended_actions:
            recommended_actions.append(action)

    workflow_type = extracted.get("workflow_type") or "beneficiary_claim"
    workflow = "Beneficiary Claim" if workflow_type == "beneficiary_claim" else workflow_type.replace("_", " ").title()
    client = extracted.get("beneficiary_name") or extracted.get("account_number") or "Unknown beneficiary"

    if findings:
        reason = " ".join(str(i) for i in issues if i)
    elif rules_status == "no_detected_exception":
        reason = "No exception was detected by the implemented deterministic checks."
    else:
        reason = "Resolve could not determine one or more required fields from the document package."

    ml_result["agreement"] = agreement

    return {
        "case_id": case_id,
        "workflow_type": workflow_type,
        "workflow": workflow,
        "account_number": extracted.get("account_number"),
        "beneficiary_name": extracted.get("beneficiary_name"),
        "client": client,
        "status_code": rules_status,
        "status": status_label,
        "decision_source": "deterministic_rules",
        "human_review": human_review,
        "issues": issues,
        "issue_codes": issue_codes,
        "reason": reason,
        "findings": findings,
        "recommended_actions": recommended_actions,
        "ml": ml_result,
        "extraction": build_extraction_summary(extracted),
        "evidence": extracted.get("evidence", []) or [],
        "uncertainties": uncertainties,
    }
