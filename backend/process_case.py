import json
import os
import sys
import time
from pathlib import Path

import boto3
import joblib
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.document_extractor import extract_case
from rules.beneficiary_rules import evaluate_beneficiary_case
from ml.model_features import FEATURE_COLUMNS, build_feature_row

MODEL_PATH = PROJECT_ROOT / "ml" / "models" / "resolve_model.joblib"
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")

DISPLAY_FIELDS = [
    "beneficiary_type","beneficiary_name","representative_name","representative_capacity",
    "nonresident_alien","estate_ein_status","destination_account","destination_account_present",
    "death_certificate_status","letters_testamentary_status","trust_document_status",
    "guardianship_document_status","w8_ben_status","signature_status",
]

FIELD_RULE_LABELS = {
    "death_certificate_status": "Beneficiary claim package requires a certified death certificate.",
    "signature_status": "Beneficiary claim form requires the applicable beneficiary signature.",
    "letters_testamentary_status": "Estate beneficiary requires court-certified Letters of Testamentary.",
    "estate_ein_status": "Estate beneficiary requires a Tax ID Number / EIN.",
    "trust_document_status": "Trust beneficiary requires trust documentation.",
    "guardianship_document_status": "Minor or conservatorship beneficiary requires guardianship or conservatorship documentation.",
    "w8_ben_status": "Non-resident beneficiary requires Form W-8BEN.",
}

STATUS_LABELS = {
    "needs_attention": "Needs Attention",
    "no_detected_exception": "No Detected Exception",
    "unable_to_determine": "Unable to Determine",
}
INFO_ONLY_REP_FIELDS = {"representative_name","representative_capacity"}

def _log(request_id, message, **fields):
    detail = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    print(f"[R'Solv][{request_id}] {message}" + (f" | {detail}" if detail else ""), flush=True)

def build_extraction_summary(extracted):
    return {field: extracted.get(field) for field in DISPLAY_FIELDS}

def predict_with_saved_model(extracted, request_id):
    _log(request_id, "ML prediction started")
    started = time.perf_counter()
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"R'Solv model not found: {MODEL_PATH}. Keep your existing trained resolve_model.joblib in ml/models/.")
    model = joblib.load(MODEL_PATH)
    features = build_feature_row(extracted)
    frame = pd.DataFrame([features], columns=FEATURE_COLUMNS)
    prediction = int(model.predict(frame)[0])
    probability = float(model.predict_proba(frame)[0][1])
    result = {
        "prediction": "needs_attention" if prediction == 1 else "no_detected_exception",
        "model_score": round(probability, 4),
        "score_note": (
            "Experimental model score from the controlled synthetic training set. "
            "It is not a calibrated probability of real-world workflow failure."
        ),
    }
    _log(request_id, "ML prediction complete", prediction=result["prediction"], score=result["model_score"], seconds=f"{time.perf_counter()-started:.2f}")
    return result

def normalize_note(item):
    if isinstance(item, dict):
        field = item.get("field") or item.get("label") or "note"
        reason = item.get("reason") or item.get("message") or item.get("text") or ""
        return {"field":field,"label":field.replace("_"," ").title(),"reason":str(reason)}
    return {"field":"note","label":"Note","reason":str(item)}

def split_uncertainties(extracted):
    beneficiary_type = str(extracted.get("beneficiary_type") or "").lower()
    uncertainties, document_notes = [], []
    for raw in extracted.get("uncertainties", []) or []:
        note = normalize_note(raw)
        field = note["field"]
        individual_like = ("individual" in beneficiary_type or beneficiary_type == "child")
        if individual_like and field in INFO_ONLY_REP_FIELDS:
            note["reason"] = "No representative was identified because the beneficiary appears to be acting on their own behalf."
            document_notes.append(note)
        else:
            uncertainties.append(note)
    return uncertainties, document_notes

def fallback_summary(extracted, rules_status, findings, recommended_actions):
    client = extracted.get("beneficiary_name") or "This beneficiary claim"
    if findings:
        message = findings[0].get("message") or "R'Solv found a document exception."
        next_step = recommended_actions[0] if recommended_actions else "Review the flagged requirement before the case proceeds."
        return f"{client}: {message}", next_step
    if rules_status == "no_detected_exception":
        return (
            f"R'Solv reviewed {client} and did not detect an exception under the implemented beneficiary checks.",
            "Continue the normal review process and verify any requirements outside the current C.A.R.D. rule set.",
        )
    return (
        f"R'Solv could not confidently determine one or more required fields for {client}.",
        "Review the unresolved document fields before the case proceeds.",
    )

