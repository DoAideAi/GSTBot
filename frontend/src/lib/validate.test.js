import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  GSTR2B_EXTENSIONS,
  GST_RATES,
  MAX_UPLOAD_MB,
  amountError,
  arnError,
  fileError,
  gstinShapeError,
  hsnError,
  invoiceDateError,
  invoiceDraftErrors,
  normalizeArn,
  normalizeGstin,
  normalizePlaceOfSupply,
  paidAtError,
  partitionFiles,
  placeOfSupplyError,
  registrationErrors,
  taxRateError,
} from "./validate";

/** A File of a stated size without allocating the bytes for it. */
function sizedFile(name, bytes, type = "application/pdf") {
  const file = new File(["x"], name, { type });
  // File.size is read-only and derives from the parts; a 20 MB fixture built
  // honestly would allocate 20 MB per test.
  Object.defineProperty(file, "size", { value: bytes });
  return file;
}

describe("fileError", () => {
  it("accepts a normal invoice", () => {
    expect(fileError(sizedFile("invoice.pdf", 400_000))).toBe("");
  });

  it("names the extension it will not read", () => {
    const message = fileError(sizedFile("scans.zip", 400_000));
    expect(message).toContain(".zip");
    expect(message).toContain(".pdf");
  });

  it("rejects a file with no extension at all", () => {
    expect(fileError(sizedFile("scan", 400_000))).toContain("no extension");
  });

  it("is case-insensitive about the extension", () => {
    // Phone cameras and scanners routinely emit .PDF and .JPG.
    expect(fileError(sizedFile("INVOICE.PDF", 400_000))).toBe("");
    expect(fileError(sizedFile("photo.JPEG", 400_000))).toBe("");
  });

  it("takes the last dot, not the first", () => {
    expect(fileError(sizedFile("april.2026.invoice.pdf", 1000))).toBe("");
    expect(fileError(sizedFile("invoice.pdf.exe", 1000))).not.toBe("");
  });

  it("refuses an empty file and says why it might be empty", () => {
    // Zero bytes reaches the parser as an empty document and comes back as
    // "no fields found", which reads like the extraction failed.
    expect(fileError(sizedFile("invoice.pdf", 0))).toContain("still be downloading");
  });

  it("refuses a file over the limit and states its actual size", () => {
    const message = fileError(sizedFile("scan.pdf", 41 * 1024 * 1024));
    expect(message).toContain("41.0 MB");
    expect(message).toContain(`${MAX_UPLOAD_MB} MB`);
  });

  it("accepts a file exactly on the limit", () => {
    // The server's check is `> max_bytes`, so the boundary must match or the
    // browser refuses a file the API would have taken.
    expect(fileError(sizedFile("scan.pdf", MAX_UPLOAD_MB * 1024 * 1024))).toBe("");
  });

  it("applies the GSTR-2B list when given it", () => {
    expect(fileError(sizedFile("2b.json", 5000), { extensions: GSTR2B_EXTENSIONS })).toBe("");
    // The portal hands the 2B out as a zip, which is the usual mistake here.
    expect(
      fileError(sizedFile("2b.zip", 5000), { extensions: GSTR2B_EXTENSIONS }),
    ).toContain(".json");
    // A PDF is a fine invoice but not a fine 2B.
    expect(
      fileError(sizedFile("2b.pdf", 5000), { extensions: GSTR2B_EXTENSIONS }),
    ).not.toBe("");
  });

  it("says something useful when there is no file", () => {
    expect(fileError(null)).toBe("No file selected.");
  });

  it("names a single permitted extension without a stray 'and'", () => {
    // readableList joins with "and" from two upwards. A caller narrowing the
    // list to one would otherwise read "Use  and .json.".
    expect(fileError(sizedFile("scan.pdf", 5000), { extensions: [".json"] })).toBe(
      "scan.pdf is .pdf, which cannot be read. Use .json.",
    );
  });

  it("refuses an entry with no filename rather than reading past it", () => {
    // A directory dragged into the dropzone reaches the FileList as an entry
    // with nothing to take an extension from. Refusing it is right; throwing
    // on the way to deciding that would take the whole drop down with it.
    expect(fileError({ size: 5000 })).toContain("cannot be read");
  });
});

