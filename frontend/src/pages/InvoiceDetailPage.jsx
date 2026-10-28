import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import ReadOnlyNotice from "../components/ReadOnlyNotice";
import { SkeletonPanel } from "../components/Skeleton";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { useStateCodes } from "../hooks/useStateCodes";
import { api, isAbortError } from "../lib/api";
import { dateLabel, rupees, statusLabel, statusTone } from "../lib/format";
import { invoiceDraftErrors, normalizePlaceOfSupply } from "../lib/validate";

// What the extractor read off the document, and what a reviewer corrects when
// it read it wrong.
//
// `place_of_supply` and `tax_rate` are here rather than left to the extraction
// because both are printed on the paper and both decide a figure on the return.
// Place of supply settles IGST against CGST+SGST and is copied verbatim into
// `pos` on every GSTR-1 line — and when it is missing and no GSTIN can supply
// it, `/filing/validate` blocks the period with an error that nothing on this
// screen could fix. Tax rate is what the portal cross-checks the tax against.
const EDITABLE = [
  { field: "counterparty_gstin", label: "Counterparty GSTIN" },
  { field: "counterparty_name", label: "Counterparty name" },
  { field: "invoice_number", label: "Invoice number" },
  { field: "invoice_date", label: "Invoice date", type: "date" },
  { field: "place_of_supply", label: "Place of supply", hint: "Two-digit state code" },
  { field: "hsn_code", label: "HSN/SAC" },
  { field: "tax_rate", label: "Tax rate %", type: "number", step: "0.01" },
  { field: "taxable_value", label: "Taxable value", type: "number" },
  { field: "cgst", label: "CGST", type: "number" },
  { field: "sgst", label: "SGST", type: "number" },
  { field: "igst", label: "IGST", type: "number" },
  { field: "cess", label: "Cess", type: "number" },
  { field: "total_value", label: "Total value", type: "number" },
];

// Facts about the invoice that are not readings off it, and that no extraction
// can supply: whether the supplier has been paid, whether the purchase was
// capital goods, whether the credit is claimable at all, whether the buyer owes
// the tax. The API has always taken all four; nothing in the app could send
// them, which quietly broke the two reversal rules the ITC screen is built on.
//
// `paid_at` is the expensive one. Rule 37 reverses the whole of an invoice's
// credit once it is 180 days unpaid, and with no way to record a payment every
// purchase stayed unpaid for ever — so a business six months into using DoAide GST
// had credit reversed on invoices it had settled on time, in a GSTR-3B it then
// filed. `is_capital_good` fails the other way: left false, a machine's credit
// is claimed whole in the month of purchase instead of over Rule 43's sixty
// months, which is over-claimed credit.
//
// Kept in their own group because the server keeps them in one: correcting an
// extracted field marks the invoice reviewed, and recording a payment does not.
const LEDGER_FLAGS = [
  {
    field: "paid_at",
    label: "Supplier paid on",
    type: "date",
    hint: "Blank means unpaid. Rule 37 reverses the credit 180 days after the invoice date.",
  },
  {
    field: "is_capital_good",
    label: "Capital goods",
    type: "checkbox",
    hint: "Credit is spread over 60 months under Rule 43 instead of claimed this month.",
  },
  {
    field: "itc_eligible",
    label: "Credit is claimable",
    type: "checkbox",
    hint: "Clear this for exempt or nil-rated purchases, and for credit blocked by s.17(5) — a car, staff catering, a club membership.",
  },
  {
    field: "reverse_charge",
    label: "Reverse charge",
    type: "checkbox",
    hint: "The supplier charged no tax and you owe it directly. Declared in GSTR-3B 3.1(d) and payable in cash.",
  },
];

const BOOLEAN_FIELDS = new Set(
  LEDGER_FLAGS.filter((f) => f.type === "checkbox").map((f) => f.field),
);

/** Every field the form owns, extracted and ledger alike. */
const ALL_FIELDS = [...EDITABLE, ...LEDGER_FLAGS];

