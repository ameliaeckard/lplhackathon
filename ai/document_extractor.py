import io
import json
import os
from pathlib import Path

import boto3
from pypdf import PdfReader

AWS_REGION = os.getenv("AWS_REGION","us-east-1")
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-sonnet-4-6",
)

STATUS_VALUES={"present","not_found","not_applicable","unknown"}

PROMPT = """
You are extracting structured facts from a beneficiary claim document for
R'Solv C.A.R.D. (Case. Automatic. Review. Dashboard.).

Return JSON ONLY. Do not add markdown.

Use only evidence visible in the supplied document/text. Do not infer legal
approval, compliance, or requirements that are not shown.

Required JSON shape:
{
  "case_id": string | null,
  "workflow_type": "beneficiary_claim",
  "account_number": string | null,
  "beneficiary_type": "individual" | "estate" | "trust" | "individual_child" | "minor" | "conservatorship" | "other" | "unknown",
  "beneficiary_name": string | null,
  "representative_name": string | null,
  "representative_capacity": string | null,
  "nonresident_alien": true | false | null,
  "estate_ein_status": "present" | "not_found" | "not_applicable" | "unknown",
  "destination_account": string | null,
  "destination_account_present": true | false | null,
  "death_certificate_status": "present" | "not_found" | "not_applicable" | "unknown",
  "letters_testamentary_status": "present" | "not_found" | "not_applicable" | "unknown",
  "trust_document_status": "present" | "not_found" | "not_applicable" | "unknown",
  "guardianship_document_status": "present" | "not_found" | "not_applicable" | "unknown",
  "w8_ben_status": "present" | "not_found" | "not_applicable" | "unknown",
  "signature_status": "present" | "not_found" | "not_applicable" | "unknown",
  "evidence": [
    {"field": string, "value": string | null, "evidence": string}
  ],
  "uncertainties": [
    {"field": string, "reason": string}
  ]
}

Rules:
- beneficiary_type should describe the claimant/entity visible in the package.
- "not_found" means the item was expected/relevant enough to search for, but it
  was not found in the supplied package.
- "not_applicable" means the document makes clear the item does not apply.
- "unknown" means the document is too unclear to decide.
- Never put full SSNs, home addresses, passwords, or unrelated sensitive data
  into evidence.
- Keep evidence short and tied to the field it supports.
""".strip()


def _clean_json_text(text):
    text=text.strip()
    if text.startswith("```"):
        text=text.strip("`").strip()
        if text.lower().startswith("json"):
            text=text[4:].strip()
    return text


def _normalize_status(value):
    value=str(value or "unknown").strip().lower()
    return value if value in STATUS_VALUES else "unknown"


def _normalize(data):
    if not isinstance(data,dict):
        data={}

    result={
        "case_id":data.get("case_id"),
        "workflow_type":"beneficiary_claim",
        "account_number":data.get("account_number"),
        "beneficiary_type":data.get("beneficiary_type") or "unknown",
        "beneficiary_name":data.get("beneficiary_name"),
        "representative_name":data.get("representative_name"),
        "representative_capacity":data.get("representative_capacity"),
        "nonresident_alien":data.get("nonresident_alien"),
        "estate_ein_status":_normalize_status(data.get("estate_ein_status")),
        "destination_account":data.get("destination_account"),
        "destination_account_present":data.get("destination_account_present"),
        "death_certificate_status":_normalize_status(data.get("death_certificate_status")),
        "letters_testamentary_status":_normalize_status(data.get("letters_testamentary_status")),
        "trust_document_status":_normalize_status(data.get("trust_document_status")),
        "guardianship_document_status":_normalize_status(data.get("guardianship_document_status")),
        "w8_ben_status":_normalize_status(data.get("w8_ben_status")),
        "signature_status":_normalize_status(data.get("signature_status")),
        "evidence":data.get("evidence") if isinstance(data.get("evidence"),list) else [],
        "uncertainties":data.get("uncertainties") if isinstance(data.get("uncertainties"),list) else [],
    }

    if result["nonresident_alien"] not in {True,False,None}:
        result["nonresident_alien"]=None

    if result["destination_account_present"] not in {True,False,None}:
        result["destination_account_present"]=bool(result["destination_account"]) if result["destination_account"] else None

    # Keep evidence limited to known fields.
    allowed={
        "case_id","account_number","beneficiary_type","beneficiary_name",
        "representative_name","representative_capacity","nonresident_alien","estate_ein_status",
        "destination_account","destination_account_present","death_certificate_status",
        "letters_testamentary_status","trust_document_status",
        "guardianship_document_status","w8_ben_status","signature_status",
    }

    cleaned=[]
    for item in result["evidence"]:
        if not isinstance(item,dict):
            continue
        field=str(item.get("field") or "")
        if field not in allowed:
            continue
        cleaned.append({
            "field":field,
            "value":item.get("value"),
            "evidence":str(item.get("evidence") or "")[:500],
        })
    result["evidence"]=cleaned

    return result


