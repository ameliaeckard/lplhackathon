import json
import os
from pathlib import Path

import joblib
import pandas as pd

from sklearn.compose import ColumnTransformer

from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix
)

from sklearn.pipeline import Pipeline

from sklearn.preprocessing import (
    OneHotEncoder
)

from sklearn.utils.class_weight import (
    compute_sample_weight
)

from xgboost import XGBClassifier

from model_features import FEATURE_COLUMNS


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DATASET_DIR = (
    PROJECT_ROOT
    / "data"
    / "datasets"
)

TRAIN_FILE = (
    DATASET_DIR
    / "train.csv"
)

VALIDATION_FILE = (
    DATASET_DIR
    / "validation.csv"
)

UNLABELED_FILE = (
    DATASET_DIR
    / "unlabeled.csv"
)

TEST_FILE = (
    DATASET_DIR
    / "test.csv"
)

MODEL_DIR = (
    PROJECT_ROOT
    / "ml"
    / "models"
)

MODEL_FILE = (
    MODEL_DIR
    / "resolve_model.joblib"
)

METRICS_FILE = (
    MODEL_DIR
    / "metrics.json"
)

PSEUDO_LABEL_FILE = (
    DATASET_DIR
    / "pseudo_labels.csv"
)


TARGET = "needs_attention"


POSITIVE_THRESHOLD = float(
    os.getenv(
        "POSITIVE_PSEUDO_THRESHOLD",
        "0.75"
    )
)

NEGATIVE_THRESHOLD = float(
    os.getenv(
        "NEGATIVE_PSEUDO_THRESHOLD",
        "0.25"
    )
)

PSEUDO_WEIGHT = float(
    os.getenv(
        "PSEUDO_LABEL_WEIGHT",
        "0.35"
    )
)


CATEGORICAL_FEATURES = [
    "beneficiary_type",
    "estate_ein_status",
    "death_certificate_status",
    "letters_testamentary_status",
    "trust_document_status",
    "guardianship_document_status",
    "w8_ben_status",
    "signature_status"
]


NUMERIC_FEATURES = [
    "destination_account_present",
    "unknown_field_count"
]


def build_pipeline():

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "categorical",
                OneHotEncoder(
                    handle_unknown="ignore"
                ),
                CATEGORICAL_FEATURES
            ),
            (
                "numeric",
                "passthrough",
                NUMERIC_FEATURES
            )
        ]
    )

    classifier = XGBClassifier(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.05,
        min_child_weight=1,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=42,
        n_jobs=2
    )

    return Pipeline(
        steps=[
            (
                "preprocessor",
                preprocessor
            ),
            (
                "model",
                classifier
            )
        ]
    )


def evaluate(
    model,
    X,
    y
):

    predictions = model.predict(
        X
    )

    return {
        "accuracy": float(
            accuracy_score(
                y,
                predictions
            )
        ),

        "precision": float(
            precision_score(
                y,
                predictions,
                zero_division=0
            )
        ),

        "recall": float(
            recall_score(
                y,
                predictions,
                zero_division=0
            )
        ),

        "f1": float(
            f1_score(
                y,
                predictions,
                zero_division=0
            )
        ),

        "confusion_matrix": (
            confusion_matrix(
                y,
                predictions
            )
            .tolist()
        )
    }


def print_metrics(
    title,
    metrics
):

    print()
    print(title)
    print(
        "-" * len(title)
    )

    print(
        json.dumps(
            metrics,
            indent=2
        )
    )


def train_balanced(
    X,
    y
):
    """
    Train a supervised XGBoost model
    while compensating for class imbalance.
    """

    model = build_pipeline()

    weights = compute_sample_weight(
        class_weight="balanced",
        y=y
    )

    model.fit(
        X,
        y,
        model__sample_weight=weights
    )

    return model


