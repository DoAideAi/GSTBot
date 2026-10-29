import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ErrorBanner from "../components/ErrorBanner";
import { stepBackOffset } from "../components/Pager";
import { SkeletonTable } from "../components/Skeleton";
import TableScroll from "../components/TableScroll";
import { useAuth } from "../hooks/useAuth";
import { usePageTitle } from "../hooks/usePageTitle";
import { api, isAbortError } from "../lib/api";
import { dateLabel, rupees, statusLabel, statusTone } from "../lib/format";

const PAGE_SIZE = 25;

// One entry per sortable column. `asc`/`desc` are the values the API takes;
// `first` is which of the two a first click lands on — descending for a
// figure someone scans top-down for the largest or the latest, ascending for
// a number read as a sequence.
const SORTS = {
  number: { asc: "number_asc", desc: "number_desc", first: "asc" },
  date: { asc: "date_asc", desc: "date_desc", first: "desc" },
  value: { asc: "value_asc", desc: "value_desc", first: "desc" },
};

/** A `<th>` that sorts its column on click, and says so to assistive tech. */
function SortHeader({ column, sort, onSort, children }) {
  const spec = SORTS[column];
  const direction = sort === spec.asc ? "ascending" : sort === spec.desc ? "descending" : "none";
  return (
    <th scope="col" aria-sort={direction}>
      <button type="button" className="th-sort" onClick={() => onSort(column)}>
        {children}
        {direction !== "none" && (
          <span aria-hidden="true">{direction === "ascending" ? " ▲" : " ▼"}</span>
        )}
      </button>
    </th>
  );
}