describe("partitionFiles", () => {
  it("keeps the good files and reports each bad one", () => {
    const { accepted, rejected } = partitionFiles([
      sizedFile("a.pdf", 1000),
      sizedFile("b.zip", 1000),
      sizedFile("c.jpg", 1000),
    ]);

    // The whole point: one bad file must not cancel the batch.
    expect(accepted.map((f) => f.name)).toEqual(["a.pdf", "c.jpg"]);
    expect(rejected).toHaveLength(1);
    expect(rejected[0].file.name).toBe("b.zip");
    expect(rejected[0].error).toContain(".zip");
  });

  it("handles an empty selection", () => {
    expect(partitionFiles(null).accepted).toEqual([]);
    expect(partitionFiles(undefined).rejected).toEqual([]);
  });
});

describe("normalizeGstin", () => {
  it("strips the separators a paste from a PDF carries", () => {
    expect(normalizeGstin("27 AAPFU0939F 1ZV")).toBe("27AAPFU0939F1ZV");
    expect(normalizeGstin("27-aapfu0939f1zv")).toBe("27AAPFU0939F1ZV");
  });

  it("survives null", () => {
    expect(normalizeGstin(null)).toBe("");
  });
});

describe("gstinShapeError", () => {
  it("passes a well-formed GSTIN", () => {
    expect(gstinShapeError("27AAPFU0939F1ZV")).toBe("");
  });

  it("treats empty as the caller's business, not an error", () => {
    // Clearing the field on the invoice form is a legitimate edit.
    expect(gstinShapeError("")).toBe("");
    expect(gstinShapeError(null)).toBe("");
  });

  it("counts the characters it actually got", () => {
    expect(gstinShapeError("27AAPFU0939F1Z")).toContain("14");
  });

  it("rejects a digit where the PAN letters belong", () => {
    expect(gstinShapeError("27AAPF00939F1ZV")).toContain("format");
  });

  it("rejects a missing Z in the fourteenth position", () => {
    expect(gstinShapeError("27AAPFU0939F1XV")).toContain("format");
  });

  it("rejects 00 as a state code", () => {
    // The usual result of a leading digit being eaten on paste.
    expect(gstinShapeError("00AAPFU0939F1ZV")).toContain("state code");
  });

  it("does not judge the check digit", () => {
    // Deliberate: the checksum lives on the server, and a second
    // implementation of that arithmetic is how the two come to disagree.
    // This GSTIN is correctly shaped but checksum-invalid, and passes here.
    expect(gstinShapeError("27AAPFU0939F1ZZ")).toBe("");
  });

  it("normalizes before judging", () => {
    expect(gstinShapeError("27 aapfu0939f 1zv")).toBe("");
  });
});

describe("amountError", () => {
  it("accepts blank, which clears the field", () => {
    expect(amountError("")).toBe("");
    expect(amountError(null)).toBe("");
  });

  it("accepts ordinary amounts", () => {
    expect(amountError("0")).toBe("");
    expect(amountError("1234.56")).toBe("");
    expect(amountError(".5")).toBe("");
  });

  it("rejects a negative, matching the server's ge=0", () => {
    expect(amountError("-1", "CGST")).toBe("CGST cannot be negative.");
  });

  it("rejects text", () => {
    expect(amountError("12oo")).toContain("must be a number");
    expect(amountError("1,234")).toContain("must be a number");
  });

  it("rejects a lone dot or minus", () => {
    expect(amountError(".")).toContain("must be a number");
    expect(amountError("-")).toContain("must be a number");
  });

  it("rejects more precision than the column holds", () => {
    // Numeric(14, 2) silently rounds a third decimal, producing a total the
    // user never typed.
    expect(amountError("100.005")).toContain("paise");
    expect(amountError("100.00")).toBe("");
  });

  it("rejects a run of digits long enough to overflow to Infinity", () => {
    // Digits only, so the shape check passes, but Number() overflows. The
    // isFinite guard answers before the size check does, so this reads as
    // "not a number" rather than as "too large" — either refusal is correct,
    // and pinning which one arrives keeps the guard from being dropped as
    // redundant on the assumption that the size check covers it.
    expect(amountError("9".repeat(400))).toBe("Amount must be a number.");
  });

  it("rejects an amount too large for the column", () => {
    expect(amountError("1000000000000")).toContain("too large");
  });

  it("labels the field it was given", () => {
    expect(amountError("-5", "Taxable value")).toContain("Taxable value");
  });
});