def build_balanced_pseudo_labels(
    unlabeled,
    probabilities
):
    """
    Accept only confident pseudo-labels.

    Keep equal numbers of positive and
    negative pseudo-labels so one class
    cannot dominate.
    """

    candidates = (
        unlabeled.copy()
    )

    candidates[
        "pseudo_probability"
    ] = probabilities

    positive = candidates[
        candidates[
            "pseudo_probability"
        ] >= POSITIVE_THRESHOLD
    ].copy()

    negative = candidates[
        candidates[
            "pseudo_probability"
        ] <= NEGATIVE_THRESHOLD
    ].copy()

    positive = positive.sort_values(
        "pseudo_probability",
        ascending=False
    )

    negative = negative.sort_values(
        "pseudo_probability",
        ascending=True
    )

    print()
    print(
        "Pseudo-label candidates"
    )

    print(
        "-----------------------"
    )

    print(
        f"Confident positive: "
        f"{len(positive)}"
    )

    print(
        f"Confident negative: "
        f"{len(negative)}"
    )

    if (
        len(positive) == 0
        or len(negative) == 0
    ):

        return pd.DataFrame()

    count = min(
        len(positive),
        len(negative)
    )

    positive = positive.head(
        count
    )

    negative = negative.head(
        count
    )

    positive[
        TARGET
    ] = 1

    negative[
        TARGET
    ] = 0

    pseudo = pd.concat(
        [
            positive,
            negative
        ],
        ignore_index=True
    )

    return pseudo


def train_with_pseudo_labels(
    gold,
    pseudo
):
    """
    Gold labels receive full weight.

    Pseudo-labels receive reduced weight.
    """

    gold_training = gold[
        FEATURE_COLUMNS
        + [TARGET]
    ].copy()

    pseudo_training = pseudo[
        FEATURE_COLUMNS
        + [TARGET]
    ].copy()

    combined = pd.concat(
        [
            gold_training,
            pseudo_training
        ],
        ignore_index=True
    )

    X = combined[
        FEATURE_COLUMNS
    ]

    y = combined[
        TARGET
    ]

    class_weights = (
        compute_sample_weight(
            class_weight="balanced",
            y=y
        )
    )

    source_weights = (
        [1.0] * len(
            gold_training
        )
        +
        [PSEUDO_WEIGHT] * len(
            pseudo_training
        )
    )

    final_weights = [
        class_weight
        * source_weight

        for (
            class_weight,
            source_weight
        )

        in zip(
            class_weights,
            source_weights
        )
    ]

    model = build_pipeline()

    model.fit(
        X,
        y,
        model__sample_weight=final_weights
    )

    return model


def choose_model(
    baseline_metrics,
    semi_metrics
):
    """
    Select using VALIDATION performance.

    F1 is primary.
    Recall breaks ties.
    Precision breaks a second tie.
    """

    if semi_metrics is None:

        return (
            "supervised_baseline"
        )

    baseline_score = (
        baseline_metrics[
            "f1"
        ],
        baseline_metrics[
            "recall"
        ],
        baseline_metrics[
            "precision"
        ]
    )

    semi_score = (
        semi_metrics[
            "f1"
        ],
        semi_metrics[
            "recall"
        ],
        semi_metrics[
            "precision"
        ]
    )

    if semi_score > baseline_score:

        return "semi_supervised"

    return "supervised_baseline"