export default function InvoicesPage() {
  usePageTitle("Invoices");
  const { canWrite } = useAuth();
  const [filters, setFilters] = useState({ invoice_type: "", status: "", search: "" });
  const [sort, setSort] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // Whether the table on screen failed to load, as opposed to loading and
  // coming back empty. Both leave `data` null, and the two empty states below
  // are findings about the books rather than captions on the banner.
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async ({ signal } = {}) => {
    setLoading(true);
    setError("");
    try {
      const page = await api.listInvoices(
        { ...filters, sort, limit: PAGE_SIZE, offset },
        { signal },
      );
      // A page past the end, because invoices left the list since the pager
      // was drawn: back to the last page there is, never "No invoices yet".
      const back = stepBackOffset(page, offset, PAGE_SIZE);
      if (back !== null) {
        setOffset(back);
        return;
      }
      setData(page);
      setLoadFailed(false);
    } catch (err) {
      // A superseded request has already been replaced by a newer one, which
      // owns the table, the banner and the spinner from here on. Returning
      // before `finally` would skip the reset, so the check is repeated there.
      if (isAbortError(err)) return;
      setError(err.message);
      // The rows on screen were fetched under the previous filters and page,
      // and no answer is coming to replace them — so they are left asserting a
      // filter they were never tested against, under a pager saying how many
      // invoices matched it. That is the out-of-order fault the abort guard
      // above exists to stop, reached by the other road.
      setData(null);
      setLoadFailed(true);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [filters, sort, offset]);

  // Every keystroke in the search box is a new request, and responses do not
  // come back in the order they were sent. Left unguarded, the answer for
  // "ACM" landing after the answer for "ACME" left the table showing rows the
  // search box no longer described — and, because each request cleared the
  // banner and the spinner on its own, an error from a superseded request
  // could sit over results that had since succeeded.
  //
  // Aborting the previous request on the way out of the effect fixes both: the
  // superseded response never arrives, so it cannot be applied out of order,
  // and the connection is released rather than spending a slot in the read
  // limit that a fast typist would otherwise exhaust mid-word.
  useEffect(() => {
    const controller = new AbortController();
    load({ signal: controller.signal });
    return () => controller.abort();
  }, [load]);

  function updateFilter(field, value) {
    setOffset(0); // A new filter means a new result set, so page 1.
    setFilters((prev) => ({ ...prev, [field]: value }));
  }

  // A first click on a column sorts by it, in whichever direction is the more
  // useful default for that column; a second click on the same column reverses
  // it; a click on a different column starts that one over at its own default
  // rather than carrying the previous column's direction.
  function toggleSort(column) {
    const spec = SORTS[column];
    setOffset(0);
    setSort((prev) => {
      if (prev === spec.asc) return spec.desc;
      if (prev === spec.desc) return spec.asc;
      return spec[spec.first];
    });
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  // Whether the list on screen is a filtered view of the books rather than the
  // books. An empty filtered view means the filters matched nothing; only an
  // empty unfiltered one means there is nothing here.
  const filtered = Object.values(filters).some((value) => value !== "");

  // A filter change refetches over a table that is already populated. Dimming
  // it says the rows on screen are the previous answer; swapping them for
  // placeholders on every keystroke in the search box would not.
  //
  // Scoped to the results rather than the page, unlike the dashboard, because
  // `.is-refreshing` carries `pointer-events: none` and the control driving
  // most of these refetches is a search box the user is still typing into.
  // Dimming the filters along with the rows would make the page fight back.
  const refreshing = loading && Boolean(data);

  return (
    <div className="page" aria-busy={refreshing}>
      <div className="page-head">
        <h1>Invoices</h1>
        {/* A call to action for a page whose only control a viewer does not
            have. The list itself is untouched — this is the invitation going,
            not the invoices. */}
        {canWrite && (
          <Link to="/upload" className="btn btn-primary">
            Upload
          </Link>
        )}
      </div>

      <ErrorBanner message={error} onDismiss={() => setError("")} />

      <div className="filters">
        <label>
          <span>Type</span>
          <select
            value={filters.invoice_type}
            onChange={(e) => updateFilter("invoice_type", e.target.value)}
          >
            <option value="">All</option>
            <option value="purchase">Purchase</option>
            <option value="sales">Sales</option>
          </select>
        </label>
        <label>
          <span>Status</span>
          <select value={filters.status} onChange={(e) => updateFilter("status", e.target.value)}>
            <option value="">All</option>
            <option value="parsed">Parsed</option>
            <option value="matched">Matched</option>
            <option value="mismatched">Mismatched</option>
            <option value="missing_in_2b">Missing in 2B</option>
            <option value="failed">Failed</option>
          </select>
        </label>
        <label className="filter-search">
          <span>Search</span>
          <input
            type="search"
            placeholder="Invoice number or party"
            value={filters.search}
            onChange={(e) => updateFilter("search", e.target.value)}
          />
        </label>
      </div>

      {loading && !data ? (
        <SkeletonTable rows={8} columns={7} label="Loading invoices" />
      ) : loadFailed ? (
        // Nothing, rather than either empty state below. Both are findings
        // about the books — that the filters matched nothing, or that there
        // are no invoices at all — and a load that failed establishes neither.
        // "No invoices yet", under a button offering to upload their first, is
        // the sentence the split below exists to keep off a filtered view; a
        // failed load was showing it to everyone, and on a book with five
        // hundred invoices it reads as the books having been lost.
        null
      ) : items.length === 0 && filtered ? (
        // Not "no invoices yet". A search for a supplier who has not been
        // booked, or a status nothing currently holds, is the ordinary way to
        // land here, and telling someone with five hundred invoices that they
        // have none — under a button offering to upload their first — reads as
        // the books having been lost. The filters are the reason and the way
        // out, so the message names them and clearing them is one click.
        <div className="empty">
          <p>No invoices match these filters.</p>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setOffset(0);
              setFilters({ invoice_type: "", status: "", search: "" });
            }}
          >
            Clear filters
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="empty">
          <p>No invoices yet.</p>
          {canWrite ? (
            <Link to="/upload" className="btn btn-primary">
              Upload your first invoice
            </Link>
          ) : (
            /* "Upload your first invoice" is the one sentence on this screen a
               viewer cannot act on, and an empty state that asks for something
               impossible is worse than one that says who to ask. */
            <p className="muted">
              An owner or an accountant can upload the first one.
            </p>
          )}
        </div>
      ) : (
        <div className={refreshing ? "results is-refreshing" : "results"}>
          <TableScroll label="Invoices">
            <table className="table table-invoices">
            <thead>
              <tr>
                <SortHeader column="number" sort={sort} onSort={toggleSort}>
                  Invoice
                </SortHeader>
                <th scope="col">Party</th>
                <SortHeader column="date" sort={sort} onSort={toggleSort}>
                  Date
                </SortHeader>
                <th scope="col">Taxable</th>
                <th scope="col">Tax</th>
                <SortHeader column="value" sort={sort} onSort={toggleSort}>
                  Total
                </SortHeader>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((invoice) => {
                const tax =
                  Number(invoice.cgst) +
                  Number(invoice.sgst) +
                  Number(invoice.igst) +
                  Number(invoice.cess);
                return (
                  <tr key={invoice.id}>
                    <td>
                      <Link to={`/invoices/${invoice.id}`}>
                        {invoice.invoice_number || `#${invoice.id}`}
                      </Link>
                      <span className="row-sub">{invoice.invoice_type}</span>
                    </td>
                    <td>
                      {invoice.counterparty_name || "—"}
                      <span className="row-sub">{invoice.counterparty_gstin || "No GSTIN"}</span>
                    </td>
                    <td>{dateLabel(invoice.invoice_date)}</td>
                    <td className="num">{rupees(invoice.taxable_value)}</td>
                    <td className="num">{rupees(tax)}</td>
                    {/* `invoice_value`, not the raw `total_value` column. The
                        column is only written when the extractor found a
                        grand-total *label*, so an invoice whose total was
                        printed as a bare "Total:" carries a stored zero with
                        every other figure on it right — and this register
                        listed a real supply at ₹0.00 while the GSTR-1 built
                        from it carried the full amount. The server derives the
                        one figure both use. */}
                    <td className="num">{rupees(invoice.invoice_value)}</td>
                    <td>
                      <span className={`chip chip-${statusTone(invoice.status)}`}>
                        {statusLabel(invoice.status)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            </table>
          </TableScroll>

          <div className="pager">
            <button
              type="button"
              className="btn btn-ghost"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </button>
            {/* Paging replaces the table in place, so without this the only
                feedback from pressing Next is that focus stayed on a button. */}
            <span className="muted" role="status">
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
            </span>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