/**
 * One row of the edit form.
 *
 * The error sits outside the `<label>`, and the label is tied to the input by
 * htmlFor rather than by wrapping it. Nesting the message inside the label
 * would fold it into the input's accessible name — the field would announce as
 * "CGST CGST cannot be negative", and then the same text again from
 * aria-describedby.
 *
 * A checkbox reverses that: its label belongs *after* the box, and its value is
 * `checked` rather than `value`. Handing a boolean to `value` would put the
 * string "true" in the box and leave the tick permanently off.
 *
 * A spec carrying `options` is a closed list and renders as a `<select>`. It
 * carries a `normalize` with them, because the value stored on the invoice is
 * not always spelt the way an option is — `7` and `07` are the same place of
 * supply — and a `<select>` whose value matches no option renders blank, which
 * reads as the invoice not having one. It runs on the way *out* only: the draft
 * keeps what the server sent, so a field nobody touched is not re-sent as an
 * edit for having been reformatted on screen.
 */
function Field({ spec, draft, message, setDraft, setTouched }) {
  const { field, label, type, hint, step, options, normalize } = spec;
  const described = [message ? `${field}-error` : null, hint ? `${field}-hint` : null]
    .filter(Boolean)
    .join(" ");
  const isCheckbox = type === "checkbox";
  const shared = {
    id: field,
    "aria-invalid": message ? true : undefined,
    // Points at the message so a screen reader reads the reason with the
    // field rather than leaving it as unattached text.
    "aria-describedby": described || undefined,
    onBlur: () => setTouched((prev) => ({ ...prev, [field]: true })),
  };
  return (
    <div
      className={`field${message ? " is-invalid" : ""}${isCheckbox ? " field-check" : ""}`}
    >
      {!isCheckbox && <label htmlFor={field}>{label}</label>}
      {options ? (
        <select
          {...shared}
          value={normalize(draft[field])}
          onChange={(e) => setDraft((prev) => ({ ...prev, [field]: e.target.value }))}
        >
          {options.map(([value, text]) => (
            <option key={value} value={value}>
              {text}
            </option>
          ))}
        </select>
      ) : (
        <input
          {...shared}
          type={type ?? "text"}
          step={step ?? (type === "number" ? "0.01" : undefined)}
          {...(isCheckbox
            ? {
                checked: Boolean(draft[field]),
                onChange: (e) =>
                  setDraft((prev) => ({ ...prev, [field]: e.target.checked })),
              }
            : {
                // The `??` never fires and is not worth a test to prove it
                // does: `adopt` builds the draft over ALL_FIELDS and coerces
                // each one through `?? ""` already, and the only other write
                // to it — the reset to `{}` on an id change — clears `invoice`
                // in the same breath, which returns above before any Field
                // renders. It stays because the alternative to a redundant
                // guard here is React silently switching this input to
                // uncontrolled, which loses the edit rather than announcing
                // itself.
                value: draft[field] ?? "",
                onChange: (e) => setDraft((prev) => ({ ...prev, [field]: e.target.value })),
              })}
        />
      )}
      {isCheckbox && <label htmlFor={field}>{label}</label>}
      {hint && (
        <span className="muted small" id={`${field}-hint`}>
          {hint}
        </span>
      )}
      {message && (
        <span className="field-error" id={`${field}-error`} role="alert">
          {message}
        </span>
      )}
    </div>
  );
}

