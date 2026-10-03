import json
import os
import time
from pathlib import Path

from document_extractor import extract_case


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DOCUMENTS_DIR = (
    PROJECT_ROOT
    / "data"
    / "documents"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "cases"
    / "extracted"
)


FORCE_REEXTRACT = (
    os.getenv(
        "FORCE_REEXTRACT",
        "0"
    )
    == "1"
)


def get_pdf_files():
    return sorted(
        DOCUMENTS_DIR.glob(
            "beneficiary_case_*.pdf"
        )
    )


def save_result(
    pdf_path,
    result
):
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    output_path = (
        OUTPUT_DIR
        / f"{pdf_path.stem}.json"
    )

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            indent=2
        )

    return output_path


def main():

    pdf_files = get_pdf_files()

    if not pdf_files:
        print(
            "No beneficiary PDFs found."
        )
        return

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print()
    print(
        "Resolve Beneficiary Extraction"
    )
    print(
        "=============================="
    )

    print(
        f"PDFs found: {len(pdf_files)}"
    )

    successes = 0
    skipped = 0
    failures = 0

    for index, pdf_path in enumerate(
        pdf_files,
        start=1
    ):

        output_path = (
            OUTPUT_DIR
            / f"{pdf_path.stem}.json"
        )

        print()
        print(
            f"[{index}/{len(pdf_files)}] "
            f"{pdf_path.name}"
        )

        if (
            output_path.exists()
            and not FORCE_REEXTRACT
        ):
            print(
                "  Already extracted. Skipping."
            )

            skipped += 1
            continue

        try:

            result = extract_case(
                pdf_path
            )

            save_result(
                pdf_path,
                result
            )

            print(
                "  Case:",
                result.get("case_id")
            )

            print(
                "  Beneficiary type:",
                result.get(
                    "beneficiary_type"
                )
            )

            print(
                "  Saved:",
                output_path
            )

            successes += 1

        except Exception as error:

            failures += 1

            print(
                "  ERROR:",
                error
            )

        time.sleep(
            1.2
        )

    print()
    print(
        "=============================="
    )

    print(
        f"Newly extracted: {successes}"
    )

    print(
        f"Already extracted: {skipped}"
    )

    print(
        f"Failed: {failures}"
    )


if __name__ == "__main__":
    main()