import json
from pathlib import Path

from beneficiary_rules import (
    evaluate_beneficiary_case
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

INPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "cases"
    / "extracted"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "cases"
    / "evaluated"
)


def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    case_files = sorted(
        INPUT_DIR.glob(
            "beneficiary_case_*.json"
        )
    )

    if not case_files:
        print(
            "No extracted beneficiary cases found."
        )
        return

    print()
    print(
        "Resolve Rules Engine"
    )
    print(
        "===================="
    )

    for case_path in case_files:

        with open(
            case_path,
            "r",
            encoding="utf-8"
        ) as file:

            case = json.load(
                file
            )

        result = evaluate_beneficiary_case(
            case
        )

        output_path = (
            OUTPUT_DIR
            / case_path.name
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

        print()
        print(
            result["case_id"]
        )

        print(
            "  Status:",
            result["status"]
        )

        if result["findings"]:

            for finding in result["findings"]:

                print(
                    "  -",
                    finding["code"]
                )

        else:

            print(
                "  - No detected exception"
            )


if __name__ == "__main__":
    main()