describe("invoiceDateError", () => {
  const today = new Date(2026, 4, 20); // 20 May 2026, local time.

  it("accepts a past date", () => {
    expect(invoiceDateError("2026-04-15", { today })).toBe("");
  });

  it("accepts today", () => {
    expect(invoiceDateError("2026-05-20", { today })).toBe("");
  });

  it("rejects tomorrow", () => {
    // A future-dated invoice lands in a period that cannot be filed yet, and
    // then reconciles as missing from the 2B every month until someone looks.
    expect(invoiceDateError("2026-05-21", { today })).toContain("future");
  });

  it("rejects a date before GST existed", () => {
    expect(invoiceDateError("2017-06-30", { today })).toContain("1 July 2017");
    expect(invoiceDateError("2017-07-01", { today })).toBe("");
  });

  it("rejects a day that does not exist", () => {
    expect(invoiceDateError("2026-02-30", { today })).toContain("does not exist");
    expect(invoiceDateError("2026-13-01", { today })).toContain("does not exist");
  });

  it("rejects a non-ISO string", () => {
    expect(invoiceDateError("15/04/2026", { today })).toContain("YYYY-MM-DD");
  });

  it("accepts blank", () => {
    expect(invoiceDateError("", { today })).toBe("");
  });

  it("does not shift the day near midnight in a positive-offset zone", () => {
    // The comparison is string-on-string against an ISO date for this reason:
    // parsing to Date drags the browser's timezone in, and in IST a date typed
    // late in the evening can read as tomorrow in UTC and be refused.
    const lateEvening = new Date(2026, 4, 20, 23, 45);
    expect(invoiceDateError("2026-05-20", { today: lateEvening })).toBe("");
  });
});

describe("hsnError", () => {
  it("accepts the real code lengths", () => {
    expect(hsnError("8471")).toBe("");
    expect(hsnError("847130")).toBe("");
    expect(hsnError("84713010")).toBe("");
    expect(hsnError("84")).toBe("");
  });

  it("rejects letters", () => {
    expect(hsnError("84A1")).toContain("digits only");
  });

  it("rejects more than the column holds", () => {
    expect(hsnError("123456789")).toContain("8 digits");
  });

  it("rejects a single digit", () => {
    expect(hsnError("8")).toContain("at least 2");
  });

  it("accepts blank", () => {
    expect(hsnError("")).toBe("");
  });
});