def _extract_text_and_fields(pdf_path):
    reader=PdfReader(str(pdf_path))
    chunks=[]
    for page_number,page in enumerate(reader.pages,start=1):
        text=page.extract_text() or ""
        if text.strip():
            chunks.append(f"--- PAGE {page_number} ---\n{text}")

    form_lines=[]
    try:
        fields=reader.get_fields() or {}
        for name,field in fields.items():
            value=field.get("/V")
            if value not in (None,""):
                form_lines.append(f"{name}: {value}")
    except Exception:
        pass

    body="\n\n".join(chunks)
    if form_lines:
        body += "\n\n--- PDF FORM FIELDS ---\n" + "\n".join(form_lines)

    return body.strip()


def _render_pages_as_jpeg(pdf_path,max_pages=10,dpi=115):
    import fitz

    doc=fitz.open(str(pdf_path))
    images=[]

    try:
        page_count=min(len(doc),max_pages)
        for index in range(page_count):
            page=doc[index]
            pix=page.get_pixmap(dpi=dpi,alpha=False)
            images.append(pix.tobytes("jpeg",jpg_quality=72))
    finally:
        doc.close()

    return images


def _converse_with_text(text):
    client=boto3.client("bedrock-runtime",region_name=AWS_REGION)
    content=[{"text":PROMPT+"\n\nDOCUMENT TEXT / FORM VALUES:\n\n"+text[:120000]}]

    response=client.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=[{"role":"user","content":content}],
        inferenceConfig={"temperature":0,"maxTokens":1800},
    )

    output=response["output"]["message"]["content"][0]["text"]
    return _normalize(json.loads(_clean_json_text(output)))


def _converse_with_images(images):
    client=boto3.client("bedrock-runtime",region_name=AWS_REGION)
    content=[{"text":PROMPT+"\n\nThe uploaded transport PDF is image-based. Read the rendered pages below."}]

    for image_bytes in images:
        content.append({
            "image":{
                "format":"jpeg",
                "source":{"bytes":image_bytes},
            }
        })

    response=client.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=[{"role":"user","content":content}],
        inferenceConfig={"temperature":0,"maxTokens":1800},
    )

    output=response["output"]["message"]["content"][0]["text"]
    return _normalize(json.loads(_clean_json_text(output)))


def extract_case(pdf_path):
    pdf_path=Path(pdf_path)

    text=_extract_text_and_fields(pdf_path)

    # Native/text PDFs keep the faster text path. Browser-rasterized transport
    # PDFs usually have little or no extractable text, so fall back to rendered
    # pages and Claude vision.
    meaningful_chars=sum(ch.isalnum() for ch in text)

    if meaningful_chars>=120:
        return _converse_with_text(text)

    images=_render_pages_as_jpeg(pdf_path)

    if not images:
        raise RuntimeError("R'Solv could not read text or render pages from this PDF.")

    return _converse_with_images(images)
