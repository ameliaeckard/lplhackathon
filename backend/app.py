import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

try:
    from .process_case import process_case
except ImportError:
    from process_case import process_case

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / "ml" / "models" / "resolve_model.joblib"
LIVE_CASES_DIR = PROJECT_ROOT / "data" / "live_cases"
LIVE_CASES_DIR.mkdir(parents=True, exist_ok=True)


def error_response(code, message, status_code):
    return jsonify({"success": False, "error": {"code": code, "message": message}}), status_code


def looks_like_pdf(path):
    try:
        with open(path, "rb") as file:
            return file.read(5) == b"%PDF-"
    except OSError:
        return False


def case_file(case_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(case_id)).strip("._") or "case"
    return LIVE_CASES_DIR / f"{safe}.json"


def save_case(case):
    with open(case_file(case["case_id"]), "w", encoding="utf-8") as file:
        json.dump(case, file, indent=2)


def load_cases():
    items = []
    for path in LIVE_CASES_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as file:
                value = json.load(file)
            if isinstance(value, dict):
                items.append(value)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(items, key=lambda x: x.get("analyzed_at", ""), reverse=True)


def find_case(case_id):
    for case in load_cases():
        if str(case.get("case_id")) == str(case_id):
            return case
    return None


@app.get("/health")
def health():
    bedrock_model = os.getenv("BEDROCK_MODEL_ID")
    model_exists = MODEL_PATH.exists()
    ready = bool(bedrock_model and model_exists)
    return jsonify({
        "service": "Resolve API",
        "status": "ready" if ready else "not_ready",
        "bedrock_configured": bool(bedrock_model),
        "ml_model_available": model_exists,
        "live_cases": len(load_cases()),
    })


@app.get("/cases")
def cases_index():
    return jsonify({"success": True, "cases": load_cases()})


@app.post("/analyze")
def analyze():
    if "file" not in request.files:
        return error_response("MISSING_FILE", "No PDF was uploaded.", 400)

    uploaded_file = request.files["file"]
    if not uploaded_file.filename:
        return error_response("EMPTY_FILENAME", "The uploaded file has no filename.", 400)

    original_name = uploaded_file.filename
    if Path(original_name).suffix.lower() != ".pdf":
        return error_response("INVALID_FILE_TYPE", "Resolve currently accepts PDF files only.", 400)

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".pdf", prefix="resolve_", delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            uploaded_file.save(temporary_file)

        if temporary_path.stat().st_size == 0:
            return error_response("EMPTY_FILE", "The uploaded PDF is empty.", 400)
        if not looks_like_pdf(temporary_path):
            return error_response("INVALID_PDF", "The uploaded file does not appear to be a valid PDF.", 400)

        result = process_case(temporary_path, source_name=original_name)
        result["filename"] = original_name
        result["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        result["reviewed"] = False
        result["reviewed_at"] = None
        save_case(result)

        return jsonify({"success": True, "case": result})

    except FileNotFoundError as error:
        return error_response("DEPENDENCY_NOT_FOUND", str(error), 500)
    except Exception as error:
        print("Resolve processing error:", repr(error))
        return error_response("PROCESSING_FAILED", str(error), 500)
    finally:
        if temporary_path and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                print(f"Warning: could not delete temporary file {temporary_path}")


@app.post("/cases/<path:case_id>/review")
def review_case(case_id):
    case = find_case(case_id)
    if case is None:
        return error_response("CASE_NOT_FOUND", f"Case not found: {case_id}", 404)

    payload = request.get_json(silent=True) or {}
    reviewed = bool(payload.get("reviewed", True))
    case["reviewed"] = reviewed
    case["reviewed_at"] = datetime.now(timezone.utc).isoformat() if reviewed else None
    save_case(case)
    return jsonify({"success": True, "case": case})


@app.post("/cases/clear")
def clear_cases():
    removed = 0
    for path in LIVE_CASES_DIR.glob("*.json"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return jsonify({"success": True, "removed": removed})


@app.errorhandler(413)
def file_too_large(error):
    return error_response("FILE_TOO_LARGE", "The uploaded PDF is larger than 15 MB.", 413)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    print("\nResolve API\n===========")
    print(f"Listening on: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