describe("invoiceDraftErrors", () => {
  const today = new Date(2026, 4, 20);

  function draft(overrides = {}) {
    return {
      counterparty_gstin: "27AAPFU0939F1ZV",
      counterparty_name: "Acme Supplies",
      invoice_number: "INV-1",
      invoice_date: "2026-04-15",
      hsn_code: "8471",
      taxable_value: "1000",
      cgst: "90",
      sgst: "90",
      igst: "",
      cess: "",
      total_value: "1180",
      ...overrides,
    };
  }

  it("passes a clean draft with no warnings", () => {
    const { errors, warnings } = invoiceDraftErrors(draft(), { today });
    expect(errors).toEqual({});
    expect(warnings).toEqual([]);
  });

  it("states a totals mismatch in Indian grouping, as every other amount is", () => {
    const { warnings } = invoiceDraftErrors(
      draft({ taxable_value: "1234567", cgst: "111111.03", sgst: "111111.03", total_value: "1400000" }),
      { today },
    );
    expect(warnings).toEqual([
      "Taxable plus tax comes to ₹14,56,789.06, but the total says ₹14,00,000.00.",
    ]);
  });

  it("keys each error to its field", () => {
    const { errors } = invoiceDraftErrors(
      draft({ cgst: "-1", invoice_date: "2027-01-01", hsn_code: "abc" }),
      { today },
    );
    expect(Object.keys(errors).sort()).toEqual(["cgst", "hsn_code", "invoice_date"]);
  });

  it("enforces the server's max lengths", () => {
    const { errors } = invoiceDraftErrors(
      draft({ invoice_number: "x".repeat(65), counterparty_name: "y".repeat(256) }),
      { today },
    );
    expect(errors.invoice_number).toContain("64");
    expect(errors.counterparty_name).toContain("255");
  });

  it("warns when a supply is both interstate and intrastate", () => {
    const { errors, warnings } = invoiceDraftErrors(
      draft({ igst: "180", cgst: "90", sgst: "90", total_value: "1360" }),
      { today },
    );
    // A warning, not an error: it must still be savable, because a credit note
    // adjusting a supply booked the other way legitimately looks like this.
    expect(errors).toEqual({});
    expect(warnings.join(" ")).toContain("interstate or intrastate");
  });

  it("does not call an interstate invoice both, when its CGST/SGST read zero", () => {
    // The parser writes 0 into the columns it found nothing in rather than
    // leaving them blank, so an ordinary IGST invoice arrives with cgst and
    // sgst present and zero. Reading "has CGST/SGST" as "the field is there"
    // would warn about every interstate supply in the ledger.
    const { errors, warnings } = invoiceDraftErrors(
      draft({ igst: "180", cgst: "0", sgst: "0", total_value: "1180" }),
      { today },
    );
    expect(errors).toEqual({});
    expect(warnings).toEqual([]);
  });

  it("counts a tax head the parser missed as zero in the total check", () => {
    // A blank SGST is a field the extraction did not find, not a reason to
    // skip the arithmetic — the mismatch is exactly the signal that says so.
    const { warnings } = invoiceDraftErrors(
      draft({ cgst: "90", sgst: "", total_value: "1180" }),
      { today },
    );
    expect(warnings.join(" ")).toContain("₹1,090.00");
    expect(warnings.join(" ")).toContain("₹1,180.00");
  });

  it("warns when CGST and SGST differ", () => {
    const { warnings } = invoiceDraftErrors(draft({ cgst: "90", sgst: "80" }), { today });
    expect(warnings.join(" ")).toContain("normally equal");
  });

  it("warns when the total does not add up", () => {
    const { warnings } = invoiceDraftErrors(draft({ total_value: "5000" }), { today });
    expect(warnings.join(" ")).toContain("₹5,000.00");
  });

  it("tolerates rounding of a rupee in the total", () => {
    // Line-level rounding on a real invoice is legal and routine.
    expect(invoiceDraftErrors(draft({ total_value: "1180.50" }), { today }).warnings).toEqual([]);
  });

  it("does not warn about arithmetic on a field that is already wrong", () => {
    // Otherwise a half-typed amount produces "the total does not add up" on
    // every keystroke, on top of the real message.
    const { errors, warnings } = invoiceDraftErrors(draft({ cgst: "9o" }), { today });
    expect(errors.cgst).toBeTruthy();
    expect(warnings).toEqual([]);
  });

  it("treats an all-blank draft as valid", () => {
    // Every field is optional on the server; blanks clear them.
    const blank = Object.fromEntries(Object.keys(draft()).map((k) => [k, ""]));
    expect(invoiceDraftErrors(blank, { today }).errors).toEqual({});
  });
});

