import json
import logging
import os
from pathlib import Path

import boto3
from pypdf import PdfReader


logging.getLogger("pypdf").setLevel(logging.ERROR)


AWS_REGION = os.getenv(
    "AWS_REGION",
    "us-east-1"
)

BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID"
)


VALID_STATUSES = {
    "present",
    "not_found",
    "not_applicable",
    "unknown"
}


ALLOWED_EVIDENCE_FIELDS = {
    "case_id",
    "workflow_type",
    "account_number",
    "beneficiary_type",
    "beneficiary_name",
    "representative_name",
    "representative_capacity",
    "estate_ein",
    "estate_ein_status",
    "destination_account",
    "death_certificate_status",
    "letters_testamentary_status",
    "trust_document_status",
    "guardianship_document_status",
    "w8_ben_status",
    "signature_status"
}


def extract_pdf_text(pdf_path):
    """
    Extract page text and interactive PDF form fields.
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {pdf_path}"
        )

    reader = PdfReader(pdf_path)

    parts = []

    # Page text
    for page_number, page in enumerate(
        reader.pages,
        start=1
    ):
        page_text = page.extract_text()

        if page_text:
            parts.append(
                f"\n--- PAGE {page_number} ---\n"
                f"{page_text}"
            )

    # PDF form fields
    fields = reader.get_fields() or {}

    if fields:
        parts.append(
            "\n--- PDF FORM FIELDS ---\n"
        )

        for field_name, field_data in fields.items():

            value = field_data.get("/V")

            if value is None:
                continue

            parts.append(
                f"{field_name}: {value}"
            )

    text = "\n".join(parts)

    if not text.strip():
        raise RuntimeError(
            "No readable PDF content was extracted."
        )

    return text


def build_extraction_prompt(document_text):
    """
    Claude performs fact extraction only.
    """

    return f"""
You are the document extraction component of Resolve.

Resolve is currently processing only beneficiary claim
documents.

You are reading the complete extracted contents of one
synthetic beneficiary claim case package.

The supplied content may contain:

1. normal PDF page text
2. interactive PDF form-field values
3. synthetic supporting records appended to the PDF

Your ONLY job is to extract facts explicitly supported
by the supplied document.

IMPORTANT RULES:

- Do not invent values.
- Do not assume values.
- Do not use outside knowledge.
- Do not determine compliance.
- Do not approve or reject the case.
- Do not calculate risk.
- Do not predict whether the case will fail.
- Do not decide whether the case needs correction.
- Do not infer legal or procedural requirements.
- PDF form fields count as document evidence.
- Supporting-document instructions are not evidence
  that the supporting document itself is present.

Do not interpret internal PDF control values such as:

/0
/1
/2
checkbox codes
radio button codes
field indexes

unless the supplied document explicitly establishes
what the value means.

Do not add personal information that is not part of
the requested schema.

Do not add SSNs, addresses, unrelated dates of birth,
or other identifiers to evidence.

-----------------------------------
STATUS VALUES
-----------------------------------

Status fields must use exactly one of:

"present"
"not_found"
"not_applicable"
"unknown"

Definitions:

"present"
= the item is explicitly present.

"not_found"
= the complete supplied case PDF was inspected and
  the item does not appear.

"not_applicable"
= the item clearly does not apply to this beneficiary
  type.

"unknown"
= the document does not provide enough information.

IMPORTANT:

"not_found" does not mean:

- invalid
- rejected
- non-compliant
- needs correction

Resolve's deterministic rules make those decisions later.

-----------------------------------
RETURN FORMAT
-----------------------------------

Return valid JSON only.

Do not use Markdown.

Use exactly this structure:

{{
  "case_id": null,
  "workflow_type": "beneficiary_claim",
  "account_number": null,

  "beneficiary_type": null,
  "beneficiary_name": null,

  "representative_name": null,
  "representative_capacity": null,

  "estate_ein": null,
  "estate_ein_status": "unknown",

  "destination_account": null,

  "death_certificate_status": "unknown",
  "letters_testamentary_status": "unknown",
  "trust_document_status": "unknown",
  "guardianship_document_status": "unknown",
  "w8_ben_status": "unknown",
  "signature_status": "unknown",

  "evidence": [],
  "uncertainties": []
}}

-----------------------------------
APPLICABILITY
-----------------------------------

Use the beneficiary type when determining whether a
supporting document is applicable.

For example:

Estate:
- trust document normally does not apply
- guardianship document normally does not apply
- W-8 BEN does not apply when the supplied record
  explicitly establishes the beneficiary is a US person

Do not treat "not applicable" as "not found."

-----------------------------------
EVIDENCE
-----------------------------------

Only add evidence for fields that exist in the schema.

Each evidence item must look like:

{{
  "field": "beneficiary_type",
  "value": "estate",
  "evidence_text": "Beneficiary type: Estate",
  "page": 6
}}

If the evidence comes from a PDF form field and its
page cannot reliably be determined, use:

"page": null

Keep evidence short and factual.

-----------------------------------
UNCERTAINTIES
-----------------------------------

Only add an uncertainty when:

- the extracted value is null

