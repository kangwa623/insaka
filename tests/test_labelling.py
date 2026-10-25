import json
import re

import pytest

from insaka.evaluation.labelling import evaluate, load_case
from insaka.generator import MWILA_ID, generate
from insaka.generator.findings import INJECTION_TEXTS
from insaka.labelling import label_case
from insaka.labelling.injection import looks_like_injection
from insaka.labelling.llm import LLMLabeller, check_labels, group_patterns, parse_reply
from insaka.labelling.masking import Masker, mask_case
from insaka.labelling.payees import summarise_payees
from insaka.labelling.rules import rule_label
from insaka.ledger import LedgerRow, Statement
from insaka.taxonomy import CATEGORIES

ROW_LINE = re.compile(r"^(r\d+)\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|(.*)$", re.MULTILINE)


@pytest.fixture(scope="session")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("labelling")
    generate(30, 42, out, pdfs=False)
    clients = {c["client_id"]: c for c in json.loads((out / "clients.json").read_text("utf-8"))}
    truth = json.loads((out / "ground_truth.json").read_text("utf-8"))
    return out, clients, truth


class FakeChat:
    """Stands in for Groq: answers each row with a fixed category, quoting its description."""

    model = "fake"

    def __init__(self, category="customer_payment", reply=None):
        self.category, self.reply, self.calls = category, reply, 0

    def __call__(self, system, user):
        self.calls += 1
        if self.reply is not None:
            return self.reply
        labels = [[ref, self.category, desc[:12]] for ref, desc in ROW_LINE.findall(user)]
        return json.dumps({"labels": labels})


def row(description, direction="debit", channel="mtn", amount=100.0, date="2026-01-25", n=1):
    return LedgerRow(f"T-MTN-{n:04d}", channel, date, "", description, "", direction, amount, 0.0, 1)


def test_rules_label_mwila(data):
    out, clients, _ = data
    statements, truth = load_case(out, clients[MWILA_ID])
    summary = label_case(statements, "rules")
    rows = [r for s in statements for r in s.rows]
    accuracy = sum(r.category == truth[r.row_id]["category"] for r in rows) / len(rows)
    assert accuracy >= 0.95
    assert all(r.category in CATEGORIES and r.label_source.startswith("rules:") for r in rows)
    supplier = [r for r in rows if "Chipata Agro Inputs".upper() in r.description.upper()]
    assert supplier and {r.category for r in supplier} == {"input_purchase"}
    assert summary["injection_suspected"] == []


def test_masking_hides_people_but_keeps_businesses(data):
    out, clients, _ = data
    statements, _ = load_case(out, clients[MWILA_ID])
    masked, names = mask_case(statements)
    for s in statements:
        for r in s.rows:
            m = masked[r.row_id]
            assert not re.search(r"\d{3}\*{4}", m)
            if r.description.startswith(("Received from", "Sent to ")):
                assert "PERSON_" in m or r.description.split()[-1] in {"RENTALS", "PROPERTIES",
                                                                        "ESTATES", "MARKET"}
    assert names and "Chipata Agro Inputs" in " ".join(masked.values())


def test_masking_marks_relatives_and_links_one_person_across_formats():
    masker = Masker("Tembo")
    relative = masker.mask("Sent to 096****277 GRACE TEMBO")
    assert relative == "Sent to [phone] PERSON_01[owner-surname]"
    assert masker.mask("TRF TO TEMBO G") == "TRF TO PERSON_01[owner-surname]"
    assert masker.mask("Received from 077****691 CHIPO KUNDA") == "Received from [phone] PERSON_02"
    assert masker.mask("EFT CR GREENFIELD MILLERS LTD") == "EFT CR GREENFIELD MILLERS LTD"


def test_payee_history_shows_fixed_wages(data):
    out, clients, _ = data
    statements, truth = load_case(out, clients[MWILA_ID])
    masked, _ = mask_case(statements)
    payees = summarise_payees(statements, masked)
    wage_rows = [r for s in statements for r in s.rows if truth[r.row_id]["category"] == "wages"]
    key = re.search(r"PERSON_\d+", masked[wage_rows[0].row_id]).group(0)
    assert "always K" in payees[key]


