from pathlib import Path

import pandas as pd

from sklearn.model_selection import train_test_split


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

SOURCE_FILE = (
    DATASET_DIR
    / "case_history.csv"
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


RANDOM_STATE = 42

TARGET = "needs_attention"


def main():

    dataframe = pd.read_csv(
        SOURCE_FILE
    )

    if len(dataframe) < 20:

        raise ValueError(
            "Semi-supervised training needs "
            "at least 20 usable cases."
        )

    if dataframe[
        TARGET
    ].nunique() < 2:

        raise ValueError(
            "Dataset needs examples from "
            "both target classes."
        )

    # ==================================
    # 1. FINAL TEST SET
    #
    # 20% of all usable cases.
    #
    # This set must remain untouched
    # until the final model is selected.
    # ==================================

    development, test = (
        train_test_split(
            dataframe,
            test_size=0.20,
            random_state=RANDOM_STATE,
            stratify=dataframe[
                TARGET
            ]
        )
    )

    # ==================================
    # 2. LABELED VS UNLABELED
    #
    # Development = 80% of dataset.
    #
    # 37.5% of 80% = 30% total labeled
    # 62.5% of 80% = 50% total unlabeled
    # ==================================

    labeled_seed, unlabeled_with_labels = (
        train_test_split(
            development,
            train_size=0.375,
            random_state=RANDOM_STATE,
            stratify=development[
                TARGET
            ]
        )
    )

    # ==================================
    # 3. TRAIN VS VALIDATION
    #
    # Validation is taken only from the
    # labeled seed.
    #
    # Model selection happens here,
    # NOT on the final test set.
    # ==================================

    train, validation = (
        train_test_split(
            labeled_seed,
            test_size=0.20,
            random_state=RANDOM_STATE,
            stratify=labeled_seed[
                TARGET
            ]
        )
    )

    # ==================================
    # 4. HIDE LABELS
    #
    # The semi-supervised model must not
    # see the true labels of this pool.
    # ==================================

    unlabeled = (
        unlabeled_with_labels
        .drop(
            columns=[
                TARGET,
                "label_source"
            ],
            errors="ignore"
        )
        .copy()
    )

    # ==================================
    # SAVE
    # ==================================

    train.to_csv(
        TRAIN_FILE,
        index=False
    )

    validation.to_csv(
        VALIDATION_FILE,
        index=False
    )

    unlabeled.to_csv(
        UNLABELED_FILE,
        index=False
    )

    test.to_csv(
        TEST_FILE,
        index=False
    )

    print()
    print(
        "Resolve Semi-Supervised Split"
    )

    print(
        "============================="
    )

    print(
        f"Total usable cases: "
        f"{len(dataframe)}"
    )

    print(
        f"Labeled training: "
        f"{len(train)}"
    )

    print(
        f"Validation: "
        f"{len(validation)}"
    )

    print(
        f"Unlabeled pool: "
        f"{len(unlabeled)}"
    )

    print(
        f"Final held-out test: "
        f"{len(test)}"
    )

    print()
    print(
        "Training distribution:"
    )

    print(
        train[
            TARGET
        ].value_counts()
    )

    print()
    print(
        "Validation distribution:"
    )

    print(
        validation[
            TARGET
        ].value_counts()
    )

    print()
    print(
        "Final test distribution:"
    )

    print(
        test[
            TARGET
        ].value_counts()
    )

    print()
    print(
        "Files:"
    )

    print(
        f"  {TRAIN_FILE}"
    )

    print(
        f"  {VALIDATION_FILE}"
    )

    print(
        f"  {UNLABELED_FILE}"
    )

    print(
        f"  {TEST_FILE}"
    )


if __name__ == "__main__":
    main()