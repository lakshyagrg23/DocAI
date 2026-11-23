"""Hindi layer (answering.md §6): detection, digits, number guard, translation fallback, planner question handling."""
from __future__ import annotations

from core import i18n
from core.answer import translate
from core.answer.plan import english_question, sanitise
from core.llm.client import ModelUnavailable
from core.models import QueryPlan, VerifiedClaim
from core.models import ClaimCheck


def test_detect_and_resolve_language():
    assert i18n.detect_language("व्यक्तिगत ऋण पर ब्याज दर क्या है?") == "hi"
    assert i18n.detect_language("What is the interest rate?") == "en"
    assert i18n.detect_language("What is the ब्याज rate on the loan today") == "en"  # mostly English
    assert i18n.detect_language("1234 ?") == "en"
    assert i18n.resolve_language("auto", "ब्याज दर क्या है") == "hi"
    assert i18n.resolve_language("hi", "What is the rate?") == "hi"  # an explicit setting wins
    assert i18n.resolve_language("en", "ब्याज दर क्या है") == "en"


def test_devanagari_digits_become_ascii():
    assert i18n.to_ascii_digits("१३.५% और ₹५००") == "13.5% और ₹500"


def test_number_guard():
    assert i18n.same_numbers("The late fee is ₹500 per instalment.", "विलंब शुल्क प्रति किस्त ₹500 है।")
    assert i18n.same_numbers("Fee is ₹5,000", "शुल्क ₹5000 है")  # grouping commas do not matter
    assert i18n.same_numbers("Rate is 13.5%", "दर १३.५% है")  # digit script does not matter
    assert not i18n.same_numbers("Fee is ₹500", "शुल्क ₹750 है")
    assert not i18n.same_numbers("Fee is ₹500 from 2025", "शुल्क ₹500 है")  # a dropped number is refused


def test_calc_strings_localise_without_touching_numbers():
    calc = {"formula": "Total late fees = fee per instalment × number of late instalments",
            "inputs": [{"name": "late fee per instalment (option 2)", "value": 750.0}, {"name": "something new", "value": 3.0}],
            "steps": ["₹750 × 3 = ₹2,250"], "result": 2250.0}
    out = i18n.localize_calculation(calc, "hi")
    assert out["formula_local"].startswith("कुल विलंब शुल्क")
    assert out["inputs"][0]["name_local"] == "प्रति किस्त विलंब शुल्क (विकल्प 2)"
    assert "name_local" not in out["inputs"][1]  # unknown names stay English
    assert out["steps_local"] == ["₹750 × 3 = ₹2,250"] and out["result"] == 2250.0
    assert i18n.localize_calculation(calc, "en") is calc


def test_english_question_never_uses_the_models_rewrite():
    plan = QueryPlan(question_en="something invented", sub_questions=["x"])
    assert english_question(plan, "What is the late fee?") == "What is the late fee?"
    hi = QueryPlan(question_en="What is the interest rate?", sub_questions=["What is the interest rate?"])
    assert english_question(hi, "ब्याज दर क्या है?") == "What is the interest rate?"
    assert english_question(QueryPlan(sub_questions=["x"]), "ब्याज दर क्या है?") == "ब्याज दर क्या है?"  # no translation: ask as is
    assert sanitise(hi, "ब्याज दर क्या है?").question_en == "What is the interest rate?"


class FakeClient:
    def __init__(self, items=None, boom=False):
        self.items, self.boom = items, boom

    def chat_json(self, messages, model_cls, max_tokens=0):
        if self.boom:
            raise ModelUnavailable("down")
        return model_cls(items=self.items)


def _claim(text: str) -> VerifiedClaim:
    return VerifiedClaim(text=text, span_ids=["D1:5.1#s1"], verdict="supported",
                         checks=ClaimCheck(spans_valid=True, numbers_ok=True, quote_ok=True, version_ok=True))


def test_localize_keeps_only_number_safe_hindi():
    claims = [_claim("The interest rate is 13.5% per annum."), _claim("The late fee is ₹500.")]
    client = FakeClient(["ब्याज दर 13.5% प्रति वर्ष है।", "विलंब शुल्क ₹750 है।"])  # second one changes the number
    missing_local, _ = translate.localize(claims, ["the processing fee"], FakeClient(["प्रोसेसिंग शुल्क"]))
    assert missing_local == ["प्रोसेसिंग शुल्क"]
    claims = [_claim("The interest rate is 13.5% per annum."), _claim("The late fee is ₹500.")]
    translate.localize(claims, [], client)
    assert claims[0].text_local == "ब्याज दर 13.5% प्रति वर्ष है।"
    assert claims[1].text_local is None  # refused: the verified English sentence is shown instead
    assert claims[1].text == "The late fee is ₹500."  # the verified text is never replaced


def test_localize_falls_back_to_english_when_unavailable_or_misaligned():
    c = [_claim("The rate is 13.5%.")]
    assert translate.localize(c, ["missing item"], FakeClient(boom=True))[0] == ["missing item"] and c[0].text_local is None
    assert translate.localize(c, ["missing item"], FakeClient(["only one"]))[0] == ["missing item"]
    assert c[0].text_local is None
    assert translate.localize(c, [], FakeClient(["English only 13.5%"]))[0] == [] and c[0].text_local is None  # must be Devanagari