describe("registrationErrors", () => {
  const good = {
    gstin: "27AAPFU0939F1ZV",
    legal_name: "Acme Supplies Pvt Ltd",
    email: "owner@acmesupplies.in",
    password: "correct horse battery",
  };

  it("passes a complete form", () => {
    expect(registrationErrors(good)).toEqual({});
  });

  // The form sets `noValidate`, which turns off the input's own `type="email"`
  // check along with the required-field bubbles it was disabled for. Without a
  // rule here, registering with the box empty was a round trip that came back
  // as a generic 400 pointing at no field in particular.
  it("requires an email", () => {
    expect(registrationErrors({ ...good, email: "" }).email).toBe("Enter your email.");
  });

  it("treats whitespace as empty", () => {
    expect(registrationErrors({ ...good, email: "   " }).email).toBe("Enter your email.");
  });

  it("requires an email to be shaped like one", () => {
    expect(registrationErrors({ ...good, email: "owner" }).email).toContain("does not look like");
    expect(registrationErrors({ ...good, email: "owner@acme" }).email).toContain(
      "does not look like",
    );
  });

  it("accepts the addresses a real business registers with", () => {
    // The shape check is a subset of the server's, so it must not refuse
    // anything the server would take. Plus-addressing and a multi-label host
    // are the two that a stricter regex usually gets wrong.
    for (const email of [
      "owner+gst@acmesupplies.in",
      "a.b@mail.co.in",
      "OWNER@ACME.IN",
    ]) {
      expect(registrationErrors({ ...good, email })).toEqual({});
    }
  });

  it("accepts an empty GSTIN — it is optional", () => {
    expect(registrationErrors({ ...good, gstin: "" }).gstin).toBeUndefined();
  });

  it("passes the shape complaint through", () => {
    expect(registrationErrors({ ...good, gstin: "27AAPFU" }).gstin).toContain("15 characters");
  });

  it("requires a legal name when a GSTIN is provided", () => {
    expect(registrationErrors({ ...good, legal_name: "   " }).legal_name).toContain("required");
  });

  it("allows a blank legal name when no GSTIN is given", () => {
    expect(registrationErrors({ ...good, gstin: "", legal_name: "" }).legal_name).toBeUndefined();
  });

  it("enforces the server's password minimum", () => {
    expect(registrationErrors({ ...good, password: "short" }).password).toContain("8 characters");
    expect(registrationErrors({ ...good, password: "12345678" }).password).toBeUndefined();
  });

  it("faults every missing field on a form whose keys were never set", () => {
    // The page seeds its state with empty strings, so the absent-key form is
    // not what the UI sends. It is what a restored draft or a future field
    // rename produces, and each rule has to read the absence as "not filled
    // in" rather than as the literal "undefined" that String() would make of
    // it — which is 9 characters long, and would pass the password rule.
    expect(registrationErrors({})).toEqual({
      email: "Enter your email.",
      password: "Use at least 8 characters.",
    });
  });
});


describe("arnError", () => {
  it("accepts the portal's 15-character acknowledgement", () => {
    expect(arnError("AA270426000000X")).toBe("");
  });

  it("accepts one typed with the spaces the acknowledgement prints", () => {
    expect(arnError("AA2704 26000000 X")).toBe("");
  });

  it("accepts a lower-cased one, since the server folds it", () => {
    expect(arnError("aa270426000000x")).toBe("");
  });

  it("treats a blank field as acceptable rather than missing", () => {
    // The acknowledgement is often not to hand when someone marks a return
    // done, and refusing the record without it would leave the deadline alert
    // firing for a return that is genuinely filed.
    for (const blank of ["", "   ", null, undefined]) {
      expect(arnError(blank)).toBe("");
    }
  });

  it("refuses punctuation, which no ARN carries", () => {
    expect(arnError("AA2704-2600-0000")).toContain("letters and digits");
  });

  it("refuses something far too short or too long to be one", () => {
    expect(arnError("AB12")).toContain("does not look like an ARN");
    expect(arnError("A".repeat(33))).toContain("does not look like an ARN");
  });

  it("stays as loose as the server's own pattern at both ends", () => {
    // Mirrors ARN_PATTERN in app/services/filing.py. Too strict is the harmful
    // direction: it locks a business out of recording a filing that happened.
    expect(arnError("A".repeat(10))).toBe("");
    expect(arnError("A".repeat(32))).toBe("");
    expect(arnError("A".repeat(9))).not.toBe("");
  });
});

