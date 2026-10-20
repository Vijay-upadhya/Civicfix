from django.test import SimpleTestCase

from . import predictor
from .rules import classify_by_rules


class RuleTests(SimpleTestCase):
    def test_keyword_mapping(self):
        for text, slug in [("The street light is broken", "streetlight"), ("garbage everywhere", "garbage"),
                           ("a big pothole", "pothole"), ("pipe burst on the road", "water"), ("blocked drain near the school", "drain")]:
            self.assertEqual(classify_by_rules(text)["label"], slug, text)

    def test_no_match(self):
        self.assertIsNone(classify_by_rules("nothing relevant")["label"])


class MLTests(SimpleTestCase):
    def test_model_predictions(self):
        for text, slug in [("Large pothole near the main gate", "pothole"), ("Garbage overflowing beside the market", "garbage"),
                           ("Street lamp is not working at night", "streetlight"), ("Water leaking from the pipe near the park", "water"),
                           ("Drain is blocked after heavy rain", "drain")]:
            r = predictor.predict(text)
            self.assertEqual(r["label"], slug, text)
            self.assertFalse(r["low_confidence"])
            self.assertEqual(len(r["top"]), 2)
            self.assertTrue(r["explanation"])

    def test_low_confidence_for_vague_text(self):
        r = predictor.predict("hello there something", threshold=0.9)
        self.assertTrue(r["low_confidence"])
        self.assertLess(r["confidence"], 0.9)
