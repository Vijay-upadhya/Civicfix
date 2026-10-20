"""Loads model.pkl lazily and returns an explainable prediction."""
from functools import lru_cache
from pathlib import Path

import joblib

from .rules import classify_by_rules

MODEL_PATH = Path(__file__).parent / "model.pkl"


@lru_cache(maxsize=1)
def _load():
    if not MODEL_PATH.exists():
        return None
    return joblib.load(MODEL_PATH)


def reload_model():
    _load.cache_clear()


def top_terms(model, text, label, n=4):
    """Words in the text that pushed the model toward `label` (for explanations)."""
    tfidf, clf = model.named_steps["tfidf"], model.named_steps["clf"]
    vec = tfidf.transform([text])
    names = tfidf.get_feature_names_out()
    idx = list(clf.classes_).index(label)
    contributions = vec.multiply(clf.coef_[idx]).toarray()[0]
    best = contributions.argsort()[::-1][:n]
    return [names[i] for i in best if contributions[i] > 0]


def predict(text: str, threshold: float = 0.40):
    """Return {label, confidence, top: [(label, p), (label, p)], method, low_confidence, explanation}."""
    text = (text or "").strip()
    bundle = _load()
    rules = classify_by_rules(text)
    if bundle is None:
        rules.update(low_confidence=rules["label"] is None, explanation=_rule_explanation(rules, text))
        return rules
    model = bundle["model"]
    probs = model.predict_proba([text])[0]
    order = probs.argsort()[::-1][:2]
    top = [(model.classes_[i], round(float(probs[i]), 3)) for i in order]
    label, confidence = top[0]
    method = "ml"
    # Keyword hit beats a weak ML guess; both are reported to the user.
    if confidence < threshold and rules["label"]:
        label, confidence, method = rules["label"], rules["confidence"], "rules"
        top = rules["top"] or top
    result = {"label": label, "confidence": confidence, "top": top, "method": method,
              "low_confidence": confidence < threshold}
    if method == "ml":
        terms = top_terms(model, text, label)
        result["explanation"] = f"Predicted '{label}' ({confidence:.0%}) because of: {', '.join(terms) or 'overall wording'}."
    else:
        result["explanation"] = _rule_explanation(rules, text)
    return result


def _rule_explanation(rules, text):
    if not rules["label"]:
        return "No keywords matched and no trained model is available."
    return f"Keyword rules matched the category '{rules['label']}'."
