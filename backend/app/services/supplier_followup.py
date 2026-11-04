"""Supplier handoffs derived from recorded findings, without sending messages."""
import csv
import hashlib
import io
import json
from decimal import Decimal

from app.services.gstin import is_valid

DEFAULT_CATEGORIES = {"missing_in_2b", "mismatched"}


def money(value):
    return Decimal(str(value or "0")).quantize(Decimal("0.01"))


def safe_cell(value):
    text = str(value if value is not None else "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


def differences(finding):
    return "; ".join(f"{d.get('field', 'Value')}: books {d.get('books', '')}; "
                     f"2B {d.get('gstr2b', '')}" for d in finding.get("differences", []))


def groups(run, reviews):
    by_index = {r.finding_index: r for r in reviews}
    suppliers, unassigned = {}, 0
    for index, finding in enumerate((run.report or {}).get("findings", [])):
        review = by_index.get(index)
        if review and review.status == "resolved" and review.decision == "accept_match":
            continue
        if finding.get("category") not in DEFAULT_CATEGORIES and not (
            review and review.decision == "follow_up"
        ):
            continue
        gstin = (finding.get("supplier_gstin") or "").strip().upper()
        if not is_valid(gstin):
            unassigned += 1
            continue
        group = suppliers.setdefault(gstin, {
            "gstin": gstin, "name": finding.get("supplier_name") or gstin,
            "items": [], "absolute_tax_difference": Decimal("0.00"),
        })
        books, portal = finding.get("books") or {}, finding.get("gstr2b") or {}
        difference = abs(money(books.get("total_tax")) - money(portal.get("total_tax")))
        group["items"].append({
            "finding_index": index,
            "invoice_number": finding.get("invoice_number") or "Unnumbered invoice",
            "category": finding.get("category"),
            "invoice_date": finding.get("invoice_date"), "differences": differences(finding),
            "books_tax": str(money(books.get("total_tax"))) if books else None,
            "gstr2b_tax": str(money(portal.get("total_tax"))) if portal else None,
            "absolute_tax_difference": str(difference),
            "review_status": review.status if review else "open",
        })
        group["absolute_tax_difference"] += difference
    ordered = sorted(suppliers.values(), key=lambda g: (-g["absolute_tax_difference"], g["gstin"]))
    for group in ordered:
        group["absolute_tax_difference"] = str(group["absolute_tax_difference"])
        group["count"] = len(group["items"])
    return ordered, unassigned


def draft(run, business, group):
    buyer = business.trade_name or business.legal_name
    subject = f"Invoice reconciliation query — {buyer} — {run.period}"
    lines = [
        f"Hello {group['name']},", "",
        f"We are reviewing {buyer}'s purchase records against the supplied GSTR-2B "
        f"for {run.period}.",
        f"Supplier GSTIN: {group['gstin']}",
        f"Our GSTIN: {business.gstin or 'Please add before sending'}", "",
        "Please help us confirm the invoice details and relevant filing period "
        "for the following items:",
    ]
    for item in group["items"][:10]:
        lines.append(f"- {item['invoice_number']}: {item['category'].replace('_', ' ')}; "
                     f"books tax INR {item['books_tax'] or 'not present'}, "
                     f"2B tax INR {item['gstr2b_tax'] or 'not present'}. "
                     f"{item['differences']}")
    if group["count"] > 10:
        lines.append(f"The full invoice list contains {group['count']} items.")
    lines += ["", "A missing entry or difference in this snapshot does not by itself establish "
              "a filing error or tax-credit eligibility. Please share the relevant invoice "
              "or filing details so our accountant can review the records.", "", "Thank you."]
    return {"subject": subject, "body": "\n".join(lines), "count": group["count"],
            "fingerprint": fingerprint(run, group),
            "gstin": group["gstin"], "run_id": run.id, "period": run.period}


def fingerprint(run, group):
    snapshot = {"run": run.id, "gstin": group["gstin"], "items": group["items"]}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def supplier_csv(run, business, group):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Run", "Period", "Buyer GSTIN", "Supplier GSTIN", "Invoice",
                     "Finding", "Recorded invoice date", "Books tax INR",
                     "2B tax INR", "Absolute tax difference INR", "Differences to check"])
    # A supplier receives only its own invoice facts, never staff names,
    # internal review notes or another supplier's figures.
    for item in group["items"]:
        writer.writerow([safe_cell(v) for v in [
            run.id, run.period, business.gstin, group["gstin"], item["invoice_number"],
            item["category"], item["invoice_date"], item["books_tax"],
            item["gstr2b_tax"], item["absolute_tax_difference"], item["differences"],
        ]])
    return "\ufeff" + stream.getvalue()