OR

- its status is "unknown"

Do not add uncertainty for fields already classified
as:

"present"
"not_found"
"not_applicable"

Do not add unrelated ambiguities.

-----------------------------------
DOCUMENT
-----------------------------------

{document_text}
"""


def clean_json_response(response_text):
    text = response_text.strip()

    if text.startswith("```json"):
        text = text[7:]

    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


def normalize_status(value):
    """
    Prevent unexpected status labels.
    """

    if value is None:
        return "unknown"

    value = str(value).strip().lower()

    if value not in VALID_STATUSES:
        return "unknown"

    return value


def get_field_value(result, field):
    """
    Used to decide whether an uncertainty
    still belongs in the final result.
    """

    if field in result:
        return result.get(field)

    return None


def sanitize_result(result):
    """
    Enforce the beneficiary-only schema after Claude.

    This does not invent document facts.
    """

    clean = {
        "case_id": result.get("case_id"),
        "workflow_type": "beneficiary_claim",
        "account_number": result.get("account_number"),

        "beneficiary_type": result.get(
            "beneficiary_type"
        ),

        "beneficiary_name": result.get(
            "beneficiary_name"
        ),

        "representative_name": result.get(
            "representative_name"
        ),

        "representative_capacity": result.get(
            "representative_capacity"
        ),

        "estate_ein": result.get(
            "estate_ein"
        ),

        "estate_ein_status": normalize_status(
            result.get("estate_ein_status")
        ),

        "destination_account": result.get(
            "destination_account"
        ),

        "death_certificate_status": normalize_status(
            result.get("death_certificate_status")
        ),

        "letters_testamentary_status": normalize_status(
            result.get("letters_testamentary_status")
        ),

        "trust_document_status": normalize_status(
            result.get("trust_document_status")
        ),

        "guardianship_document_status": normalize_status(
            result.get("guardianship_document_status")
        ),

        "w8_ben_status": normalize_status(
            result.get("w8_ben_status")
        ),

        "signature_status": normalize_status(
            result.get("signature_status")
        ),

        "evidence": [],
        "uncertainties": []
    }

    # Normalize beneficiary type
    if clean["beneficiary_type"] is not None:
        clean["beneficiary_type"] = (
            str(clean["beneficiary_type"])
            .strip()
            .lower()
        )

    # Keep evidence only for approved schema fields
    evidence = result.get(
        "evidence",
        []
    )

    for item in evidence:

        if not isinstance(item, dict):
            continue

        field = item.get("field")

        if field not in ALLOWED_EVIDENCE_FIELDS:
            continue

        clean["evidence"].append({
            "field": field,
            "value": item.get("value"),
            "evidence_text": item.get(
                "evidence_text"
            ),
            "page": item.get("page")
        })

    # Keep uncertainties only when the
    # actual field is null or unknown.
    uncertainties = result.get(
        "uncertainties",
        []
    )

    for item in uncertainties:

        if not isinstance(item, dict):
            continue

        field = item.get("field")

        if not field:
            continue

        value = get_field_value(
            clean,
            field
        )

        if value is None or value == "unknown":

            clean["uncertainties"].append(
                item
            )

    return clean


def validate_result(result):
    """
    Schema sanity check only.

    This is NOT a compliance check.
    """

    if not isinstance(result, dict):
        raise ValueError(
            "Claude did not return a JSON object."
        )

    if result.get("workflow_type") != "beneficiary_claim":
        raise ValueError(
            "Expected beneficiary_claim workflow."
        )

    status_fields = [
        "estate_ein_status",
        "death_certificate_status",
        "letters_testamentary_status",
        "trust_document_status",
        "guardianship_document_status",
        "w8_ben_status",
        "signature_status"
    ]

    for field in status_fields:

        value = result.get(field)

        if value not in VALID_STATUSES:
            raise ValueError(
                f"Invalid {field}: {value}"
            )


def extract_case(pdf_path):
    """
    PDF
      -> text + form fields
      -> Claude
      -> sanitized JSON
    """

    if not BEDROCK_MODEL_ID:
        raise RuntimeError(
            "BEDROCK_MODEL_ID is not set."
        )

    document_text = extract_pdf_text(
        pdf_path
    )

    prompt = build_extraction_prompt(
        document_text
    )

    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=AWS_REGION
    )

    response = bedrock.converse(
        modelId=BEDROCK_MODEL_ID,

        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],

        inferenceConfig={
            "temperature": 0,
            "maxTokens": 2500
        }
    )

    content = (
        response["output"]
        ["message"]
        ["content"]
    )

    response_text = None

    for block in content:

        if "text" in block:
            response_text = block["text"]
            break

    if response_text is None:
        raise RuntimeError(
            "Claude returned no text."
        )

    cleaned = clean_json_response(
        response_text
    )

    try:
        raw_result = json.loads(
            cleaned
        )

    except json.JSONDecodeError as error:

        raise RuntimeError(
            "Claude did not return valid JSON.\n\n"
            f"{response_text}"
        ) from error

    result = sanitize_result(
        raw_result
    )

    validate_result(
        result
    )

    return result