describe("normalizeArn", () => {
  it("strips whitespace and upper-cases", () => {
    expect(normalizeArn(" aa2704 26000000 x ")).toBe("AA270426000000X");
  });

  it("gives the empty string for nothing, so a caller can omit the field", () => {
    // An absent ARN means "not to hand" on the server and leaves a stored one
    // alone; an empty string is not an ARN and would be refused.
    expect(normalizeArn("")).toBe("");
    expect(normalizeArn(null)).toBe("");
    expect(normalizeArn("   ")).toBe("");
  });
});

describe("placeOfSupplyError", () => {
  it("accepts a two-digit state code", () => {
    expect(placeOfSupplyError("27")).toBe("");
    expect(placeOfSupplyError("07")).toBe("");
    expect(placeOfSupplyError("97")).toBe("");
  });

  it("accepts a single digit, because that is what people type", () => {
    // 7 for Delhi is what a person types and 07 is what the portal wants,
    // which is exactly what the server's own validator does with it.
    expect(placeOfSupplyError("7")).toBe("");
  });

  it("treats blank as acceptable — clearing the field is a legitimate edit", () => {
    for (const blank of ["", "  ", null, undefined]) {
      expect(placeOfSupplyError(blank)).toBe("");
    }
  });

  it("refuses anything that is not a code", () => {
    expect(placeOfSupplyError("ZZ")).toContain("two-digit state code");
    expect(placeOfSupplyError("Maharashtra")).toContain("two-digit state code");
    expect(placeOfSupplyError("270")).toContain("two-digit state code");
  });

  it("refuses 00, which is the usual result of a leading digit being eaten", () => {
    expect(placeOfSupplyError("00")).toContain("not a state code");
  });

  it("leaves the list of real codes to the server", () => {
    // A second copy of STATE_CODES here would eventually disagree with the one
    // that decides whether a return uploads. 39 is not assigned; the server
    // says so, and this only checks the shape.
    expect(placeOfSupplyError("39")).toBe("");
  });
});

describe("normalizePlaceOfSupply", () => {
  it("pads a single digit the way the portal wants it", () => {
    expect(normalizePlaceOfSupply("7")).toBe("07");
    expect(normalizePlaceOfSupply(" 7 ")).toBe("07");
  });

  it("leaves anything else alone", () => {
    expect(normalizePlaceOfSupply("27")).toBe("27");
    expect(normalizePlaceOfSupply("")).toBe("");
  });
});

describe("taxRateError", () => {
  it("accepts every slab GST levies", () => {
    for (const rate of GST_RATES) {
      expect(taxRateError(String(rate))).toBe("");
    }
  });

  it("accepts blank, which clears the rate on a multi-rate invoice", () => {
    expect(taxRateError("")).toBe("");
    expect(taxRateError(null)).toBe("");
  });

  it("mirrors the server's own 0-to-100 bound", () => {
    expect(taxRateError("-1")).toContain("negative");
    expect(taxRateError("101")).toContain("over 100");
    expect(taxRateError("abc")).toContain("must be a number");
  });

  it("rejects a run of digits long enough to overflow to Infinity", () => {
    // As in amountError: digits pass the shape check, Number() overflows, and
    // the isFinite guard answers ahead of the over-100 check.
    expect(taxRateError("9".repeat(400))).toBe("Tax rate must be a number.");
  });

  it("does not block a rate outside the slabs — that is a warning", () => {
    // The API takes anything from 0 to 100; /filing/validate is what calls a
    // non-slab rate an error. Refusing it here would stop someone recording
    // what the paper actually says.
    expect(taxRateError("15")).toBe("");
  });
});

