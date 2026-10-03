import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
)


STEPS = [
    (
        "1. Extract beneficiary PDFs with Claude",
        PROJECT_ROOT
        / "ai"
        / "run_extraction.py"
    ),

    (
        "2. Run deterministic beneficiary rules",
        PROJECT_ROOT
        / "rules"
        / "run_rules.py"
    ),

    (
        "3. Build full document-derived dataset",
        PROJECT_ROOT
        / "ml"
        / "build_dataset.py"
    ),

    (
        "4. Create semi-supervised split",
        PROJECT_ROOT
        / "ml"
        / "split_dataset.py"
    ),

    (
        "5. Train semi-supervised XGBoost",
        PROJECT_ROOT
        / "ml"
        / "train_semisupervised.py"
    )
]


def check_environment():

    model_id = os.getenv(
        "BEDROCK_MODEL_ID"
    )

    if not model_id:

        raise RuntimeError(
            "BEDROCK_MODEL_ID is not set."
        )

    documents_dir = (
        PROJECT_ROOT
        / "data"
        / "documents"
    )

    pdfs = list(
        documents_dir.glob(
            "beneficiary_case_*.pdf"
        )
    )

    if not pdfs:

        raise RuntimeError(
            "No beneficiary PDFs found."
        )

    print(
        f"Beneficiary PDFs found: "
        f"{len(pdfs)}"
    )

    print(
        f"Bedrock model: "
        f"{model_id}"
    )


def run_step(
    title,
    script
):

    print()
    print(
        "=" * 60
    )

    print(
        title
    )

    print(
        "=" * 60
    )

    subprocess.run(
        [
            sys.executable,
            str(script)
        ],
        cwd=PROJECT_ROOT,
        check=True
    )


def main():

    print()
    print(
        "=" * 60
    )

    print(
        "RESOLVE"
    )

    print(
        "Proactive Exception Intelligence"
    )

    print(
        "=" * 60
    )

    try:

        check_environment()

        for title, script in STEPS:

            run_step(
                title,
                script
            )

    except subprocess.CalledProcessError as error:

        print()
        print(
            "RESOLVE PIPELINE FAILED"
        )

        raise SystemExit(
            error.returncode
        )

    except Exception as error:

        print()
        print(
            "RESOLVE PIPELINE FAILED"
        )

        print(
            error
        )

        raise SystemExit(
            1
        )

    print()
    print(
        "=" * 60
    )

    print(
        "RESOLVE PIPELINE COMPLETE"
    )

    print(
        "=" * 60
    )

    print()
    print(
        "Final model:"
    )

    print(
        "ml/models/"
        "resolve_model.joblib"
    )

    print()
    print(
        "Evaluation:"
    )

    print(
        "ml/models/metrics.json"
    )


if __name__ == "__main__":
    main()