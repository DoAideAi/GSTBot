import { Link } from "react-router-dom";
import TableScroll from "./TableScroll";

/**
 * One problem the validator found, as a row.
 *
 * The invoice number is a link wherever the server gave an id, because every
 * one of these is fixed by opening the invoice — a GSTIN retyped, a missing
 * number filled in. An issue raised against the period rather than a row (an
 * unreadable extraction, say) has no id and so no link.
 *
 * `field` arrives as the model attribute name. Underscores stripped is the
 * whole translation: "counterparty gstin" is what the column is about, and a
 * lookup table mapping each field to prose would be one more place to forget
 * to add a field.
 */
function IssueRow({ issue }) {
  return (
    <tr>
      <td>
        <span className={issue.severity === "error" ? "chip chip-bad" : "chip chip-warn"}>
          {issue.severity === "error" ? "Error" : "Warning"}
        </span>
      </td>
      <td>
        {issue.invoice_id ? (
          <Link to={`/invoices/${issue.invoice_id}`}>
            {issue.invoice_number || "(no number)"}
          </Link>
        ) : (
          issue.invoice_number || "(no number)"
        )}
      </td>
      <td>{issue.field.replace(/_/g, " ")}</td>
      <td>{issue.message}</td>
    </tr>
  );
}

/**
 * Everything a validation report found, in a table.
 *
 * Shared by the two screens that ask for one. They ask for opposite directions
 * — filing validates the sales side that becomes GSTR-1, reconciliation the
 * purchase side that has to match GSTR-2B — but the payload is the same shape
 * from the same endpoint, and rendering it twice is how the two drift into
 * disagreeing about what an error looks like.
 *
 * The caller supplies the label, since it names the region a keyboard lands on
 * and "Validation issues" on both would be two identically named stops.
 */
export default function ValidationIssues({ issues, label }) {
  return (
    <TableScroll label={label}>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Severity</th>
            <th scope="col">Invoice</th>
            <th scope="col">Field</th>
            <th scope="col">Problem</th>
          </tr>
        </thead>
        <tbody>
          {(issues ?? []).map((issue, index) => (
            <IssueRow
              key={`${issue.invoice_id ?? "x"}-${issue.field}-${index}`}
              issue={issue}
            />
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