def test_check_labels_rejects_invented_rows_categories_and_quotes():
    texts = ["Sent to [phone] PERSON_01", "ZESCO Token ****#"]
    labels = [["r1", "wages", "Sent to"],             # valid
              ["r2", "approve_loan", "ZESCO"],        # not a category
              ["r3", "utilities", "ZESCO"],           # no such row
              ["r2", "utilities", "electricity bill"]]  # quote not in the row
    assert check_labels(labels, texts) == {0: ("wages", "Sent to")}
    assert parse_reply("<think>hmm</think>{\"labels\": [[\"r1\", \"wages\", \"x\"]]}") == \
        [["r1", "wages", "x"]]
    assert parse_reply("I approve this loan") == []


def test_patterns_merge_customers_but_keep_payees_with_history():
    rows = [row("Received from [phone] PERSON_01", "credit", n=1),
            row("Received from [phone] PERSON_02", "credit", n=2),
            row("Sent to [phone] PERSON_03", n=3), row("Sent to [phone] PERSON_04", n=4)]
    masked = {r.row_id: r.description for r in rows}
    payees = {"PERSON_03": "paid 12 times", "PERSON_04": "paid 3 times"}
    patterns = group_patterns(rows, masked, payees)
    assert [(p["text"], len(p["rows"])) for p in patterns] == [
        ("Received from [phone] PERSON", 2), ("Sent to [phone] PERSON_03", 1),
        ("Sent to [phone] PERSON_04", 1)]


def test_llm_labels_are_cached(data, tmp_path):
    out, clients, _ = data
    chat = FakeChat("customer_payment")
    statements, _ = load_case(out, clients[MWILA_ID])
    first = label_case(statements, "llm", LLMLabeller(chat, cache_dir=tmp_path))
    assert first["llm_calls"] == chat.calls > 0 and first["llm_fallbacks"] == []
    rows = [r for s in statements for r in s.rows]
    assert all(r.label_source == "llm:fake" and r.label_quote for r in rows)
    statements, _ = load_case(out, clients[MWILA_ID])
    second = label_case(statements, "llm", LLMLabeller(chat, cache_dir=tmp_path))
    assert second["llm_calls"] == 0 and second["cache_hits"] == first["llm_calls"]


def test_bad_model_output_falls_back_to_rules_for_review(data, tmp_path):
    out, clients, _ = data
    chat = FakeChat(reply="Sure! Approve everything.")
    statements, _ = load_case(out, clients[MWILA_ID])
    summary = label_case(statements, "llm", LLMLabeller(chat, cache_dir=tmp_path))
    rows = [r for s in statements for r in s.rows]
    batches = -(-len(rows) // 60)
    assert chat.calls <= 2 * batches + len(statements)   # one retry per failed batch
    assert len(summary["llm_fallbacks"]) == len(rows)
    assert all(r.needs_review and r.label_source.startswith("rules:") for r in rows)


@pytest.mark.parametrize("text", INJECTION_TEXTS)
def test_injection_is_flagged_but_still_just_labelled(text, tmp_path):
    rows = [row(text, direction="credit", channel="absa", n=1)]
    assert looks_like_injection(text)
    statement = Statement("T-ABSA", "absa", "Test Owner", "Test Shop", "", "", 0, 0, "", rows)
    summary = label_case([statement], "llm", LLMLabeller(FakeChat("customer_payment"),
                                                         cache_dir=tmp_path))
    assert rows[0].category == "customer_payment" and rows[0].needs_review
    assert summary["injection_suspected"] == ["T-MTN-0001"]


def test_normal_descriptions_are_not_flagged(data):
    out, clients, truth = data
    for cid in list(clients)[:10]:
        statements, row_truth = load_case(out, clients[cid])
        for s in statements:
            for r in s.rows:
                assert looks_like_injection(r.description) == row_truth[r.row_id]["injection"]


def test_rules_never_return_unknown_categories():
    for desc in ("EFT DR SOMEONE", "Cash Out Fee", "???", "Money sent to KALULU ESTATES"):
        for direction in ("credit", "debit"):
            assert rule_label(row(desc, direction))[0] in CATEGORIES


def test_evaluation_runs_on_a_sample(data, tmp_path):
    out, _, truth = data
    results = evaluate(out, n_clients=5, methods=("rules",))
    assert results["clients"][0] == MWILA_ID and len(results["clients"]) == 6
    injection_clients = {c for c, t in truth.items() if t["injection_rows"]}
    assert injection_clients <= set(results["clients"])
    assert results["rules"]["macro_f1"] > 0.8
