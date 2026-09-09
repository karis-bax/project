"""CSV bank-export importer — pure parsing logic (no FastAPI, no DB).

Responsibilities:
- sniff the delimiter and detect a header row,
- propose a column mapping to date / payee / amount / memo, covering the three
  common amount shapes (one signed column; separate debit/credit columns; one
  amount column plus a type column),
- parse dates tolerantly (MM/DD/YYYY, YYYY-MM-DD, DD/MM/YYYY) and report when the
  slash format is ambiguous across the file rather than guessing,
- normalize payees and compute a stable ``import_hash``,
- run category rules to propose a category per row.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

AMOUNT_SIGNED = "signed"
AMOUNT_DEBIT_CREDIT = "debit_credit"
AMOUNT_TYPE = "amount_type"


@dataclass
class Mapping:
    amount_shape: str = AMOUNT_SIGNED
    date_col: int | None = None
    payee_col: int | None = None
    memo_col: int | None = None
    amount_col: int | None = None
    debit_col: int | None = None
    credit_col: int | None = None
    type_col: int | None = None


@dataclass
class ParsedRow:
    row_index: int
    date: str | None
    payee: str
    amount_cents: int | None
    memo: str
    warnings: list[str] = field(default_factory=list)

    @property
    def importable(self) -> bool:
        return self.date is not None and self.amount_cents is not None


# --- normalization & hashing ------------------------------------------------

_TRAILING_STORE_NUM = re.compile(r"(\s*#?\d[\d-]*)+$")


def normalize_payee(payee: str) -> str:
    """Uppercase, collapse whitespace, strip trailing digits / store numbers."""

    collapsed = re.sub(r"\s+", " ", payee.upper()).strip()
    return _TRAILING_STORE_NUM.sub("", collapsed).strip()


def compute_import_hash(
    account_id: int, date_iso: str, amount_cents: int, payee: str
) -> str:
    raw = f"{account_id}|{date_iso}|{amount_cents}|{normalize_payee(payee)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- money ------------------------------------------------------------------


def money_to_cents(raw: str) -> int | None:
    s = raw.strip()
    if not s:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    if s.endswith("-"):
        negative = True
        s = s[:-1]
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("-"):
        negative = True
        s = s[1:]
    if not s:
        return None
    try:
        cents = int((Decimal(s) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None
    return -cents if negative else cents


# --- dates ------------------------------------------------------------------

_ISO_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

SLASH_MDY = "MM/DD/YYYY"
SLASH_DMY = "DD/MM/YYYY"
SLASH_AMBIGUOUS = "ambiguous"


def detect_slash_format(date_strings: list[str]) -> str | None:
    """Return SLASH_MDY, SLASH_DMY, SLASH_AMBIGUOUS, or None (no slash dates)."""

    saw_slash = False
    looks_mdy = False  # second part > 12 -> day is second -> MM/DD
    looks_dmy = False  # first part > 12 -> day is first -> DD/MM
    for s in date_strings:
        m = _SLASH_RE.match(s.strip())
        if not m:
            continue
        saw_slash = True
        a, b = int(m.group(1)), int(m.group(2))
        if b > 12:
            looks_mdy = True
        if a > 12:
            looks_dmy = True
    if not saw_slash:
        return None
    if looks_mdy and not looks_dmy:
        return SLASH_MDY
    if looks_dmy and not looks_mdy:
        return SLASH_DMY
    # Either no disambiguating row, or conflicting evidence.
    return SLASH_AMBIGUOUS


def parse_date(raw: str, slash_format: str | None) -> tuple[str | None, str | None]:
    """Parse a single date. Returns (iso_or_none, warning_or_none)."""

    s = raw.strip()
    if not s:
        return None, "empty date"
    if _ISO_RE.match(s):
        try:
            y, m, d = (int(p) for p in s.split("-"))
            return date(y, m, d).isoformat(), None
        except ValueError:
            return None, f"invalid date: {raw!r}"

    m = _SLASH_RE.match(s)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        warning: str | None = None
        if slash_format == SLASH_DMY:
            day, month = a, b
        else:
            # MM/DD, and also the tentative choice when ambiguous.
            month, day = a, b
            if slash_format == SLASH_AMBIGUOUS:
                warning = "ambiguous date format; parsed as MM/DD/YYYY"
        try:
            return date(year, month, day).isoformat(), warning
        except ValueError:
            return None, f"invalid date: {raw!r}"

    return None, f"unrecognized date format: {raw!r}"


# --- reading & mapping ------------------------------------------------------


def sniff(content: str) -> tuple[str, bool]:
    """Return (delimiter, has_header)."""

    sample = content[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        # Fall back to the most common delimiter in the sample.
        counts = {d: sample.count(d) for d in [",", ";", "\t", "|"]}
        delimiter = max(counts, key=lambda d: counts[d]) or ","
    try:
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        has_header = True
    return delimiter, has_header


def read_rows(content: str, delimiter: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    return [row for row in reader]


_HEADER_HINTS = {
    "date": ["transaction date", "posted date", "post date", "date"],
    "payee": ["description", "payee", "name", "merchant", "memo/description"],
    "memo": ["memo", "notes", "note", "reference"],
    "amount": ["amount", "value"],
    "debit": ["debit", "withdrawal", "withdrawals", "money out"],
    "credit": ["credit", "deposit", "deposits", "money in"],
    "type": ["type", "transaction type", "debit/credit", "dr/cr"],
}


def _find_col(header: list[str], hints: list[str]) -> int | None:
    lowered = [h.strip().lower() for h in header]
    # Exact match first, then substring.
    for hint in hints:
        for i, name in enumerate(lowered):
            if name == hint:
                return i
    for hint in hints:
        for i, name in enumerate(lowered):
            if hint in name:
                return i
    return None


def propose_mapping(header: list[str] | None, data_rows: list[list[str]]) -> Mapping:
    mapping = Mapping()
    if header:
        mapping.date_col = _find_col(header, _HEADER_HINTS["date"])
        mapping.payee_col = _find_col(header, _HEADER_HINTS["payee"])
        mapping.memo_col = _find_col(header, _HEADER_HINTS["memo"])
        debit = _find_col(header, _HEADER_HINTS["debit"])
        credit = _find_col(header, _HEADER_HINTS["credit"])
        amount = _find_col(header, _HEADER_HINTS["amount"])
        type_col = _find_col(header, _HEADER_HINTS["type"])
        if debit is not None and credit is not None:
            mapping.amount_shape = AMOUNT_DEBIT_CREDIT
            mapping.debit_col = debit
            mapping.credit_col = credit
        elif amount is not None and type_col is not None:
            mapping.amount_shape = AMOUNT_TYPE
            mapping.amount_col = amount
            mapping.type_col = type_col
        else:
            mapping.amount_shape = AMOUNT_SIGNED
            mapping.amount_col = amount
        # If payee and memo collided, prefer distinct columns.
        if mapping.memo_col == mapping.payee_col:
            mapping.memo_col = None
    else:
        mapping = _guess_mapping_no_header(data_rows)
    return mapping


def _guess_mapping_no_header(data_rows: list[list[str]]) -> Mapping:
    mapping = Mapping(amount_shape=AMOUNT_SIGNED)
    if not data_rows:
        return mapping
    width = max(len(r) for r in data_rows)
    sample = data_rows[: min(10, len(data_rows))]
    for col in range(width):
        values = [r[col] for r in sample if col < len(r)]
        if mapping.date_col is None and values and all(
            parse_date(v, None)[0] is not None for v in values if v.strip()
        ):
            mapping.date_col = col
            continue
        if mapping.amount_col is None and values and all(
            money_to_cents(v) is not None for v in values if v.strip()
        ):
            mapping.amount_col = col
            continue
    # First remaining text column becomes payee.
    for col in range(width):
        if col not in (mapping.date_col, mapping.amount_col):
            mapping.payee_col = col
            break
    return mapping


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    return row[index]


def _amount_for_row(row: list[str], mapping: Mapping) -> tuple[int | None, str | None]:
    if mapping.amount_shape == AMOUNT_DEBIT_CREDIT:
        debit = money_to_cents(_cell(row, mapping.debit_col))
        credit = money_to_cents(_cell(row, mapping.credit_col))
        if debit is None and credit is None:
            return None, "no debit or credit amount"
        # Debits are outflows (negative); credits are inflows (positive).
        return (credit or 0) - abs(debit or 0), None
    if mapping.amount_shape == AMOUNT_TYPE:
        magnitude = money_to_cents(_cell(row, mapping.amount_col))
        if magnitude is None:
            return None, "no amount"
        type_val = _cell(row, mapping.type_col).strip().lower()
        is_outflow = any(
            k in type_val for k in ("debit", "withdrawal", "payment", "dr", "out")
        )
        return (-abs(magnitude) if is_outflow else abs(magnitude)), None
    # signed
    cents = money_to_cents(_cell(row, mapping.amount_col))
    if cents is None:
        return None, "no amount"
    return cents, None


def parse_rows(
    data_rows: list[list[str]], mapping: Mapping
) -> tuple[list[ParsedRow], list[str]]:
    """Parse data rows using ``mapping``. Returns (rows, global_warnings)."""

    global_warnings: list[str] = []

    date_strings = [
        _cell(row, mapping.date_col)
        for row in data_rows
        if any(c.strip() for c in row)
    ]
    slash_format = detect_slash_format(date_strings)
    if slash_format == SLASH_AMBIGUOUS:
        global_warnings.append(
            "Date format is ambiguous across the file (MM/DD vs DD/MM); "
            "parsed as MM/DD/YYYY — please verify."
        )

    parsed: list[ParsedRow] = []
    for index, row in enumerate(data_rows):
        if not any(c.strip() for c in row):
            continue  # skip fully blank rows

        warnings: list[str] = []
        iso, date_warn = parse_date(_cell(row, mapping.date_col), slash_format)
        if date_warn:
            warnings.append(date_warn)
        amount_cents, amount_warn = _amount_for_row(row, mapping)
        if amount_warn:
            warnings.append(amount_warn)

        payee = re.sub(r"\s+", " ", _cell(row, mapping.payee_col)).strip()
        memo = re.sub(r"\s+", " ", _cell(row, mapping.memo_col)).strip()

        if iso is None and amount_cents is None:
            warnings.append("row does not look like a transaction; will be skipped")

        parsed.append(
            ParsedRow(
                row_index=index,
                date=iso,
                payee=payee,
                amount_cents=amount_cents,
                memo=memo,
                warnings=warnings,
            )
        )
    return parsed, global_warnings