export default function InvoiceDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { canWrite } = useAuth();

  const [invoice, setInvoice] = useState(null);
  const [draft, setDraft] = useState({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  // Which fields have been left, so a half-typed GSTIN is not marked wrong on
  // the third keystroke. A submit attempt marks everything touched.
  const [touched, setTouched] = useState({});
  // The invoice the page is showing, readable from a callback that has been
  // waiting on the network. `id` closed over when a write went out is the
  // invoice it was *for*, which is the one thing an in-flight write must not
  // assume the URL still names.
  const shownId = useRef(id);

  // The direction is not on the form — it is not a field anyone corrects —
  // but one warning turns on it: Rule 46(b) governs the numbers this business
  // issues, not the ones its suppliers do.
  const { errors, warnings } = invoiceDraftErrors(draft, {
    invoiceType: invoice?.invoice_type,
  });
  const hasErrors = Object.keys(errors).length > 0;

  // Place of supply is a code out of a list the server owns, and typing it blind
  // is how the wrong state ends up deciding IGST against CGST+SGST — 06 and 09
  // are both plausible things to read off a Delhi invoice, and neither is Delhi.
  // With the list to hand the field becomes a picker; without it, it stays the
  // text box it has always been. `useStateCodes` answers null for every reason
  // the list can be missing, so the fallback is one branch rather than a
  // dropdown that is empty while a request is in flight.
  const stateCodes = useStateCodes();
  const placeOfSupply = normalizePlaceOfSupply(draft.place_of_supply);
  const stateOptions = useMemo(() => {
    if (!stateCodes) return null;
    // Ordered by code rather than by name. The code is what is printed on the
    // invoice, what the first two digits of the counterparty's GSTIN spell, and
    // what a reviewer is cross-checking one against the other — so the list is
    // ordered the way the thing being looked up is. Sorting is not cosmetic:
    // "27" is an array-index-shaped key and "07" is not, so the object hands
    // back Maharashtra before Delhi whatever order the server sent.
    const options = Object.keys(stateCodes)
      .sort()
      .map((code) => [code, `${code} — ${stateCodes[code]}`]);
    // Blank is a real answer here: the API accepts an invoice without a place of
    // supply, and `/filing/validate` is what refuses one at the period.
    options.unshift(["", "Not stated"]);
    // A code the server does not know still has to be selectable, or opening an
    // invoice would silently swap the picker to blank and the next save would
    // write that blank over a value nobody looked at. The API refuses an
    // unknown code on the way in, so this is a row that predates that check
    // rather than one anyone can create — and saying so on the row beats
    // finding out from a 422 on a field the user did not touch.
    if (placeOfSupply && !(placeOfSupply in stateCodes)) {
      options.push([placeOfSupply, `${placeOfSupply} — not a GST state code`]);
    }
    return options;
  }, [stateCodes, placeOfSupply]);

  // The hint goes with the text box: "two-digit state code" is instruction for
  // typing, and there is nothing to type once the codes are on screen.
  const editable = stateOptions
    ? EDITABLE.map((spec) =>
        spec.field === "place_of_supply"
          ? { ...spec, hint: undefined, options: stateOptions, normalize: normalizePlaceOfSupply }
          : spec,
      )
    : EDITABLE;

  // Named by invoice number once it arrives, so browser history and the tab
  // strip distinguish the four invoices someone has open while reconciling.
  // Until then the title is just "Invoice" rather than a number the user has
  // never seen — the row id in the URL is not one they would recognise.
  usePageTitle(invoice?.invoice_number ? `Invoice ${invoice.invoice_number}` : "Invoice");

  // The form is a working copy of the invoice, so every path that replaces the
  // invoice has to replace the copy with it. Only `load` used to, which made
  // re-extraction destructive: the panel showed the newly parsed fields while
  // the inputs still held the ones extraction had just replaced, and saving
  // from there wrote the stale copy back over them. Two ordinary clicks —
  // re-extract, then save — and the re-extraction was undone.
  //
  // Saving has a milder version of the same gap. The server settles what it
  // stores (money lands on the column's two decimal places, a date comes back
  // in the API's format), so a draft left as typed disagrees with the invoice
  // beside it, is re-sent as a change on the next save, and reports
  // "Corrections saved" for an edit nobody made.
  const adopt = useCallback((data) => {
    setInvoice(data);
    setDraft(
      Object.fromEntries(
        ALL_FIELDS.map(({ field }) => [
          field,
          // A checkbox is a boolean both ways. Coerced through "" like the text
          // fields it would come back as the string "false", which is truthy,
          // and every unticked flag would tick itself on the next render.
          BOOLEAN_FIELDS.has(field) ? Boolean(data[field]) : data[field] ?? "",
        ]),
      ),
    );
  }, []);

  const load = useCallback(async ({ signal } = {}) => {
    setError("");
    try {
      adopt(await api.getInvoice(id, { signal }));
    } catch (err) {
      // A superseded request describes an invoice this page has already moved
      // off. Its answer must not be adopted, and its rejection is this app
      // cancelling itself rather than anything to tell the user about.
      if (isAbortError(err)) return;
      setError(err.message);
    }
  }, [id, adopt]);

  // The id in the URL is the only thing naming which invoice this is, and
  // React Router keeps one component instance across a change to it. So the
  // next invoice does not arrive on a fresh page — it arrives on the previous
  // invoice's, and until it lands every control on that page writes to the new
  // id: `handleSave` diffs the form against the invoice beside it and PATCHes
  // the difference to `id`. Two clicks in the invoice list, one slow response,
  // and one invoice's GSTIN, dates and figures were saved onto another.
  //
  // Clearing first is what closes that: with no invoice there is no form and
  // no save button, so the page shows its loading placeholder until the
  // invoice the URL actually names has arrived. The abort handles the other
  // half — answers do not come back in the order they were sent, so without it
  // a slow 42 landing after 43 would put 42 back on 43's page.
  useEffect(() => {
    const controller = new AbortController();
    shownId.current = id;
    setInvoice(null);
    setDraft({});
    setTouched({});
    setNotice("");
    load({ signal: controller.signal });
    return () => controller.abort();
  }, [load, id]);

  async function handleSave(event) {
    event.preventDefault();
    const target = id;
    // Everything becomes touched on submit, so a field the user never entered
    // still shows why the save did not go through.
    setTouched(Object.fromEntries(ALL_FIELDS.map(({ field }) => [field, true])));
    if (hasErrors) {
      setNotice("");
      setError("Fix the highlighted fields before saving.");
      return;
    }

    setBusy(true);
    setError("");
    setNotice("");
    try {
      // Only changed fields are sent — the API leaves unmentioned fields
      // alone, so a blank one must not be transmitted as an empty string.
      //
      // A cleared text field is sent as null, which is how a misread GSTIN or
      // date is taken back off an invoice. A flag never is: `itc_eligible`,
      // `reverse_charge` and `is_capital_good` are NOT NULL columns with no
      // cleared state, and the schema refuses an explicit null on them, so an
      // unticked box has to travel as `false`.
      const changes = {};
      for (const { field } of ALL_FIELDS) {
        const next = draft[field];
        if (BOOLEAN_FIELDS.has(field)) {
          if (Boolean(next) !== Boolean(invoice[field])) changes[field] = Boolean(next);
          continue;
        }
        const current = invoice[field] ?? "";
        if (String(next) !== String(current)) changes[field] = next === "" ? null : next;
      }
      if (Object.keys(changes).length === 0) {
        setNotice("Nothing changed.");
        return;
      }
      const saved = await api.updateInvoice(target, changes);
      // Clearing the form on the way in stops one invoice's values being sent
      // to another's id. This is the other direction: the PATCH answers with
      // the invoice it wrote, and adopting it makes the form a working copy of
      // that invoice again — while the URL, and every control on the page,
      // name the one opened since. The next save would then PATCH the first
      // invoice's GSTIN, dates and figures onto the second.
      if (shownId.current !== target) return;
      adopt(saved);
      setNotice("Corrections saved.");
    } catch (err) {
      // A failure belongs to the invoice it was for. Left unguarded it banners
      // the page of an invoice that is loading, or has loaded, perfectly well.
      if (shownId.current !== target) return;
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleReparse() {
    // Re-extraction is a second model pass over the stored file, so it is the
    // slowest write this page makes and the one most likely to still be
    // running when the user moves on to the next invoice.
    const target = id;
    setBusy(true);
    setError("");
    try {
      const reparsed = await api.reparseInvoice(target);
      if (shownId.current !== target) return;
      adopt(reparsed);
      setNotice("Re-extracted from the stored file.");
    } catch (err) {
      if (shownId.current !== target) return;
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm("Remove this invoice from your books?")) return;
    // The invoice this delete is for, like the two writes above it. This is the
    // only one of the three that can move the user, which makes landing it on
    // the wrong invoice the worst of the three rather than the mildest.
    const target = id;
    // The one write on this page that never took the busy lock. Its button
    // stayed live for as long as its own request, so a second click sent a
    // second DELETE for an invoice already gone and banal double-clicking
    // produced "Invoice not found" over an invoice that had just been removed
    // successfully — a refusal describing nothing the user did wrong. It also
    // left Save and Re-extract clickable against a row mid-deletion, which is
    // the pair of requests that races to decide whether the invoice exists.
    setBusy(true);
    setError("");
    try {
      await api.deleteInvoice(target);
      // Not a redirect off whatever is on screen now. Leaving the detail page
      // is how a deleted invoice stops showing a form whose every save 404s —
      // it is about `target`, and it is only right while `target` is what the
      // page is showing. Someone who deleted one invoice, moved to the next and
      // started correcting it would otherwise be pulled to the list mid-edit,
      // by an answer to a click they made on a different invoice, losing
      // whatever they had typed.
      //
      // Nothing is said in its place. The delete has been applied server-side
      // and the list will show it gone; a notice about `target` on the invoice
      // opened since is the same misattribution one line down.
      if (shownId.current !== target) return;
      navigate("/invoices");
    } catch (err) {
      // A refusal belongs to the invoice it was for. "Invoice is part of a
      // filed return" banners over the invoice opened since, which reads as
      // that invoice being the one that cannot be removed.
      if (shownId.current !== target) return;
      setError(err.message);
    } finally {
      // Unconditional, like the two writes above. On the path that navigates
      // the page is gone and this lands on nothing; on every other path the
      // buttons have to come back, including the one where the user moved to
      // another invoice while the delete was in flight.
      setBusy(false);
    }
  }

  if (!invoice) {
    return (
      <div className="page">
        <ErrorBanner message={error} />
        {!error && <SkeletonPanel lines={6} label="Loading invoice" />}
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{invoice.invoice_number || `Invoice #${invoice.id}`}</h1>
          <p className="muted">
            <span className={`chip chip-${statusTone(invoice.status)}`}>
              {statusLabel(invoice.status)}
            </span>{" "}
            · {invoice.invoice_type} · {dateLabel(invoice.invoice_date)}
          </p>
        </div>
        {canWrite && (
          <div className="page-actions">
            <button type="button" className="btn btn-ghost" onClick={handleReparse} disabled={busy}>
              Re-extract
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={handleDelete}
              disabled={busy}
            >
              {/* Keeps its label while busy, the way Re-extract beside it
                  does. `busy` is one lock over all three writes, so a button
                  that renamed itself to "Deleting…" would say so during a
                  save the user started from the form below. */}
              Delete
            </button>
          </div>
        )}
      </div>

      <ErrorBanner message={error} onDismiss={() => setError("")} />
      {/* The page keeps its whole read-only half — an invoice a viewer cannot
          correct is still one they are here to look at — so the notice is what
          explains the missing Re-extract, Delete and Save rather than the page
          reading as broken. */}
      <ReadOnlyNotice>
        Ask an owner or an accountant to correct or delete this invoice.
      </ReadOnlyNotice>
      {notice && (
        <div className="banner banner-good" role="status">
          {notice}
        </div>
      )}

      {invoice.parse_error && (
        <section className="banner banner-error" role="alert">
          <div>
            <strong>Extraction failed:</strong> {invoice.parse_error}
          </div>
          {canWrite && (
            <button type="button" className="btn btn-ghost" onClick={handleReparse} disabled={busy}>
              Try re-extracting
            </button>
          )}
        </section>
      )}

      {invoice.warnings?.length > 0 && (
        <section className="panel panel-warn">
          <h2>Needs attention</h2>
          <ul>
            {invoice.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel">
        <h2>Extracted fields</h2>
        <p className="muted small">
          Read by {invoice.parsed_with ?? "unknown"}
          {invoice.extraction_confidence != null &&
            ` · confidence ${(invoice.extraction_confidence * 100).toFixed(0)}%`}
          . Your edits override the extraction.
        </p>

        {warnings.length > 0 && (
          <div className="banner banner-warn" role="status">
            <p className="small">
              These look wrong, but they will save — check them against the paper first.
            </p>
            <ul>
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        )}

        {/* One `disabled` on a wrapping fieldset rather than a flag threaded
            through every Field: the inputs stay in the DOM and keep showing
            what the extractor read, which is what a viewer came for, and the
            browser refuses focus and typing on all of them at once. Nothing
            here relies on it — the Save button is gone and the route is
            gated — but a field that looks editable and silently discards what
            is typed into it is worse than one that never invited the typing. */}
        <form onSubmit={handleSave} noValidate>
          <fieldset className="fieldset-bare" disabled={!canWrite}>
            <div className="edit-grid">
              {editable.map((spec) => (
                <Field
                  key={spec.field}
                  spec={spec}
                  draft={draft}
                  message={touched[spec.field] ? errors[spec.field] : ""}
                  setDraft={setDraft}
                  setTouched={setTouched}
                />
              ))}
            </div>

            <fieldset className="edit-fieldset">
              <legend>Your books</legend>
              <p className="muted small">
                Not on the paper, and nothing can read them off it — but they decide what
                this invoice’s credit is worth. Recording one does not mark the extraction
                reviewed.
              </p>
              <div className="edit-grid">
                {LEDGER_FLAGS.map((spec) => (
                  <Field
                    key={spec.field}
                    spec={spec}
                    draft={draft}
                    message={touched[spec.field] ? errors[spec.field] : ""}
                    setDraft={setDraft}
                    setTouched={setTouched}
                  />
                ))}
              </div>
          </fieldset>

          {canWrite && (
            <div className="edit-actions">
              {/* Not disabled on invalid input. A disabled button gives no
                  reason it is disabled; letting the submit through is what
                  surfaces the per-field messages and the banner. */}
              {/* "Working…", not "Saving…". `busy` is one lock over all three
                  writes on this page, so the specific label was already a lie
                  during a re-extract and would be a worse one during a delete
                  — a button announcing a save over a row being removed. The
                  three other pages that share a lock this way say the same
                  thing for the same reason. */}
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? "Working…" : "Save corrections"}
              </button>
            </div>
          )}
          </fieldset>
        </form>
      </section>

      <section className="panel">
        <h2>Totals</h2>
        <dl className="kv">
          <div>
            <dt>Taxable value</dt>
            <dd>{rupees(invoice.taxable_value)}</dd>
          </div>
          <div>
            <dt>CGST</dt>
            <dd>{rupees(invoice.cgst)}</dd>
          </div>
          <div>
            <dt>SGST</dt>
            <dd>{rupees(invoice.sgst)}</dd>
          </div>
          <div>
            <dt>IGST</dt>
            <dd>{rupees(invoice.igst)}</dd>
          </div>
          <div>
            <dt>Total</dt>
            {/* What the return will declare this invoice at. The editable
                "Total value" field above stays the raw column, because that is
                what a reviewer corrects and what validation cross-foots — but
                the column is zero whenever the extractor found no grand-total
                label, and this panel is where someone checks the figures
                against the paper. */}
            <dd>{rupees(invoice.invoice_value)}</dd>
          </div>
        </dl>
      </section>

      <nav className="next-steps" aria-label="Next steps">
        <Link to="/invoices" className="btn btn-ghost">← All invoices</Link>
        {invoice.invoice_type === "purchase" && (
          <Link to="/reconcile" className="btn btn-ghost">Reconcile with GSTR-2B</Link>
        )}
        {invoice.invoice_type === "sales" && (
          <Link to="/filing" className="btn btn-ghost">Prepare GSTR-1</Link>
        )}
      </nav>
    </div>
  );
}
