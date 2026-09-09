"""Unit tests for the pure CSV importer logic."""

from __future__ import annotations

from pathlib import Path

from app import importer

FIXTURE = Path(__file__).parent / "fixtures" / "messy_bank_export.csv"


def test_normalize_payee_strips_store_numbers() -> None:
    assert importer.normalize_payee("Publix #1234") == "PUBLIX"
    assert importer.normalize_payee("  chevron   0099 ") == "CHEVRON"
    assert importer.normalize_payee("WWW.NETFLIX.COM 866-579") == "WWW.NETFLIX.COM"
    assert importer.normalize_payee("ACME, INC PAYROLL") == "ACME, INC PAYROLL"


def test_money_to_cents_shapes() -> None:
    assert importer.money_to_cents("-52.30") == -5230
    assert importer.money_to_cents("2,465.00") == 246500
    assert importer.money_to_cents("$1,234.56") == 123456
    assert importer.money_to_cents("(40.00)") == -4000
    assert importer.money_to_cents("") is None
    assert importer.money_to_cents("abc") is None


def test_detect_slash_format() -> None:
    assert importer.detect_slash_format(["01/15/2026"]) == importer.SLASH_MDY
    assert importer.detect_slash_format(["13/01/2026"]) == importer.SLASH_DMY
    # No disambiguating day -> ambiguous.
    assert (
        importer.detect_slash_format(["01/02/2026", "03/04/2026"])
        == importer.SLASH_AMBIGUOUS
    )
    # Conflicting evidence -> ambiguous.
    assert (
        importer.detect_slash_format(["01/15/2026", "13/01/2026"])
        == importer.SLASH_AMBIGUOUS
    )
    assert importer.detect_slash_format(["2026-01-01"]) is None


def test_ambiguous_dates_are_reported_not_guessed() -> None:
    rows = [["01/02/2026", "A", "-1.00"], ["03/04/2026", "B", "-2.00"]]
    mapping = importer.Mapping(
        amount_shape=importer.AMOUNT_SIGNED, date_col=0, payee_col=1, amount_col=2
    )
    _parsed, warnings = importer.parse_rows(rows, mapping)
    assert any("ambiguous" in w.lower() for w in warnings)


def test_parse_messy_csv() -> None:
    content = FIXTURE.read_text()
    delimiter, has_header = importer.sniff(content)
    assert delimiter == ","
    assert has_header is True

    all_rows = importer.read_rows(content, delimiter)
    header, data_rows = all_rows[0], all_rows[1:]
    mapping = importer.propose_mapping(header, data_rows)
    assert mapping.amount_shape == importer.AMOUNT_SIGNED
    assert mapping.date_col == 0
    assert mapping.payee_col == 1
    assert mapping.amount_col == 2

    parsed, warnings = importer.parse_rows(data_rows, mapping)
    # Blank line is skipped; the remaining 6 rows are parsed.
    assert len(parsed) == 6
    # Not ambiguous here (all slash dates are MM/DD).
    assert warnings == []

    by_payee = {p.payee: p for p in parsed if p.payee}
    # Comma inside quotes stays a single payee field.
    assert "ACME, INC PAYROLL" in by_payee
    assert by_payee["ACME, INC PAYROLL"].date == "2026-01-16"
    assert by_payee["ACME, INC PAYROLL"].amount_cents == 246500

    publix = [p for p in parsed if p.payee == "PUBLIX #1234"]
    assert len(publix) == 2  # duplicate rows both parse
    assert publix[0].date == "2026-01-15"
    assert publix[0].amount_cents == -5230

    # Trailing summary line has no valid date -> not importable, flagged.
    summary = [p for p in parsed if not p.importable]
    assert len(summary) == 1
    assert summary[0].warnings


def test_debit_credit_and_amount_type_shapes() -> None:
    # Debit/credit columns.
    dc_rows = [["01/05/2026", "Store", "52.30", ""], ["01/06/2026", "Job", "", "2465.00"]]
    dc_map = importer.Mapping(
        amount_shape=importer.AMOUNT_DEBIT_CREDIT,
        date_col=0,
        payee_col=1,
        debit_col=2,
        credit_col=3,
    )
    parsed, _ = importer.parse_rows(dc_rows, dc_map)
    assert parsed[0].amount_cents == -5230
    assert parsed[1].amount_cents == 246500

    # Amount + type column.
    at_rows = [["01/05/2026", "Store", "52.30", "Debit"], ["01/06/2026", "Job", "2465.00", "Credit"]]
    at_map = importer.Mapping(
        amount_shape=importer.AMOUNT_TYPE,
        date_col=0,
        payee_col=1,
        amount_col=2,
        type_col=3,
    )
    parsed2, _ = importer.parse_rows(at_rows, at_map)
    assert parsed2[0].amount_cents == -5230
    assert parsed2[1].amount_cents == 246500
