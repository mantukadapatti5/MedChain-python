"""Chronological split, shared by RF/XGBoost/LSTM so all three are compared
on identical train/validation/test periods. Never a random shuffle."""
import pandas as pd

VAL_START = pd.Timestamp("2023-11-01")
TEST_START = pd.Timestamp("2024-02-01")


def chronological_split(df: pd.DataFrame):
    train = df[df["Date"] < VAL_START]
    val = df[(df["Date"] >= VAL_START) & (df["Date"] < TEST_START)]
    test = df[df["Date"] >= TEST_START]
    print(f"[demand.split] train={len(train)} ({train.Date.min().date()}..{train.Date.max().date()}) | "
          f"val={len(val)} ({val.Date.min().date()}..{val.Date.max().date()}) | "
          f"test={len(test)} ({test.Date.min().date()}..{test.Date.max().date()})")
    return train, val, test