describe("paidAtError", () => {
  const today = new Date(2026, 3, 20); // 20 April 2026, local time.

  it("accepts blank, which is what puts an invoice back on the 180-day clock", () => {
    expect(paidAtError("", { today })).toBe("");
    expect(paidAtError(null, { today })).toBe("");
  });

  it("accepts a payment on or before today", () => {
    expect(paidAtError("2026-04-20", { today })).toBe("");
    expect(paidAtError("2026-01-02", { today })).toBe("");
  });

  it("refuses a payment in the future", () => {
    // A future payment date takes an invoice off the Rule 37 reversal list it
    // belongs on, which is over-claimed credit with interest running on it.
    expect(paidAtError("2026-04-21", { today })).toContain("future");
  });

  it("refuses a payment before the invoice was issued", () => {
    const message = paidAtError("2026-01-01", {
      today,
      invoiceDate: "2026-04-01",
    });
    expect(message).toContain("2026-04-01");
    expect(message).toContain("cannot have been paid before");
  });

  it("says nothing about an invoice date it has not been given", () => {
    expect(paidAtError("2020-01-01", { today })).toBe("");
  });

  it("refuses a date that is not a date", () => {
    expect(paidAtError("2026-02-30", { today })).toContain("does not exist");
    expect(paidAtError("20/04/2026", { today })).toContain("YYYY-MM-DD");
  });
});

describe("invoiceDraftErrors with the ledger fields", () => {
  const today = new Date(2026, 3, 20);

  it("reports a bad place of supply and tax rate against their own fields", () => {
    const { errors } = invoiceDraftErrors(
      { place_of_supply: "ZZ", tax_rate: "150" },
      { today },
    );
    expect(errors.place_of_supply).toContain("two-digit state code");
    expect(errors.tax_rate).toContain("over 100");
  });

  it("checks the payment date against the invoice date the form will save", () => {
    // Not against the row as it stands: correcting a misread year is the
    // commonest reason anyone touches that field, and the server compares the
    // pair the PATCH lands.
    const { errors } = invoiceDraftErrors(
      { invoice_date: "2026-04-01", paid_at: "2026-03-01" },
      { today },
    );
    expect(errors.paid_at).toContain("cannot have been paid before");
  });

  it("warns about a rate the portal will reject without blocking the save", () => {
    const { errors, warnings } = invoiceDraftErrors({ tax_rate: "15" }, { today });
    expect(errors.tax_rate).toBeUndefined();
    expect(warnings.join(" ")).toContain("not a GST rate");
  });

  it("says nothing about a rate that is a real slab", () => {
    const { warnings } = invoiceDraftErrors({ tax_rate: "18" }, { today });
    expect(warnings.join(" ")).not.toContain("not a GST rate");
  });

  // Rule 46(b): letters, digits, hyphen and slash, up to sixteen characters.
  // The portal rejects the whole return over one offending line, so this is
  // worth saying at the box rather than in a filing report a month later.
  describe("an invoice number the portal will not take", () => {
    /** The identity fields alone: nothing here is about the money. */
    const numbered = (invoice_number) => ({
      counterparty_gstin: "27AAPFU0939F1ZV",
      invoice_number,
      invoice_date: "2026-04-15",
      hsn_code: "8471",
    });

    it("warns about a character Rule 46 forbids without blocking the save", () => {
      const { errors, warnings } = invoiceDraftErrors(
        numbered("INV#42"),
        { today, invoiceType: "sales" },
      );
      // Not an error: a business that issued the number that way still has to
      // be able to record what the paper says.
      expect(errors.invoice_number).toBeUndefined();
      expect(warnings.join(" ")).toContain("Rule 46(b)");
      expect(warnings.join(" ")).toContain("'#'");
    });

    it("names every character that has to go, once each", () => {
      const { warnings } = invoiceDraftErrors(
        numbered("IN V#4#2"),
        { today, invoiceType: "sales" },
      );
      const line = warnings.find((w) => w.includes("Rule 46(b)"));
      expect(line).toContain("' '");
      expect(line).toContain("'#'");
      expect(line.match(/'#'/g)).toHaveLength(1);
    });

    it("leaves a supplier's own serial alone", () => {
      // It is what GSTR-2B carries too, so it reconciles either way — and the
      // buyer has no authority to renumber someone else's invoice.
      const { warnings } = invoiceDraftErrors(
        numbered("INV#42"),
        { today, invoiceType: "purchase" },
      );
      expect(warnings.join(" ")).not.toContain("Rule 46(b)");
    });

    it("says nothing about a number that is only hyphens and slashes", () => {
      const { warnings } = invoiceDraftErrors(
        numbered("INV/2026-0042"),
        { today, invoiceType: "sales" },
      );
      expect(warnings).toEqual([]);
    });

    it("warns past sixteen characters whichever way the invoice runs", () => {
      // The cap is the portal's, and a purchase longer than it is a number
      // the supplier cannot have filed — so it is the books that are wrong.
      for (const invoiceType of ["sales", "purchase"]) {
        const { warnings } = invoiceDraftErrors(
          numbered("INV-2026-000000042"),
          { today, invoiceType },
        );
        expect(warnings.join(" ")).toContain("16 characters");
      }
    });
  });
});


