/**
 * Previous / "from–to of total" / Next, for a list the API serves a page at a
 * time. Renders nothing when everything fits on one page.
 *
 * The suppliers and alerts lists had none: each showed the API's first page
 * and a heading counting the whole list, so everything past fifty was there
 * by count and nowhere to be seen.
 */
export default function Pager({ offset, total, pageSize, onPage }) {
  if (total <= pageSize && offset === 0) return null;
  return (
    <div className="pager">
      <button
        type="button"
        className="btn btn-ghost"
        disabled={offset === 0}
        onClick={() => onPage(Math.max(0, offset - pageSize))}
      >
        Previous
      </button>
      {/* Paging replaces the table in place, so this is the feedback. */}
      <span className="muted" role="status">
        {offset + 1}–{Math.min(offset + pageSize, total)} of {total}
      </span>
      <button
        type="button"
        className="btn btn-ghost"
        disabled={offset + pageSize >= total}
        onClick={() => onPage(offset + pageSize)}
      >
        Next
      </button>
    </div>
  );
}
