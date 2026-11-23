"""Calculator: reference values, input sourcing (question vs cited claims), conflicts and missing inputs."""
import pytest

from core.answer import calc
from core.models import CalcPlan, ClaimCheck, VerifiedClaim


def claim(text, span="D1:5.1#s1", verdict="supported"):
    return VerifiedClaim(text=text, span_ids=[span], verdict=verdict,
                         checks=ClaimCheck(spans_valid=True, numbers_ok=True, quote_ok=True, version_ok=True, hhem=0.9))


def test_reference_values():
    assert abs(calc.emi(500000, 13.5, 36)[0] - 16968) <= 1
    assert calc.prepayment_charge(200000, 3)[0] == 6000
    assert calc.prepayment_charge(200000, nil=True)[0] == 0
    assert calc.late_fee_total(500, 3)[0] == 1500
    assert calc.emi(120000, 0, 12)[0] == 10000


def test_emi_rejects_bad_input():
    with pytest.raises(ValueError):
        calc.emi(0, 10, 12)


def test_inr_grouping():
    assert calc.inr(500000) == "₹5,00,000" and calc.inr(16968) == "₹16,968" and calc.inr(1234567.5) == "₹12,34,567.50"
    assert calc.inr(750) == "₹750"


Q_EMI = "What would my EMI be on a ₹5,00,000 loan at the agreement's interest rate for 36 months?"


def test_emi_inputs_from_question_and_cited_claim():
    plan = CalcPlan(kind="emi", given={"principal": 500000, "months": 36})
    out, missing, used = calc.run(plan, Q_EMI, [claim("The interest rate is 13.5% per annum")])
    assert not missing and used == {0}
    assert abs(out["result"] - 16968) <= 1 and out["unit"] == "INR"
    by = {i["name"]: i for i in out["inputs"]}
    assert by["annual interest rate (%)"]["span_id"] == "D1:5.1#s1" and by["loan amount"]["source"] == "question"
    assert len(out["steps"]) == 3


def test_planner_number_not_in_question_is_dropped():
    plan = CalcPlan(kind="emi", given={"principal": 900000, "months": 36})  # 9,00,000 is invented
    out, missing, _ = calc.run(plan, Q_EMI, [claim("The interest rate is 13.5% per annum")])
    assert out is None and missing == ["Missing input: the loan amount"]


def test_missing_document_input():
    plan = CalcPlan(kind="emi", given={"principal": 500000, "months": 36})
    out, missing, _ = calc.run(plan, Q_EMI, [claim("The processing fee is 1%", verdict="supported")])
    assert out is None and missing == ["Missing input: the annual interest rate"]
    out, missing, _ = calc.run(plan, Q_EMI, [claim("The interest rate is 13.5%", verdict="unsupported")])
    assert out is None  # an unverified claim is never an input


def test_prepayment_percent_and_nil():
    q = "What prepayment charge would I pay on an outstanding principal of ₹2,00,000?"
    plan = CalcPlan(kind="prepayment_charge", given={"outstanding": 200000})
    out, _, _ = calc.run(plan, q, [claim("A prepayment charge of 3% of the outstanding principal is payable", "D3:1#s1")])
    assert out["result"] == 6000
    out, _, _ = calc.run(plan, q, [claim("No prepayment charge is payable on floating-rate loans", "D4:1#s1")])
    assert out["result"] == 0 and out["inputs"][1]["span_id"] == "D4:1#s1"


def test_conflicting_fee_shows_every_option_and_no_single_result():
    q = "If I miss 3 payments, what is the total late fee?"
    plan = CalcPlan(kind="late_fee_total", given={"count": 3})
    out, missing, used = calc.run(plan, q, [claim("The late payment fee is ₹500 per instalment", "D1:8.1#s1"),
                                           claim("The late payment fee is ₹750 per instalment", "D2:t#s1")])
    assert not missing and out["result"] is None and used == {0, 1}
    assert any("₹1,500" in s for s in out["steps"]) and any("₹2,250" in s for s in out["steps"])


def test_not_a_calculation():
    assert calc.run(CalcPlan(), "hi", [])[0] is None