describe("normalizeGstin with what copying brings along", () => {
  // Mirrors app/services/gstin.normalize: the same paste must be the same
  // GSTIN on both sides, or the form accepts what the API refuses.
  const VALID = "27AAPFU0939F1ZV";
  const fullWidth = [...VALID].map((c) => String.fromCharCode(c.charCodeAt(0) + 0xfee0)).join("");
  it.each([
    ["zero-width space", VALID + "\u200b"],
    ["byte-order mark", "\ufeff" + VALID],
    ["soft hyphen", "27\u00adAAPFU0939F1ZV"],
    ["en dash", "27\u2013AAPFU0939F1ZV"],
    ["non-breaking hyphen", "27\u2011AAPFU0939F1ZV"],
    ["minus sign", "27\u2212AAPFU0939F1ZV"],
    ["full-width forms", fullWidth],
  ])("strips a %s", (_label, pasted) => {
    expect(normalizeGstin(pasted)).toBe(VALID);
    expect(gstinShapeError(pasted)).toBe("");
  });

  it("never drops a real character", () => {
    expect(normalizeGstin("27AAPFU0939F1ZVX")).toBe("27AAPFU0939F1ZVX");
  });
});


describe("GST_RATES", () => {
  // It said it mirrored the backend's VALID_TAX_RATES and had stopped at 28:
  // GST 2.0's 40% slab (from 22 September 2025) was missing, so a reviewer
  // correcting a 40% invoice was told "40% is not a GST rate … the portal
  // rejects anything else" — a nudge to change a right rate to a wrong one.
  it("matches the backend's slabs, which /filing/validate holds a return to", () => {
    const src = readFileSync(
      resolve(__dirname, "../../../backend/app/services/invoice_parser.py"),
      "utf8",
    );
    const body = src.slice(src.indexOf("VALID_TAX_RATES = ("));
    const backend = [...body.slice(0, body.indexOf("\n)")).matchAll(/Decimal\("([\d.]+)"\)/g)]
      .map((m) => Number(m[1]));
    expect(backend.length).toBeGreaterThan(10);
    expect([...GST_RATES].sort((a, b) => a - b)).toEqual(backend.sort((a, b) => a - b));
  });

  it("does not warn about a 40% invoice", () => {
    const { warnings } = invoiceDraftErrors({
      taxable_value: "1000", igst: "400", total_value: "1400", tax_rate: "40",
    });
    expect(warnings.join(" ")).not.toMatch(/not a GST rate/);
  });
});
