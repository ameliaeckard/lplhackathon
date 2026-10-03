import json
import os
import re
import shutil
import tempfile
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
DEFAULT_AWS_REGION = "us-east-1"

os.environ.setdefault("AWS_REGION", DEFAULT_AWS_REGION)
os.environ.setdefault("AWS_DEFAULT_REGION", DEFAULT_AWS_REGION)
os.environ.setdefault("BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID)

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

try:
    from .process_case import process_case
except ImportError:
    from process_case import process_case


app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MODEL_PATH = PROJECT_ROOT / "ml" / "models" / "resolve_model.joblib"

LIVE_CASES_DIR = PROJECT_ROOT / "data" / "live_cases"
HISTORY_DIR = LIVE_CASES_DIR / "history"

TRANSPORT_DIR = LIVE_CASES_DIR / "transport_pdfs"
TRANSPORT_HISTORY_DIR = LIVE_CASES_DIR / "transport_history"

for folder in [
    LIVE_CASES_DIR,
    HISTORY_DIR,
    TRANSPORT_DIR,
    TRANSPORT_HISTORY_DIR,
]:
    folder.mkdir(parents=True, exist_ok=True)


COMPRESSION_TARGET_MB = 0.35
MAX_UPLOAD_MB = 100
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


VALID_REVIEW_STATUSES = {
    "not_required",
    "awaiting_review",
    "follow_up_required",
    "ready_to_continue",
}


# ---------------------------------------------------------
# Logging
# ---------------------------------------------------------

def log(request_id, message, **fields):
    detail = " ".join(
        f"{key}={value}"
        for key, value in fields.items()
        if value is not None
    )

    print(
        f"[R'Solv][{request_id}] {message}"
        + (f" | {detail}" if detail else ""),
        flush=True,
    )


def error_response(code, message, status_code, request_id=None):
    return jsonify({
        "success": False,
        "request_id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }), status_code


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def looks_like_pdf(path):
    try:
        with open(path, "rb") as file:
            return file.read(5) == b"%PDF-"
    except OSError:
        return False


def bytes_to_mb(value):
    try:
        return round(int(value) / (1024 * 1024), 2)
    except (TypeError, ValueError):
        return None


def file_mb(path):
    return round(path.stat().st_size / (1024 * 1024), 2)


def safe_case_id(case_id):
    cleaned = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        str(case_id),
    ).strip("._")

    return cleaned or "case"


def case_file(case_id):
    return LIVE_CASES_DIR / f"{safe_case_id(case_id)}.json"


def transport_file(case_id):
    return TRANSPORT_DIR / f"{safe_case_id(case_id)}_transport.pdf"


def case_history_dir(case_id):
    path = HISTORY_DIR / safe_case_id(case_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def transport_history_dir(case_id):
    path = TRANSPORT_HISTORY_DIR / safe_case_id(case_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_run_id():
    now = datetime.now(timezone.utc)

    return (
        now.strftime("%Y%m%dT%H%M%S_%fZ")
        + "_"
        + uuid.uuid4().hex[:6]
    )


# ---------------------------------------------------------
# Atomic JSON persistence
# ---------------------------------------------------------

def atomic_json_write(path, value):
    """
    Write JSON safely.

    We write to a temporary sibling file first and then use
    os.replace(), so a partial write cannot destroy the case.
    """

    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(
        path.suffix + f".{uuid.uuid4().hex}.tmp"
    )

    try:
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(
                value,
                file,
                indent=2,
                ensure_ascii=False,
            )

            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary, path)

    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def save_current_case(case):
    path = case_file(case["case_id"])
    atomic_json_write(path, case)
    return path


def archive_analysis(case):
    run_id = case["analysis_run_id"]

    history_path = (
        case_history_dir(case["case_id"])
        / f"{run_id}.json"
    )

    atomic_json_write(history_path, case)

    return history_path


def archive_transport(case_id, run_id, source_path):
    history_path = (
        transport_history_dir(case_id)
        / f"{run_id}.pdf"
    )

    shutil.copy2(source_path, history_path)

    return history_path


# ---------------------------------------------------------
# Existing-case compatibility
# ---------------------------------------------------------

def normalize_saved_case(case):
    if not isinstance(case.get("review_history"), list):
        case["review_history"] = []

    if "review_status" not in case:
        if case.get("reviewed"):
            case["review_status"] = "ready_to_continue"

        elif case.get("human_review"):
            case["review_status"] = "awaiting_review"

        else:
            case["review_status"] = "not_required"

    case.setdefault("review_note", None)

    case.setdefault(
        "reviewed",
        case["review_status"]
        in {
            "follow_up_required",
            "ready_to_continue",
        },
    )

    return case


def load_cases():
    items = []

    LIVE_CASES_DIR.mkdir(parents=True, exist_ok=True)

    for path in LIVE_CASES_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as file:
                value = json.load(file)

            if isinstance(value, dict):
                items.append(normalize_saved_case(value))

        except Exception as error:
            print(
                f"[R'Solv] Could not load saved case {path}: {error}",
                flush=True,
            )

    return sorted(
        items,
        key=lambda item: item.get(
            "analyzed_at",
            "",
        ),
        reverse=True,
    )


def find_case(case_id):
    path = case_file(case_id)

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as file:
                return normalize_saved_case(json.load(file))
        except Exception:
            pass

    # Backward-compatible fallback.
    for case in load_cases():
        if str(case.get("case_id")) == str(case_id):
            return case

    return None


# ---------------------------------------------------------
# Request logging
# ---------------------------------------------------------

@app.before_request
def log_request():
    if request.path != "/health":
        rid = (
            request.headers.get("X-Request-ID")
            or uuid.uuid4().hex[:8]
        )

        request.environ["rsolv.request_id"] = rid

        log(
            rid,
            "HTTP request",
            method=request.method,
            path=request.path,
        )


@app.after_request
def log_response(response):
    rid = request.environ.get("rsolv.request_id")

    if rid:
        response.headers["X-Request-ID"] = rid

        log(
            rid,
            "HTTP response",
            status=response.status_code,
            path=request.path,
        )

    return response


# ---------------------------------------------------------
# Root / health
# ---------------------------------------------------------

@app.get("/")
def root():
    return jsonify({
        "service": "R'Solv API",
        "technology": (
            "C.A.R.D. — "
            "Case. Automatic. Review. Dashboard."
        ),
        "status": "running",
        "health": "/health",
        "analyze": "/analyze",
    })


@app.get("/health")
def health():
    bedrock_model = os.getenv(
        "BEDROCK_MODEL_ID",
        DEFAULT_BEDROCK_MODEL_ID,
    )

    model_exists = MODEL_PATH.exists()

    ready = bool(
        bedrock_model
        and model_exists
    )

    saved_cases = load_cases()

    return jsonify({
        "service": "R'Solv API",
        "technology": "C.A.R.D.",
        "status": (
            "ready"
            if ready
            else "not_ready"
        ),
        "bedrock_configured": bool(bedrock_model),
        "bedrock_model": bedrock_model,
        "aws_region": os.getenv(
            "AWS_REGION",
            DEFAULT_AWS_REGION,
        ),
        "ml_model_available": model_exists,
        "live_cases": len(saved_cases),
        "max_upload_mb": MAX_UPLOAD_MB,
        "compression_target_mb": COMPRESSION_TARGET_MB,
        "browser_compression": True,
        "persistent_case_directory": str(
            LIVE_CASES_DIR
        ),
    })


# ---------------------------------------------------------
# Case list
# ---------------------------------------------------------

@app.get("/cases")
def cases_index():
    cases = load_cases()

    return jsonify({
        "success": True,
        "count": len(cases),
        "cases": cases,
    })


# ---------------------------------------------------------
# Case analysis history
# ---------------------------------------------------------

@app.get("/cases/<path:case_id>/history")
def case_history(case_id):
    folder = case_history_dir(case_id)

    entries = []

    for path in sorted(
        folder.glob("*.json"),
        reverse=True,
    ):
        try:
            with open(
                path,
                "r",
                encoding="utf-8",
            ) as file:
                entries.append(json.load(file))

        except Exception as error:
            print(
                f"[R'Solv] Could not load history {path}: {error}",
                flush=True,
            )

    return jsonify({
        "success": True,
        "case_id": case_id,
        "count": len(entries),
        "history": entries,
    })


# ---------------------------------------------------------
# Transport PDF
# ---------------------------------------------------------

@app.get("/cases/<path:case_id>/transport")
def download_transport(case_id):
    path = transport_file(case_id)

    if not path.exists():
        return error_response(
            "TRANSPORT_COPY_NOT_FOUND",
            "No uploaded transport PDF is available for this case.",
            404,
        )

    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=(
            f"{safe_case_id(case_id)}"
            "_transport.pdf"
        ),
    )


# ---------------------------------------------------------
# Analyze
# ---------------------------------------------------------

@app.post("/analyze")
def analyze():
    request_id = (
        request.environ.get("rsolv.request_id")
        or uuid.uuid4().hex[:8]
    )

    total_started = time.perf_counter()

    if "file" not in request.files:
        return error_response(
            "MISSING_FILE",
            "No PDF was uploaded.",
            400,
            request_id,
        )

    uploaded_file = request.files["file"]

    if not uploaded_file.filename:
        return error_response(
            "EMPTY_FILENAME",
            "The uploaded file has no filename.",
            400,
            request_id,
        )

    original_name = (
        request.form.get("original_filename")
        or uploaded_file.filename
    )

    compression_mode = request.form.get(
        "compression_mode",
        "original",
    )

    original_size_bytes = request.form.get(
        "original_size_bytes"
    )

    original_mb = bytes_to_mb(
        original_size_bytes
    )

    if (
        Path(uploaded_file.filename)
        .suffix
        .lower()
        != ".pdf"
    ):
        return error_response(
            "INVALID_FILE_TYPE",
            "R'Solv currently accepts PDF files only.",
            400,
            request_id,
        )

    temporary_path = None

    try:
        # ---------------------------------------------
        # Receive uploaded transport PDF
        # ---------------------------------------------

        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".pdf",
            prefix="rsolv_",
            delete=False,
        ) as temporary_file:

            temporary_path = Path(
                temporary_file.name
            )

            uploaded_file.save(
                temporary_file
            )

        transport_mb = file_mb(
            temporary_path
        )

        log(
            request_id,
            "Transport PDF received",
            original_filename=original_name,
            original_mb=original_mb,
            transport_mb=transport_mb,
            compression_mode=compression_mode,
        )

        if temporary_path.stat().st_size == 0:
            return error_response(
                "EMPTY_FILE",
                "The uploaded PDF is empty.",
                400,
                request_id,
            )

        if not looks_like_pdf(
            temporary_path
        ):
            return error_response(
                "INVALID_PDF",
                "The uploaded file does not appear to be a valid PDF.",
                400,
                request_id,
            )

        # ---------------------------------------------
        # Run C.A.R.D.
        # ---------------------------------------------

        log(
            request_id,
            "C.A.R.D. live analysis started",
        )

        result = process_case(
            temporary_path,
            source_name=original_name,
            request_id=request_id,
        )

        case_id = result["case_id"]
        run_id = make_run_id()

        # ---------------------------------------------
        # Preserve review history from earlier runs
        # ---------------------------------------------

        previous = find_case(case_id)

        previous_review_history = []

        if previous:
            previous_review_history = (
                previous.get(
                    "review_history",
                    [],
                )
                or []
            )

        # ---------------------------------------------
        # Save current transport PDF
        # ---------------------------------------------

        current_transport = transport_file(
            case_id
        )

        shutil.copy2(
            temporary_path,
            current_transport,
        )

        # ---------------------------------------------
        # Archive this exact transport PDF too
        # ---------------------------------------------

        archived_transport = archive_transport(
            case_id,
            run_id,
            temporary_path,
        )

        # ---------------------------------------------
        # Build saved case
        # ---------------------------------------------

        result["analysis_run_id"] = run_id
        result["filename"] = original_name

        result["upload"] = {
            "original_mb": (
                original_mb
                if original_mb is not None
                else transport_mb
            ),
            "transport_mb": transport_mb,
            "compression_mode": compression_mode,
            "target_mb": COMPRESSION_TARGET_MB,
            "download_url": (
                f"/cases/{case_id}/transport"
            ),
            "archived_transport": str(
                archived_transport.relative_to(
                    PROJECT_ROOT
                )
            ),
        }

        result["analyzed_at"] = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        result["request_id"] = request_id

        # Preserve old human-review events.
        result["review_history"] = (
            previous_review_history
        )

        result["review_note"] = None
        result["reviewed"] = False
        result["reviewed_at"] = None

        # A new analysis creates a new review state.
        if result.get("human_review"):
            result["review_status"] = (
                "awaiting_review"
            )
        else:
            result["review_status"] = (
                "not_required"
            )

        # ---------------------------------------------
        # Save CURRENT case atomically
        # ---------------------------------------------

        current_case_path = save_current_case(
            result
        )

        # ---------------------------------------------
        # Archive this analysis forever
        # ---------------------------------------------

        history_path = archive_analysis(
            result
        )

        log(
            request_id,
            "Case persisted",
            case_id=case_id,
            current_file=current_case_path,
            history_file=history_path,
            run_id=run_id,
        )

        log(
            request_id,
            "Case saved to live history",
            case_id=case_id,
            review_status=result["review_status"],
            total_seconds=(
                f"{time.perf_counter()-total_started:.2f}"
            ),
        )

        return jsonify({
            "success": True,
            "request_id": request_id,
            "case": result,
        })

    except FileNotFoundError as error:
        log(
            request_id,
            "Dependency not found",
            error=repr(error),
        )

        return error_response(
            "DEPENDENCY_NOT_FOUND",
            str(error),
            500,
            request_id,
        )

    except Exception as error:
        log(
            request_id,
            "PROCESSING FAILED",
            error=repr(error),
        )

        traceback.print_exc()

        return error_response(
            "PROCESSING_FAILED",
            str(error),
            500,
            request_id,
        )

    finally:
        if (
            temporary_path
            and temporary_path.exists()
        ):
            try:
                temporary_path.unlink()

                log(
                    request_id,
                    "Temporary transport PDF deleted",
                )

            except OSError as error:
                log(
                    request_id,
                    "Could not delete temporary transport PDF",
                    error=repr(error),
                )


# ---------------------------------------------------------
# Human review
# ---------------------------------------------------------

@app.post("/cases/<path:case_id>/review")
def review_case(case_id):
    rid = (
        request.environ.get("rsolv.request_id")
        or "review"
    )

    case = find_case(case_id)

    if case is None:
        return error_response(
            "CASE_NOT_FOUND",
            f"Case not found: {case_id}",
            404,
            rid,
        )

    payload = (
        request.get_json(silent=True)
        or {}
    )

    review_status = str(
        payload.get("review_status")
        or ""
    ).strip()

    note = str(
        payload.get("note")
        or ""
    ).strip()[:600]

    if (
        review_status
        not in VALID_REVIEW_STATUSES
    ):
        return error_response(
            "INVALID_REVIEW_STATUS",
            (
                "review_status must be one of: "
                "not_required, awaiting_review, "
                "follow_up_required, ready_to_continue."
            ),
            400,
            rid,
        )

    # ---------------------------------------------
    # IMPORTANT:
    # Active deterministic exception cannot be
    # marked Ready to Continue.
    # ---------------------------------------------

    if (
        review_status
        == "ready_to_continue"
        and case.get("status")
        == "Needs Attention"
    ):
        return error_response(
            "ACTIVE_EXCEPTION",
            (
                "This case still has an active "
                "deterministic exception. Resolve "
                "the finding and re-analyze the case "
                "before marking it Ready to Continue."
            ),
            409,
            rid,
        )

    timestamp = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    if review_status == "awaiting_review":
        case["human_review"] = True
        case["reviewed"] = False
        case["reviewed_at"] = None

    elif review_status == "not_required":
        case["reviewed"] = False
        case["reviewed_at"] = None

    else:
        case["reviewed"] = True
        case["reviewed_at"] = timestamp

    case["review_status"] = (
        review_status
    )

    case["review_note"] = (
        note or None
    )

    review_event = {
        "timestamp": timestamp,
        "review_status": review_status,
        "note": note or None,
        "analysis_run_id": case.get(
            "analysis_run_id"
        ),
    }

    case.setdefault(
        "review_history",
        [],
    ).append(
        review_event
    )

    # Save current case.
    save_current_case(
        case
    )

    # Also update this run's archived JSON.
    run_id = case.get(
        "analysis_run_id"
    )

    if run_id:
        history_path = (
            case_history_dir(case_id)
            / f"{run_id}.json"
        )

        atomic_json_write(
            history_path,
            case,
        )

    log(
        rid,
        "Human review recorded",
        case_id=case_id,
        review_status=review_status,
        note_present=bool(note),
    )

    return jsonify({
        "success": True,
        "case": case,
    })


# ---------------------------------------------------------
# Clear history
# ---------------------------------------------------------

@app.post("/cases/clear")
def clear_cases():
    rid = (
        request.environ.get("rsolv.request_id")
        or "clear"
    )

    removed = 0

    # Current case JSON.
    for path in LIVE_CASES_DIR.glob(
        "*.json"
    ):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass

    # Current transports.
    if TRANSPORT_DIR.exists():
        for path in TRANSPORT_DIR.glob(
            "*.pdf"
        ):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass

    # Analysis histories.
    for directory in [
        HISTORY_DIR,
        TRANSPORT_HISTORY_DIR,
    ]:
        if directory.exists():
            for child in directory.iterdir():
                try:
                    if child.is_dir():
                        shutil.rmtree(
                            child
                        )
                    else:
                        child.unlink()

                    removed += 1

                except OSError:
                    pass

    log(
        rid,
        "Live case history cleared",
        removed=removed,
    )

    return jsonify({
        "success": True,
        "removed": removed,
    })


# ---------------------------------------------------------
# 413
# ---------------------------------------------------------

@app.errorhandler(413)
def file_too_large(error):
    rid = (
        request.environ.get("rsolv.request_id")
        or "upload"
    )

    log(
        rid,
        "Upload rejected: file too large",
        max_upload_mb=MAX_UPLOAD_MB,
    )

    return error_response(
        "FILE_TOO_LARGE",
        (
            "The prepared PDF is larger than "
            f"{MAX_UPLOAD_MB} MB."
        ),
        413,
        rid,
    )


# ---------------------------------------------------------
# Start
# ---------------------------------------------------------

if __name__ == "__main__":
    port = int(
        os.getenv(
            "PORT",
            "8000",
        )
    )

    debug = (
        os.getenv(
            "FLASK_DEBUG",
            "0",
        )
        == "1"
    )

    print(
        "\nR'Solv API\n===========",
        flush=True,
    )

    print(
        "Technology: C.A.R.D. — "
        "Case. Automatic. Review. Dashboard.",
        flush=True,
    )

    print(
        f"Listening on: http://localhost:{port}",
        flush=True,
    )

    print(
        f"Persistent cases: {LIVE_CASES_DIR}",
        flush=True,
    )

    print(
        f"Analysis history: {HISTORY_DIR}",
        flush=True,
    )

    print(
        f"Bedrock model: "
        f"{os.getenv('BEDROCK_MODEL_ID', DEFAULT_BEDROCK_MODEL_ID)}",
        flush=True,
    )

    print(
        f"Browser transport target: "
        f"~{COMPRESSION_TARGET_MB} MB\n",
        flush=True,
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug,
    )