def generate_case_summary(extracted, rules_status, findings, recommended_actions, uncertainties, request_id):
    fallback = fallback_summary(extracted, rules_status, findings, recommended_actions)
    payload = {
        "beneficiary_name": extracted.get("beneficiary_name"),
        "beneficiary_type": extracted.get("beneficiary_type"),
        "representative_capacity": extracted.get("representative_capacity"),
        "death_certificate_status": extracted.get("death_certificate_status"),
        "letters_testamentary_status": extracted.get("letters_testamentary_status"),
        "estate_ein_status": extracted.get("estate_ein_status"),
        "signature_status": extracted.get("signature_status"),
        "rule_status": rules_status,
        "findings": findings,
        "recommended_actions": recommended_actions,
        "unresolved_fields": uncertainties,
    }
    prompt = f"""
You are writing a short operations summary for R'Solv's C.A.R.D.
(Case. Automatic. Review. Dashboard.) beneficiary-claim prototype.

Use ONLY the structured facts below. Do not invent facts, legal conclusions,
approval status, compliance status, probabilities, or requirements that are
not explicitly present.

The deterministic rule result is authoritative. Do not contradict or change it.

Write JSON only:
{{
  "summary": "One or two natural, concise sentences explaining what R'Solv found.",
  "next_step": "One concise operational next step."
}}

Writing rules:
- Sound like a helpful operations analyst, not a chatbot.
- If the rule status is no_detected_exception, say that no exception was
  detected under the implemented checks. Do NOT say approved or compliant.
- If something is missing, name the specific item.
- If a field is unresolved, explain that it needs review.
- Do not mention XGBoost or a model score.

Structured case:
{json.dumps(payload, indent=2)}
""".strip()
    _log(request_id, "Claude case-summary generation started")
    started = time.perf_counter()
    try:
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        response = bedrock.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[{"role":"user","content":[{"text":prompt}]}],
            inferenceConfig={"temperature":0,"maxTokens":220},
        )
        text = response["output"]["message"]["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        result = json.loads(text)
        summary = str(result.get("summary") or "").strip()
        next_step = str(result.get("next_step") or "").strip()
        if not summary:
            _log(request_id, "Claude summary empty; using deterministic fallback")
            return fallback
        _log(request_id, "Claude case-summary generation complete", seconds=f"{time.perf_counter()-started:.2f}")
        return summary, next_step or fallback[1]
    except Exception as error:
        _log(request_id, "Claude summary failed; using fallback", error=repr(error))
        return fallback


def _find_evidence(extracted, field):
    for item in extracted.get("evidence", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("field") or "") == field:
            return str(item.get("evidence") or item.get("value") or "").strip()
    return ""


def build_decision_trace(extracted, findings):
    trace = []

    for finding in findings:
        field = finding.get("field")
        if not field:
            continue

        trace.append({
            "code": finding.get("code"),
            "field": field,
            "fact_value": extracted.get(field) if extracted.get(field) is not None else "unknown",
            "evidence": _find_evidence(extracted, field) or "No direct evidence snippet was captured for this field.",
            "rule": FIELD_RULE_LABELS.get(field, "Implemented deterministic requirement check."),
            "result": finding.get("message") or finding.get("code"),
        })

    return trace


def build_resolution_preview(extracted, findings):
    items = []

    for finding in findings:
        field = finding.get("field")
        code = str(finding.get("code") or "")

        if not field:
            continue

        label = field.replace("_status", "").replace("_", " ").title()
        current = str(extracted.get(field) or "unknown").replace("_", " ").title()

        if code.startswith("MISSING_"):
            items.append({
                "code": code,
                "field": field,
                "title": finding.get("message") or code,
                "current_label": label,
                "current_value": current,
                "change_description": (
                    f"If verified documentation changes {label.lower()} to Present, "
                    "this specific missing-document rule would no longer trigger."
                ),
                "effect": (
                    "Preview only. Other implemented requirements may still require attention, "
                    "and this does not approve the claim."
                ),
            })

        elif code.startswith("REVIEW_"):
            items.append({
                "code": code,
                "field": field,
                "title": finding.get("message") or code,
                "current_label": label,
                "current_value": current,
                "change_description": (
                    f"Verify the underlying evidence so {label.lower()} can be resolved "
                    "from Unknown to a supported state."
                ),
                "effect": (
                    "Resolving the unknown removes this review-only finding if the resulting "
                    "state does not trigger another deterministic requirement."
                ),
            })

    return items


def process_case(pdf_path, source_name=None, request_id="no-request-id"):
    pdf_path = Path(pdf_path)
    total_started = time.perf_counter()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    _log(request_id, "Claude document extraction started", filename=source_name or pdf_path.name)
    extract_started = time.perf_counter()
    extracted = extract_case(pdf_path)
    _log(request_id, "Claude document extraction complete", seconds=f"{time.perf_counter()-extract_started:.2f}", beneficiary_type=extracted.get("beneficiary_type"))

    fallback_id = Path(source_name or pdf_path.name).stem
    case_id = extracted.get("case_id") or fallback_id
    extracted["case_id"] = case_id
    _log(request_id, "Case identified", case_id=case_id)

    _log(request_id, "Deterministic rules started")
    rules_started = time.perf_counter()
    rules_result = evaluate_beneficiary_case(extracted)
    rules_status = rules_result.get("status", "unable_to_determine")
    findings = rules_result.get("findings", []) or []
    _log(request_id, "Deterministic rules complete", status=rules_status, findings=len(findings), seconds=f"{time.perf_counter()-rules_started:.2f}")

    ml_result = predict_with_saved_model(extracted, request_id)
    status_label = STATUS_LABELS.get(rules_status, "Unable to Determine")
    uncertainties, document_notes = split_uncertainties(extracted)

    comparable = rules_status in {"needs_attention","no_detected_exception"}
    agreement = ml_result["prediction"] == rules_status if comparable else None
    human_review = bool(rules_status in {"needs_attention","unable_to_determine"} or uncertainties or agreement is False)

    issue_codes = [f.get("code") for f in findings if f.get("code")]
    issues = [f.get("message") or f.get("code") for f in findings]
    recommended_actions = []
    for finding in findings:
        action = finding.get("recommended_action")
        if action and action not in recommended_actions:
            recommended_actions.append(action)

    workflow_type = extracted.get("workflow_type") or "beneficiary_claim"
    workflow = "Beneficiary Claim" if workflow_type == "beneficiary_claim" else workflow_type.replace("_"," ").title()
    client = extracted.get("beneficiary_name") or extracted.get("account_number") or "Unknown beneficiary"

    if findings:
        reason = " ".join(str(issue) for issue in issues if issue)
    elif rules_status == "no_detected_exception":
        reason = "No exception was detected by the implemented deterministic checks."
    else:
        reason = "R'Solv could not determine one or more required fields from the document package."

    ml_result["agreement"] = agreement
    summary, summary_next_step = generate_case_summary(
        extracted, rules_status, findings, recommended_actions, uncertainties, request_id
    )

    result = {
        "case_id":case_id,"workflow_type":workflow_type,"workflow":workflow,
        "account_number":extracted.get("account_number"),
        "beneficiary_name":extracted.get("beneficiary_name"),
        "client":client,"status_code":rules_status,"status":status_label,
        "decision_source":"deterministic_rules","human_review":human_review,
        "issues":issues,"issue_codes":issue_codes,"reason":reason,
        "summary":summary,"summary_next_step":summary_next_step,
        "summary_source":"claude_with_fallback","findings":findings,
        "recommended_actions":recommended_actions,"ml":ml_result,
        "extraction":build_extraction_summary(extracted),
        "evidence":extracted.get("evidence",[]) or [],
        "uncertainties":uncertainties,"document_notes":document_notes,
        "decision_trace":build_decision_trace(extracted, findings),
        "resolution_preview":build_resolution_preview(extracted, findings),
    }
    _log(request_id, "Live case processing complete", case_id=case_id, status=status_label, human_review=human_review, seconds=f"{time.perf_counter()-total_started:.2f}")
    return result
