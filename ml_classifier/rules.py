"""Phase 1: transparent keyword classifier. Keys are Category.slug values."""
KEYWORDS = {
    "streetlight": ["streetlight", "street light", "street lamp", "lamp post", "lamp", "dark road", "light not working", "lights not working"],
    "garbage": ["garbage", "waste", "trash", "bin overflow", "overflowing bin", "rubbish", "litter"],
    "dumping": ["illegal dumping", "dumping", "dumped", "construction debris", "debris dumped"],
    "pothole": ["pothole", "road damage", "broken road", "road hole", "deep hole", "road caved"],
    "water": ["water leak", "water leakage", "pipe burst", "leaking pipe", "burst pipe", "no water supply", "water wastage"],
    "drain": ["blocked drain", "drainage", "sewage", "drain blocked", "manhole", "clogged drain", "waterlogging"],
    "footpath": ["footpath", "pavement", "sidewalk", "broken tiles", "walkway"],
    "traffic": ["traffic signal", "traffic light", "signal not working", "signal timer", "zebra crossing"],
    "animal": ["stray dog", "stray animal", "stray cattle", "stray cow", "dog bite", "monkey"],
    "safety": ["unsafe", "harassment", "open wire", "exposed wire", "fallen tree", "dangerous", "accident prone", "no railing"],
    "park": ["park", "playground", "bench broken", "garden", "public space", "swing"],
}
# Longer, more specific phrases win ties.
PRIORITY = ["dumping", "streetlight", "traffic", "drain", "water", "pothole", "footpath", "animal", "garbage", "safety", "park"]


def classify_by_rules(text: str):
    text = (text or "").lower()
    scores = {}
    for slug, words in KEYWORDS.items():
        hits = [w for w in words if w in text]
        if hits:
            scores[slug] = max(len(h) for h in hits) + 3 * len(hits)
    if not scores:
        return {"label": None, "confidence": 0.0, "top": [], "method": "rules"}
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], PRIORITY.index(kv[0]) if kv[0] in PRIORITY else 99))
    best = ranked[0][0]
    return {"label": best, "confidence": 0.9, "method": "rules",
            "top": [(slug, 0.9 if i == 0 else 0.4) for i, (slug, _) in enumerate(ranked[:2])]}
