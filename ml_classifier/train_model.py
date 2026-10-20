"""Train the TF-IDF + LogisticRegression classifier.  Usage: python -m ml_classifier.train_model"""
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

HERE = Path(__file__).parent


def build_pipeline():
    return Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, lowercase=True, min_df=1)),
        ("clf", LogisticRegression(max_iter=2000, C=8.0)),
    ])


def train(dataset=HERE / "dataset.csv", output=HERE / "model.pkl"):
    df = pd.read_csv(dataset).dropna()
    x_train, x_test, y_train, y_test = train_test_split(
        df["description"], df["category"], test_size=0.2, random_state=42, stratify=df["category"])
    model = build_pipeline().fit(x_train, y_train)
    pred = model.predict(x_test)
    acc = accuracy_score(y_test, pred)
    print(classification_report(y_test, pred, zero_division=0))
    final = build_pipeline().fit(df["description"], df["category"])  # refit on all data for deployment
    joblib.dump({"model": final, "holdout_accuracy": acc, "rows": len(df)}, output)
    print(f"Holdout accuracy: {acc:.3f}. Saved {output}")
    return acc


if __name__ == "__main__":
    train()
