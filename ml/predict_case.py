import json
import sys
from pathlib import Path

import joblib
import pandas as pd

from model_features import (
    FEATURE_COLUMNS,
    build_feature_row
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

MODEL_PATH = (
    PROJECT_ROOT
    / "ml"
    / "models"
    / "resolve_model.joblib"
)


def predict_case(case):

    if not MODEL_PATH.exists():

        raise FileNotFoundError(
            "Resolve model not found. "
            "Run python3 main.py first."
        )

    model = joblib.load(
        MODEL_PATH
    )

    features = build_feature_row(
        case
    )

    dataframe = pd.DataFrame(
        [features],
        columns=FEATURE_COLUMNS
    )

    prediction = int(
        model.predict(
            dataframe
        )[0]
    )

    probability = float(
        model.predict_proba(
            dataframe
        )[0][1]
    )

    return {
        "prediction": (
            "needs_attention"
            if prediction == 1
            else "no_detected_exception"
        ),

        # Experimental model output.
        # Do not describe this as calibrated
        # probability of real-world failure.
        "model_score": round(
            probability,
            4
        )
    }


def main():

    if len(sys.argv) != 2:

        print(
            "Usage:"
        )

        print(
            "python3 ml/predict_case.py "
            "data/cases/extracted/"
            "beneficiary_case_001.json"
        )

        raise SystemExit(1)

    case_path = Path(
        sys.argv[1]
    )

    with open(
        case_path,
        "r",
        encoding="utf-8"
    ) as file:

        case = json.load(
            file
        )

    result = predict_case(
        case
    )

    print(
        json.dumps(
            result,
            indent=2
        )
    )


if __name__ == "__main__":
    main()