"""UI strings (en / hi). Only labels live here; answers are translated by the pipeline (M10)."""
from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "en": {"tagline": "Answers only with proof.", "new_chat": "New chat", "chats": "Chats", "settings": "Chat settings",
           "as_of": "As-of date", "language": "Language", "ask": "Ask about your documents…",
           "answered": "Answered", "partial": "Partially answered", "conflict": "Documents disagree",
           "abstained": "I don't have proof", "faithfulness": "Faithfulness", "missing": "What's missing",
           "blocked": "Blocked claims", "audit": "Audit", "rule_in_force": "Rule in force", "disagree": "Documents disagree",
           "calculation": "Calculation", "quote": "Quote", "abstain_text": "I don't have proof for this in the uploaded documents.",
           "offline": "The model is warming up (about 2-3 min). Your documents and the Conflicts and Amendments pages are still available."},
    "hi": {"tagline": "केवल प्रमाण के साथ उत्तर।", "new_chat": "नई चैट", "chats": "चैट", "settings": "चैट सेटिंग",
           "as_of": "तिथि", "language": "भाषा", "ask": "अपने दस्तावेज़ों के बारे में पूछें…",
           "answered": "उत्तर मिला", "partial": "आंशिक उत्तर", "conflict": "दस्तावेज़ों में अंतर",
           "abstained": "मेरे पास प्रमाण नहीं है", "faithfulness": "विश्वसनीयता", "missing": "क्या कमी है",
           "blocked": "अवरुद्ध दावे", "audit": "ऑडिट", "rule_in_force": "लागू नियम", "disagree": "दस्तावेज़ों में अंतर",
           "calculation": "गणना", "quote": "उद्धरण", "abstain_text": "अपलोड किए गए दस्तावेज़ों में इसका प्रमाण मेरे पास नहीं है।",
           "offline": "मॉडल शुरू हो रहा है (लगभग 2-3 मिनट)। आपके दस्तावेज़ और विरोध/संशोधन पृष्ठ उपलब्ध हैं।"},
}


def t(key: str, lang: str = "en") -> str:
    return STRINGS.get(lang, STRINGS["en"]).get(key) or STRINGS["en"].get(key, key)