def main():

    train = pd.read_csv(
        TRAIN_FILE
    )

    validation = pd.read_csv(
        VALIDATION_FILE
    )

    unlabeled = pd.read_csv(
        UNLABELED_FILE
    )

    test = pd.read_csv(
        TEST_FILE
    )

    print()
    print(
        "Resolve ML Training"
    )

    print(
        "==================="
    )

    print(
        f"Training cases: "
        f"{len(train)}"
    )

    print(
        f"Validation cases: "
        f"{len(validation)}"
    )

    print(
        f"Unlabeled cases: "
        f"{len(unlabeled)}"
    )

    print(
        f"Final test cases: "
        f"{len(test)}"
    )

    print()

    print(
        "Training class distribution:"
    )

    print(
        train[
            TARGET
        ].value_counts()
    )

    # ==================================
    # DATA
    # ==================================

    X_train = train[
        FEATURE_COLUMNS
    ]

    y_train = train[
        TARGET
    ]

    X_validation = validation[
        FEATURE_COLUMNS
    ]

    y_validation = validation[
        TARGET
    ]

    X_unlabeled = unlabeled[
        FEATURE_COLUMNS
    ]

    X_test = test[
        FEATURE_COLUMNS
    ]

    y_test = test[
        TARGET
    ]

    # ==================================
    # 1. SUPERVISED BASELINE
    # ==================================

    baseline = train_balanced(
        X_train,
        y_train
    )

    baseline_validation = evaluate(
        baseline,
        X_validation,
        y_validation
    )

    print_metrics(
        "Baseline Validation",
        baseline_validation
    )

    # ==================================
    # 2. PSEUDO-LABEL UNLABELED POOL
    # ==================================

    probabilities = (
        baseline.predict_proba(
            X_unlabeled
        )[:, 1]
    )

    pseudo = (
        build_balanced_pseudo_labels(
            unlabeled,
            probabilities
        )
    )

    semi_validation = None

    if pseudo.empty:

        print()
        print(
            "No balanced pseudo-label set "
            "could be created."
        )

    else:

        print()

        print(
            f"Balanced pseudo-labels accepted: "
            f"{len(pseudo)}"
        )

        print(
            f"Positive pseudo-labels: "
            f"{int((pseudo[TARGET] == 1).sum())}"
        )

        print(
            f"Negative pseudo-labels: "
            f"{int((pseudo[TARGET] == 0).sum())}"
        )

        pseudo.to_csv(
            PSEUDO_LABEL_FILE,
            index=False
        )

        semi_model = (
            train_with_pseudo_labels(
                train,
                pseudo
            )
        )

        semi_validation = evaluate(
            semi_model,
            X_validation,
            y_validation
        )

        print_metrics(
            "Semi-Supervised Validation",
            semi_validation
        )

    # ==================================
    # 3. CHOOSE USING VALIDATION ONLY
    # ==================================

    selected_name = choose_model(
        baseline_validation,
        semi_validation
    )

    print()
    print(
        "Selected approach:"
    )

    print(
        selected_name
    )

    # ==================================
    # 4. FINAL TRAINING
    #
    # Validation labels may now join the
    # training data because model choice
    # is already complete.
    # ==================================

    full_gold = pd.concat(
        [
            train,
            validation
        ],
        ignore_index=True
    )

    if selected_name == (
        "semi_supervised"
    ):

        final_model = (
            train_with_pseudo_labels(
                full_gold,
                pseudo
            )
        )

    else:

        X_full_gold = full_gold[
            FEATURE_COLUMNS
        ]

        y_full_gold = full_gold[
            TARGET
        ]

        final_model = train_balanced(
            X_full_gold,
            y_full_gold
        )

    # ==================================
    # 5. FINAL TEST
    #
    # This is the FIRST time the test
    # labels influence an evaluation.
    # They never influenced model choice.
    # ==================================

    final_test_metrics = evaluate(
        final_model,
        X_test,
        y_test
    )

    print_metrics(
        "FINAL HELD-OUT TEST",
        final_test_metrics
    )

    # ==================================
    # 6. SAVE FINAL MODEL
    # ==================================

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    joblib.dump(
        final_model,
        MODEL_FILE
    )

    metrics = {
        "training_cases": int(
            len(train)
        ),

        "validation_cases": int(
            len(validation)
        ),

        "unlabeled_cases": int(
            len(unlabeled)
        ),

        "final_test_cases": int(
            len(test)
        ),

        "positive_pseudo_threshold": (
            POSITIVE_THRESHOLD
        ),

        "negative_pseudo_threshold": (
            NEGATIVE_THRESHOLD
        ),

        "pseudo_label_weight": (
            PSEUDO_WEIGHT
        ),

        "pseudo_labels_accepted": int(
            len(pseudo)
        ),

        "baseline_validation": (
            baseline_validation
        ),

        "semi_supervised_validation": (
            semi_validation
        ),

        "selected_model": (
            selected_name
        ),

        "final_test": (
            final_test_metrics
        ),

        "label_source": (
            "deterministic_rules_proxy"
        )
    }

    with open(
        METRICS_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            metrics,
            file,
            indent=2
        )

    print()
    print(
        "Final model saved:"
    )

    print(
        MODEL_FILE
    )

    print()
    print(
        "Metrics saved:"
    )

    print(
        METRICS_FILE
    )


if __name__ == "__main__":
    main()