import json
from pathlib import Path

import pandas as pd

from model_features import (
    build_feature_row
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

EXTRACTED_DIR = (
    PROJECT_ROOT
    / "data"
    / "cases"
    / "extracted"
)

EVALUATED_DIR = (
    PROJECT_ROOT
    / "data"
    / "cases"
    / "evaluated"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "datasets"
)

OUTPUT_FILE = (
    OUTPUT_DIR
    / "case_history.csv"
)


def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(
            file
        )


def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    extracted_files = sorted(
        EXTRACTED_DIR.glob(
            "beneficiary_case_*.json"
        )
    )

    rows = []

    skipped_unknown = 0

    for extracted_path in extracted_files:

        evaluated_path = (
            EVALUATED_DIR
            / extracted_path.name
        )

        if not evaluated_path.exists():

            print(
                f"Skipping {extracted_path.name}: "
                "no rule evaluation."
            )

            continue

        extracted = load_json(
            extracted_path
        )

        evaluated = load_json(
            evaluated_path
        )

        status = evaluated.get(
            "status"
        )

        if status == "needs_attention":
            label = 1

        elif status == "no_detected_exception":
            label = 0

        else:

            print(
                f"Skipping {extracted_path.name}: "
                f"{status}"
            )

            skipped_unknown += 1
            continue

        row = {
            "case_id": extracted.get(
                "case_id"
            )
        }

        row.update(
            build_feature_row(
                extracted
            )
        )

        row["needs_attention"] = label

        # Transparency:
        # this can later become historical_outcome
        row[
            "label_source"
        ] = "deterministic_rules_proxy"

        rows.append(
            row
        )

    dataframe = pd.DataFrame(
        rows
    )

    dataframe.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print()
    print(
        "Resolve Full Labeled Dataset"
    )

    print(
        "============================"
    )

    print(
        f"Usable labeled cases: "
        f"{len(dataframe)}"
    )

    print(
        f"Unable to determine / excluded: "
        f"{skipped_unknown}"
    )

    if not dataframe.empty:

        print(
            f"Needs attention: "
            f"{int(dataframe['needs_attention'].sum())}"
        )

        print(
            f"No detected exception: "
            f"{int((dataframe['needs_attention'] == 0).sum())}"
        )

    print(
        f"Saved: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()