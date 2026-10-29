import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import UploadPage from "./UploadPage";

function jsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: async () => JSON.stringify(body),
  };
}

function invoiceResponse(overrides = {}) {
  return {
    queued: false,
    message: "Invoice processed",
    invoice: {
      id: 1,
      invoice_number: "INV-2026-0042",
      counterparty_gstin: "29AAGCB7383J1Z4",
      invoice_date: "2026-04-15",
      total_value: "531000.00",
      // What the API derives and every screen prints: the stored total where
      // there is one, taxable value plus tax where the extractor found no
      // grand-total label to write it from.
      invoice_value: "531000.00",
      warnings: [],
      ...overrides,
    },
  };
}

/**
 * The batch endpoint's shape: one outcome per file, whatever happened to it.
 *
 * `accepted` is the field the page switches on, so a rejected file carries an
 * `error` and no invoice — a bad page in a folder of fifty costs that page
 * alone, which is the whole reason the endpoint answers this way instead of
 * failing the request.
 */
function bulkResponse(items) {
  const list = items.map((item) =>
    item.accepted === false
      ? { filename: item.filename, accepted: false, error: item.error }
      : {
          filename: item.filename ?? "invoice.txt",
          accepted: true,
          queued: false,
          invoice: { ...invoiceResponse(item.invoice ?? {}).invoice },
        },
  );
  const accepted = list.filter((item) => item.accepted).length;
  return { total: list.length, accepted, rejected: list.length - accepted, items: list };
}

/** The commonest case: one file, accepted. */
function oneAccepted(overrides = {}, filename = "invoice.txt") {
  return bulkResponse([{ filename, invoice: overrides }]);
}

function file(name = "invoice.txt") {
  return new File(["invoice text"], name, { type: "text/plain" });
}

/** A File reporting a size without allocating the bytes for it. */
function sizedFile(name, bytes) {
  const made = file(name);
  Object.defineProperty(made, "size", { value: bytes });
  return made;
}

function renderPage({ role } = {}) {
  return render(
    <MemoryRouter>
      <StubAuth role={role}>
        <UploadPage />
      </StubAuth>
    </MemoryRouter>,
  );
}

describe("UploadPage", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });

  afterEach(() => vi.restoreAllMocks());

  it("uploads a file and shows what was extracted", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(jsonResponse(oneAccepted()));

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), file());

    expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
    expect(screen.getByText(/₹5,31,000.00/)).toBeInTheDocument();
  });

  it("defaults to a purchase, since that is what ITC is claimed on", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(jsonResponse(oneAccepted()));

    renderPage();
    expect(screen.getByLabelText("Purchase (claim ITC)")).toBeChecked();

    await user.upload(screen.getByLabelText("Choose files"), file());
    await waitFor(() => {
      expect(global.fetch.mock.calls[0][1].body.get("invoice_type")).toBe("purchase");
    });
  });

  it("sends the chosen type when uploading a sales invoice", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(jsonResponse(oneAccepted()));

    renderPage();
    await user.click(screen.getByLabelText("Sales (feeds GSTR-1)"));
    await user.upload(screen.getByLabelText("Choose files"), file());

    await waitFor(() => {
      expect(global.fetch.mock.calls[0][1].body.get("invoice_type")).toBe("sales");
    });
  });

  it("shows extraction warnings rather than hiding them", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse(oneAccepted({ warnings: ["No valid supplier GSTIN found"] })),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), file());

    // A flagged invoice can be corrected; a silently-accepted bad one is
    // filed wrong.
    expect(await screen.findByText("No valid supplier GSTIN found")).toBeInTheDocument();
  });

  it("still gives a scan the parser read nothing off a row worth clicking", async () => {
    // The commonest bad-but-not-failed outcome: a photographed invoice the
    // model could not get a number, a GSTIN or a date out of. It is stored,
    // it is claimable once corrected, and the row has to say which file it
    // was and offer the way in — an empty row reads as a dropped upload, and
    // the fix for a dropped upload is to drop it again, which duplicates it.
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse(
        bulkResponse([
          {
            filename: "photo.txt",
            invoice: { id: 12, invoice_value: "0.00", invoice_number: undefined,
              counterparty_gstin: undefined, invoice_date: undefined },
          },
        ]),
      ),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), file("photo.txt"));

    expect(await screen.findByText("photo.txt")).toBeInTheDocument();
    expect(screen.getByText(/No number found/)).toBeInTheDocument();
    // No stray separators for the fields that are not there.
    expect(screen.getByText(/No number found/).textContent).toBe("No number found · ₹0.00");
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute(
      "href",
      "/invoices/12",
    );
  });

  it("reports a per-file failure without losing the batch", async () => {
    const user = userEvent.setup();
    // One bad page in a folder of fifty costs that page alone. The server says
    // so per file, which is why the batch endpoint answers 200 with outcomes
    // rather than failing the request.
    global.fetch.mockResolvedValueOnce(
      jsonResponse(
        bulkResponse([
          {
            filename: "a.txt",
            accepted: false,
            error: "This file was already uploaded as invoice 3",
          },
          { filename: "b.txt", invoice: { invoice_number: "INV-2" } },
        ]),
      ),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), [file("a.txt"), file("b.txt")]);

    expect(await screen.findByText(/already uploaded as invoice 3/)).toBeInTheDocument();
    expect(await screen.findByText("INV-2")).toBeInTheDocument();
  });

  it("sends a batch as one request rather than one request per file", async () => {
    // The per-minute upload ceiling counts requests. Ninety files sent one at a
    // time spent it partway through and refused their own tail — and the files
    // that met the refusal were the ones that would otherwise have gone through.
    const user = userEvent.setup();
    global.fetch.mockResolvedValue(
      jsonResponse(
        bulkResponse([{ filename: "a.txt" }, { filename: "b.txt" }, { filename: "c.txt" }]),
      ),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), [
      file("a.txt"),
      file("b.txt"),
      file("c.txt"),
    ]);

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    expect(global.fetch.mock.calls[0][1].body.getAll("files")).toHaveLength(3);
  });

  it("splits a drop too big for one request into batches", async () => {
    // Ten at a time, so the progress line has something to say more often than
    // once per fifty files.
    const user = userEvent.setup();
    global.fetch.mockResolvedValue(jsonResponse(bulkResponse([{ filename: "x.txt" }])));

    renderPage();
    const many = Array.from({ length: 23 }, (_, i) => file(`file-${i}.txt`));
    await user.upload(screen.getByLabelText("Choose files"), many);

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(3));
    expect(global.fetch.mock.calls[0][1].body.getAll("files")).toHaveLength(10);
    expect(global.fetch.mock.calls[2][1].body.getAll("files")).toHaveLength(3);
  });

  it("refuses an oversized file without asking the server", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.upload(screen.getByLabelText("Choose files"), sizedFile("scan.txt", 41 * 1024 * 1024));

    // The point of the client-side check: a 41 MB scan should be refused
    // before it is read off disk and pushed over a phone connection.
    expect(await screen.findByText(/over the 15 MB limit/)).toBeInTheDocument();
    expect(global.fetch.mock.calls.map((c) => c[0])).toEqual([]);
  });

  it("refuses a file type the parser cannot read", async () => {
    const { container } = renderPage();

    // Dropped rather than picked. The `accept` attribute already filters the
    // file dialog, so a .zip cannot arrive that way — but drag-and-drop
    // ignores `accept` entirely, which is exactly why the JS check is not
    // redundant with the attribute.
    fireEvent.drop(container.querySelector(".dropzone"), {
      dataTransfer: { files: [new File(["PK"], "scans.zip", { type: "application/zip" })] },
    });

    expect(await screen.findByText(/which cannot be read/)).toBeInTheDocument();
    expect(global.fetch.mock.calls.map((c) => c[0])).toEqual([]);
  });

  it("accepts a dropped file the parser can read", async () => {
    const { container } = renderPage();
    global.fetch.mockResolvedValueOnce(jsonResponse(oneAccepted()));

    fireEvent.drop(container.querySelector(".dropzone"), {
      dataTransfer: { files: [file("dropped.txt")] },
    });

    expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
  });

  it("refuses an empty file and suggests why it is empty", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.upload(screen.getByLabelText("Choose files"), sizedFile("invoice.txt", 0));

    // Zero bytes otherwise reaches the parser and comes back as "no fields
    // found", which reads like the extraction failed rather than the file.
    expect(await screen.findByText(/still be downloading/)).toBeInTheDocument();
    expect(global.fetch.mock.calls.map((c) => c[0])).toEqual([]);
  });

  it("uploads the good files in a batch and reports the rejected one", async () => {
    const user = userEvent.setup();
    window.umami = { track: vi.fn() };
    global.fetch.mockResolvedValue(jsonResponse(oneAccepted()));

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), [
      file("good.txt"),
      sizedFile("huge.txt", 41 * 1024 * 1024),
      file("also-good.txt"),
    ]);

    // Dropping the bad file silently is how a 40-file batch quietly becomes 38.
    expect(await screen.findByText(/over the 15 MB limit/)).toBeInTheDocument();
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    // The oversized one is refused here and never reaches the request.
    expect(global.fetch.mock.calls[0][1].body.getAll("files")).toHaveLength(2);
    // Usage is counted by files, never by their names.
    expect(window.umami.track).toHaveBeenCalledWith("invoice_upload", {
      invoice_type: "purchase",
      files: 2,
      accepted: 1,
    });
    expect(JSON.stringify(window.umami.track.mock.calls)).not.toContain("good.txt");
    delete window.umami;
  });

  it("says how far through the drop it is", async () => {
    const user = userEvent.setup();
    let release;
    global.fetch.mockReturnValueOnce(new Promise((resolve) => {
      release = () => resolve(jsonResponse(bulkResponse([{ filename: "first.txt" }])));
    }));

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), [file("first.txt"), file("second.txt")]);

    // A range rather than a filename: several files are in flight at once, and
    // naming one of them would be picking one at random and calling it the
    // slow one.
    expect(await screen.findByText(/Extracting 1–2 of 2/)).toBeInTheDocument();
    release();
  });

  it("counts a single file as one, not as a range from itself to itself", async () => {
    const user = userEvent.setup();
    let release;
    global.fetch.mockReturnValueOnce(new Promise((resolve) => {
      release = () => resolve(jsonResponse(oneAccepted()));
    }));

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), file("only.txt"));

    expect(await screen.findByText(/Extracting 1 of 1/)).toBeInTheDocument();
    release();
  });

  it("takes an accepted invoice that came back with no warnings list at all", async () => {
    // `warnings` is the field the row's whole appearance keys off — an empty
    // list is the clean case and prints a tick. Absent is not the same thing,
    // and reading `.length` off it directly is a page that blanks on an
    // upload the server actually accepted.
    const user = userEvent.setup();
    const { warnings: _dropped, ...rest } = invoiceResponse().invoice;
    global.fetch.mockResolvedValueOnce(
      jsonResponse({
        total: 1,
        accepted: 1,
        rejected: 0,
        items: [{ filename: "invoice.txt", accepted: true, queued: false, invoice: rest }],
      }),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), file());

    expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
  });

  it("keeps the rows already on screen when a batch answers with no outcomes", async () => {
    // A 200 with no `items` is a truncated answer, not an empty one. Mapping
    // over it directly throws inside the loop, which is caught as a *request*
    // failure and relabels files the server may well have taken — so the safe
    // reading is that this batch reported nothing, and the earlier rows stand.
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(jsonResponse(oneAccepted({}, "first.txt")));
    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), file("first.txt"));
    expect(await screen.findByText("first.txt")).toBeInTheDocument();

    global.fetch.mockResolvedValueOnce(jsonResponse({ total: 1, accepted: 0, rejected: 0 }));
    await user.upload(screen.getByLabelText("Choose files"), file("second.txt"));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    // The first upload's row is still there, and nothing was invented for the
    // second — in particular it is not listed as having failed.
    expect(screen.getByText("first.txt")).toBeInTheDocument();
    expect(screen.queryByText("second.txt")).not.toBeInTheDocument();
  });

  it("never puts up a spinner that cannot say how far through the drop it is", async () => {
    // The line and the spinner used to be two pieces of state — a `busy` flag
    // and a `progress` object — set and cleared together on the same line
    // every time. Together they could spell "extracting, position unknown",
    // which the upload loop cannot produce, so the page carried a caption no
    // run of it could ever reach. It is one piece of state now; this drives a
    // batch across a chunk boundary, where the counter is rewritten mid-flight
    // and a re-introduced second flag would fall out of step.
    const user = userEvent.setup();
    const seen = [];
    const observer = new MutationObserver(() => {
      const line = document.querySelector(".upload-progress");
      if (line) seen.push(line.textContent);
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    // Both requests are held, so the line can be read while each is in flight
    // rather than after the batch has taken it down again.
    let releaseFirst;
    let releaseSecond;
    global.fetch
      .mockReturnValueOnce(
        new Promise((resolve) => {
          releaseFirst = () =>
            resolve(jsonResponse(bulkResponse(Array.from({ length: 10 }, () => ({})))));
        }),
      )
      .mockReturnValueOnce(
        new Promise((resolve) => {
          releaseSecond = () =>
            resolve(jsonResponse(bulkResponse(Array.from({ length: 2 }, () => ({})))));
        }),
      );

    renderPage();
    await user.upload(
      screen.getByLabelText("Choose files"),
      Array.from({ length: 12 }, (_, i) => file(`invoice-${i}.txt`)),
    );

    // BULK_CHUNK is 10, so this is two requests and the line moves between them.
    expect(await screen.findByText(/Extracting 1–10 of 12/)).toBeInTheDocument();
    releaseFirst();
    expect(await screen.findByText(/Extracting 11–12 of 12/)).toBeInTheDocument();
    releaseSecond();
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    observer.disconnect();

    // Every state the line was ever in named the files it was waiting on.
    expect(seen.length).toBeGreaterThan(0);
    for (const text of seen) {
      expect(text).toMatch(/Extracting \d+(–\d+)? of 12/);
    }
  });

  it("surfaces the plan limit as the server stated it", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse(
        { detail: "Plan 'free' allows 50 invoices per month. Upgrade to continue uploading." },
        { status: 402 },
      ),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), file());

    expect(await screen.findByText(/Upgrade to continue uploading/)).toBeInTheDocument();
  });

  describe("dragging files onto the dropzone", () => {
    // Dragging a scanned bill straight out of the mail client is the way most
    // of these arrive, so the drop path deserves the same cover as the picker.
    function dropzone(container) {
      return container.querySelector(".dropzone");
    }

    it("highlights the target while a file is over it", () => {
      const { container } = renderPage();

      fireEvent.dragOver(dropzone(container));

      expect(dropzone(container)).toHaveClass("is-dragging");
    });

    it("drops the highlight when the file is dragged away again", () => {
      const { container } = renderPage();
      fireEvent.dragOver(dropzone(container));

      fireEvent.dragLeave(dropzone(container));

      expect(dropzone(container)).not.toHaveClass("is-dragging");
    });

    it("uploads what was dropped", async () => {
      global.fetch = vi.fn().mockResolvedValue(jsonResponse(oneAccepted()));
      const { container } = renderPage();

      fireEvent.drop(dropzone(container), { dataTransfer: { files: [file("dropped.txt")] } });

      expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
      expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    it("clears the highlight once the drop is handled", async () => {
      // Otherwise the zone stays lit after the drop and looks stuck.
      global.fetch = vi.fn().mockResolvedValue(jsonResponse(oneAccepted()));
      const { container } = renderPage();
      fireEvent.dragOver(dropzone(container));

      fireEvent.drop(dropzone(container), { dataTransfer: { files: [file("dropped.txt")] } });

      await waitFor(() => expect(dropzone(container)).not.toHaveClass("is-dragging"));
    });

    describe("a second batch dropped while the first is still going", () => {
      /**
       * An upload the test releases by hand, so a second drop can be made to
       * land while the first batch is genuinely mid-flight.
       */
      function heldUpload() {
        const pending = [];
        global.fetch = vi.fn(
          () =>
            new Promise((resolve) => {
              pending.push(() => resolve(jsonResponse(oneAccepted())));
            }),
        );
        return pending;
      }

      it("does not start a second run alongside the first", async () => {
        // The picker is `disabled` while a batch runs, so the design already
        // says one at a time. The dropzone had no such guard, and two loops at
        // once defeat the thing the upload loop is sequential for: each file
        // costs a model call, and a burst is what the free tier rate-limits.
        const pending = heldUpload();
        const { container } = renderPage();

        fireEvent.drop(dropzone(container), {
          dataTransfer: { files: [file("first.txt")] },
        });
        await waitFor(() => expect(pending).toHaveLength(1));

        fireEvent.drop(dropzone(container), {
          dataTransfer: { files: [file("second.txt")] },
        });

        expect(await screen.findByText(/Still extracting the last batch/)).toBeInTheDocument();
        // The second drop must not have put another upload on the wire.
        expect(pending).toHaveLength(1);
      });

      it("takes the batch once the first one has finished", async () => {
        const pending = heldUpload();
        const { container } = renderPage();

        fireEvent.drop(dropzone(container), {
          dataTransfer: { files: [file("first.txt")] },
        });
        await waitFor(() => expect(pending).toHaveLength(1));
        // Released inside `act` because resolving it is what drives the state
        // updates that end the batch.
        await act(async () => pending[0]());
        await screen.findByText("INV-2026-0042");

        // Busy is over, so the zone accepts again — the refusal is about
        // overlap, not a door that stays shut.
        fireEvent.drop(dropzone(container), {
          dataTransfer: { files: [file("second.txt")] },
        });

        await waitFor(() => expect(pending).toHaveLength(2));
      });

      it("does not invite a drop it is about to refuse", async () => {
        const pending = heldUpload();
        const { container } = renderPage();
        fireEvent.drop(dropzone(container), {
          dataTransfer: { files: [file("first.txt")] },
        });
        await waitFor(() => expect(pending).toHaveLength(1));

        fireEvent.dragOver(dropzone(container));

        expect(dropzone(container)).not.toHaveClass("is-dragging");
      });
    });

    it("ignores a drop that carries no files", async () => {
      // Dragging selected text or a link onto the page fires the same event.
      global.fetch = vi.fn();
      const { container } = renderPage();

      fireEvent.drop(dropzone(container), { dataTransfer: { files: [] } });

      await waitFor(() => expect(dropzone(container)).not.toHaveClass("is-dragging"));
      expect(global.fetch.mock.calls.map((c) => c[0])).toEqual([]);
    });

    it("ignores a drop with no file list at all rather than throwing on it", async () => {
      // Not the same event as the one above. `Array.from(undefined)` throws,
      // and a throw here escapes into React's event handling — which takes the
      // page down for a gesture that should simply do nothing.
      global.fetch = vi.fn();
      const { container } = renderPage();

      fireEvent.drop(dropzone(container), { dataTransfer: {} });

      await waitFor(() => expect(dropzone(container)).not.toHaveClass("is-dragging"));
      expect(global.fetch.mock.calls.map((c) => c[0])).toEqual([]);
      expect(screen.getByRole("heading", { name: "Upload invoices" })).toBeInTheDocument();
    });
  });
});

describe("running out of the monthly allowance mid-batch", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });

  afterEach(() => vi.restoreAllMocks());

  /** More files than fit in one request, so there is a "rest of the batch". */
  function manyFiles(count) {
    return Array.from({ length: count }, (_, i) => file(`file-${i}.txt`));
  }

  it("stops uploading once the allowance is spent", async () => {
    // The allowance does not come back partway through a drop, so every
    // remaining batch gets the same 402. Carrying on spends the upload rate
    // limit on requests that cannot succeed.
    const user = userEvent.setup();
    global.fetch
      .mockResolvedValueOnce(jsonResponse(bulkResponse([{ filename: "a.txt" }])))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Monthly invoice allowance used up" }, { status: 402 }),
      );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), manyFiles(25));

    await screen.findByRole("alert");
    // One batch through, one refused, and the third never sent.
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
  });

  it("lists the files it did not attempt rather than dropping them", async () => {
    // A drop that quietly shrinks from fifteen to ten is how an invoice goes
    // missing from a return.
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Monthly invoice allowance used up" }, { status: 402 }),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), manyFiles(15));

    expect(await screen.findByText("file-14.txt")).toBeInTheDocument();
    // The five that were never sent, each said to be unattempted.
    expect(screen.getAllByText(/allowance ran out before this file/)).toHaveLength(5);
  });

  it("offers the plans when even a single file finds the allowance used up", async () => {
    // P24 M18: the banner said "upgrade the plan" with nothing to click, and
    // a single file got no banner at all, only its row: a dead end at the
    // moment the free plan stops being enough.
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Monthly invoice allowance used up" }, { status: 402 }),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), manyFiles(1));

    const plans = await screen.findByRole("link", { name: "See plans" });
    expect(plans).toHaveAttribute("href", "/pricing");
    expect(screen.getByRole("heading", { name: /uploads are used up/ })).toBeInTheDocument();
  });

  it("does not offer plans for the per-minute limit, which passes by itself", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Too many requests. Try again in 45s." }, { status: 429 }),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), manyFiles(1));

    await screen.findByText(/Too many requests/);
    expect(screen.queryByRole("link", { name: "See plans" })).not.toBeInTheDocument();
  });

  it("says how many were left and what to do about it", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Monthly invoice allowance used up" }, { status: 402 }),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), manyFiles(13));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /3 file\(s\) were not uploaded.*Upgrade the plan/,
    );
  });

  // The per-minute upload ceiling is the other answer about the account rather
  // than the document. It differs from the allowance in the direction that
  // matters: carrying on does not merely fail, it spends the budget that would
  // have let the rest of the drop through, because the limiter counts the
  // requests it refuses too.
  it("stops uploading once the upload rate limit is reached", async () => {
    const user = userEvent.setup();
    global.fetch
      .mockResolvedValueOnce(jsonResponse(bulkResponse([{ filename: "a.txt" }])))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Too many requests. Try again in 45s." }, { status: 429 }),
      );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), manyFiles(25));

    await screen.findByRole("alert");
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
  });

  it("lists the files the rate limit cost, and says they can just be dropped again", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Too many requests. Try again in 45s." }, { status: 429 }),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), manyFiles(15));

    expect(await screen.findByText("file-14.txt")).toBeInTheDocument();
    expect(screen.getAllByText(/rate limit was reached before this file/)).toHaveLength(5);
    // Unlike the allowance, this comes good on its own — so the instruction is
    // to wait and retry, not to go and buy something.
    expect(screen.getByRole("alert")).toHaveTextContent(
      /5 file\(s\) were not uploaded.*drop them again/,
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent(/Upgrade the plan/);
  });

  it("clears the banner when it is dismissed, and leaves the rows alone", async () => {
    // `ErrorBanner.test.jsx` proves the button calls back; this proves the
    // page's half of it, that the callback actually empties the state the
    // banner renders from. Nothing in the suite clicked dismiss on any page
    // before, so a banner that could be raised and never cleared would have
    // shipped green.
    //
    // The rows must survive it. The banner counts what did not upload and the
    // rows say which files those were — dismissing the summary is not a
    // reason to lose the detail it was summarising.
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Too many requests. Try again in 45s." }, { status: 429 }),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), manyFiles(15));
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("file-14.txt")).toBeInTheDocument();
  });

  it("leaves the seconds to the rows the server answered", async () => {
    // The banner says only what the rows cannot: how much of the drop never
    // went. The wait itself is the server's sentence, and it is already on the
    // rows for the files that were actually refused.
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Too many requests. Try again in 45s." }, { status: 429 }),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), manyFiles(15));

    expect(
      await screen.findAllByText("Too many requests. Try again in 45s."),
    ).toHaveLength(10);
  });

  it("keeps going through an ordinary per-file failure", async () => {
    // A duplicate or an unreadable scan says nothing about the next file, so it
    // is one rejected row in a batch the server otherwise accepted.
    const user = userEvent.setup();
    global.fetch.mockResolvedValueOnce(
      jsonResponse(
        bulkResponse([
          { filename: "a.txt", accepted: false, error: "Already on file" },
          { filename: "b.txt" },
        ]),
      ),
    );

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), [file("a.txt"), file("b.txt")]);

    expect(await screen.findByText("INV-2026-0042")).toBeInTheDocument();
    expect(screen.getByText("Already on file")).toBeInTheDocument();
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
  });
});

describe("the invoice type while a batch is running", () => {
  /** An upload that stays in flight until the returned callback is called. */
  function heldUpload() {
    const pending = [];
    global.fetch = vi.fn(
      () =>
        new Promise((resolve) => {
          pending.push(() => resolve(jsonResponse(oneAccepted())));
        }),
    );
    return pending;
  }

  it("locks the picker so the screen cannot disagree with what is being sent", async () => {
    // `uploadFiles` reads the type once and the loop under it is sequential,
    // so a forty-file batch goes on sending the type it started with for
    // minutes. Left live, the radio moved and the uploads did not: the screen
    // said Sales while the rest of the batch was still booked as purchases.
    //
    // Which is the expensive direction. A sales invoice booked as a purchase
    // claims credit against the business's own output tax, and no screen
    // downstream re-reads the document to catch it.
    const user = userEvent.setup();
    const pending = heldUpload();

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), [file("a.txt"), file("b.txt")]);
    await waitFor(() => expect(pending).toHaveLength(1));

    expect(screen.getByLabelText("Sales (feeds GSTR-1)")).toBeDisabled();
    expect(screen.getByLabelText("Purchase (claim ITC)")).toBeDisabled();
  });

  it("unlocks it once the batch is done", async () => {
    const user = userEvent.setup();
    const pending = heldUpload();

    renderPage();
    await user.upload(screen.getByLabelText("Choose files"), file("a.txt"));
    await waitFor(() => expect(pending).toHaveLength(1));
    await act(async () => pending[0]());
    await screen.findByText("INV-2026-0042");

    expect(screen.getByLabelText("Sales (feeds GSTR-1)")).toBeEnabled();
  });

  it("keeps the whole batch on the type it was started with", async () => {
    // The batch is the honest unit: splitting one drop across two types by
    // how fast someone clicked is not a thing anyone can predict.
    const user = userEvent.setup();
    const pending = heldUpload();

    renderPage();
    await user.click(screen.getByLabelText("Sales (feeds GSTR-1)"));
    // More than one request's worth, so there is a second batch to send under
    // a type the radio could have been moved to in between.
    await user.upload(
      screen.getByLabelText("Choose files"),
      Array.from({ length: 12 }, (_, i) => file(`file-${i}.txt`)),
    );

    await waitFor(() => expect(pending).toHaveLength(1));
    await act(async () => pending[0]());
    await waitFor(() => expect(pending).toHaveLength(2));
    await act(async () => pending[1]());

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    for (const call of global.fetch.mock.calls) {
      expect(call[1].body.get("invoice_type")).toBe("sales");
    }
  });

  describe("reaching the picker from the keyboard", () => {
    // The input is `.visually-hidden` — clipped to one pixel — with a label
    // styled as the button next to it. That is what makes a file picker look
    // like the rest of the app, and it is also what took the focus ring away:
    // the input holds focus, the input is what is clipped, and tabbing onto
    // the one control this page exists for lit nothing up anywhere on screen.
    //
    // The ring is drawn by `.dropzone:has(input:focus-visible) .btn`. jsdom
    // applies no stylesheet, so these pin the DOM that rule selects through
    // instead — move the input out of the dropzone, or drop the class off the
    // label, and the ring goes away again in silence.

    it("keeps the file input inside the dropzone", () => {
      const { container } = renderPage();

      expect(container.querySelector(".dropzone")).toContainElement(
        screen.getByLabelText("Choose files"),
      );
    });

    it("keeps the label the ring is drawn on inside it too", () => {
      const { container } = renderPage();

      expect(container.querySelector(".dropzone label.btn")).toHaveTextContent(
        "Choose files",
      );
    });

    it("leaves the input in the tab order rather than hiding it from focus", async () => {
      // `.visually-hidden` clips; it does not remove the element from the tab
      // order, and it must not — `display: none` or a negative tabindex here
      // would leave the page with no keyboard route to its own file picker at
      // all, ring or no ring.
      const user = userEvent.setup();
      renderPage();
      const input = screen.getByLabelText("Choose files");
      expect(input).not.toHaveAttribute("tabindex", "-1");

      // Reached by tabbing from the top of the page, rather than by a
      // programmatic focus() no user can perform.
      for (let i = 0; i < 20 && document.activeElement !== input; i += 1) {
        await user.tab();
      }
      expect(input).toHaveFocus();
    });

    it("takes the picker out of the tab order while a batch is running", async () => {
      // Disabled, so the ring cannot land on a control that would refuse the
      // click it is inviting. The label stays where it is, because a dropzone
      // with no button in it reads as broken.
      const user = userEvent.setup();
      global.fetch.mockReturnValueOnce(new Promise(() => {}));
      const { container } = renderPage();

      await user.upload(screen.getByLabelText("Choose files"), file());

      await waitFor(() => expect(screen.getByLabelText("Choose files")).toBeDisabled());
      expect(container.querySelector(".dropzone label.btn")).toBeInTheDocument();
    });
  });
});

describe("a viewer", () => {
  // Its own fetch, rather than the one the suite above leaves behind: this
  // block asserts that *no* request is made, which is only a claim about this
  // page if the counter starts at zero.
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  // Every route this page can call is writer-only, so there is no read-only
  // version of it to fall back to. The controls go and the notice takes their
  // place — a dropzone that answers 403 on drop would be worse than no
  // dropzone, and a bare page with nothing on it worse still.
  it("is not shown a dropzone whose every drop would be refused", () => {
    renderPage({ role: "viewer" });

    expect(screen.queryByLabelText("Choose files")).toBeNull();
    expect(screen.queryByText(/Drag invoices here/)).toBeNull();
    expect(screen.queryByRole("group", { name: /Invoice type/ })).toBeNull();
  });

  it("is told why, and who can do it", () => {
    renderPage({ role: "viewer" });

    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent(/read-only/);
    expect(notice).toHaveTextContent(/Ask an owner or an accountant to upload/);
  });

  it("sends nothing", async () => {
    // The gate is the point, so assert the absence that matters: no request
    // leaves the page at all, rather than one that leaves and is refused.
    renderPage({ role: "viewer" });
    await Promise.resolve();

    expect(global.fetch.mock.calls.map((c) => c[0])).toEqual([]);
  });

  it("leaves an owner the whole form", () => {
    renderPage();

    expect(screen.getByLabelText("Choose files")).toBeInTheDocument();
    expect(screen.getByText(/Drag invoices here/)).toBeInTheDocument();
    expect(screen.queryByText(/read-only/)).toBeNull();
  });

  describe("remembering the invoice type across visits", () => {
    it("restores the last-used type from localStorage", () => {
      localStorage.setItem("upload_type", "sales");
      renderPage();

      expect(screen.getByLabelText("Sales (feeds GSTR-1)")).toBeChecked();
      expect(screen.getByLabelText("Purchase (claim ITC)")).not.toBeChecked();
    });

    it("persists the chosen type to localStorage", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(screen.getByLabelText("Sales (feeds GSTR-1)"));
      expect(localStorage.getItem("upload_type")).toBe("sales");
    });

    it("falls back to purchase when localStorage is empty", () => {
      renderPage();

      expect(screen.getByLabelText("Purchase (claim ITC)")).toBeChecked();
    });

    it("falls back to purchase when localStorage throws on read", () => {
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new Error("SecurityError");
      });
      renderPage();

      expect(screen.getByLabelText("Purchase (claim ITC)")).toBeChecked();
    });

    it("survives localStorage throwing on write", async () => {
      const user = userEvent.setup();
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new Error("QuotaExceeded");
      });
      renderPage();

      await user.click(screen.getByLabelText("Sales (feeds GSTR-1)"));
      expect(screen.getByLabelText("Sales (feeds GSTR-1)")).toBeChecked();
    });
  });

  describe("next steps after upload", () => {
    it("shows a link to review uploaded invoices after a successful upload", async () => {
      const user = userEvent.setup();
      global.fetch.mockResolvedValueOnce(jsonResponse(oneAccepted()));
      renderPage();

      await user.upload(screen.getByLabelText("Choose files"), file());
      await screen.findByText("INV-2026-0042");

      expect(screen.getByRole("link", { name: "Review uploaded invoices" })).toHaveAttribute(
        "href",
        "/invoices?status=parsed",
      );
    });

    it("offers reconciliation as the next step for purchase invoices", async () => {
      const user = userEvent.setup();
      global.fetch.mockResolvedValueOnce(jsonResponse(oneAccepted()));
      renderPage();

      await user.upload(screen.getByLabelText("Choose files"), file());
      await screen.findByText("INV-2026-0042");

      expect(screen.getByRole("link", { name: "Reconcile with GSTR-2B" })).toHaveAttribute(
        "href",
        "/reconcile",
      );
    });

    it("offers GSTR-1 preparation as the next step for sales invoices", async () => {
      const user = userEvent.setup();
      global.fetch.mockResolvedValueOnce(jsonResponse(oneAccepted()));
      renderPage();

      await user.click(screen.getByLabelText("Sales (feeds GSTR-1)"));
      await user.upload(screen.getByLabelText("Choose files"), file());
      await screen.findByText("INV-2026-0042");

      expect(screen.getByRole("link", { name: "Prepare GSTR-1" })).toHaveAttribute(
        "href",
        "/filing",
      );
      expect(screen.queryByRole("link", { name: "Reconcile with GSTR-2B" })).not.toBeInTheDocument();
    });
  });

  describe("localStorage unavailable", () => {
    it("defaults to purchase when getItem throws", () => {
      const orig = Storage.prototype.getItem;
      Storage.prototype.getItem = () => { throw new Error("SecurityError"); };
      try {
        renderPage();
        expect(screen.getByLabelText("Purchase (claim ITC)")).toBeChecked();
      } finally {
        Storage.prototype.getItem = orig;
      }
    });

    it("swallows setItem errors in private browsing", async () => {
      const orig = Storage.prototype.setItem;
      Storage.prototype.setItem = () => { throw new Error("QuotaExceededError"); };
      try {
        renderPage();
        const user = userEvent.setup();
        await user.click(screen.getByLabelText("Sales (feeds GSTR-1)"));
        expect(screen.getByLabelText("Sales (feeds GSTR-1)")).toBeChecked();
      } finally {
        Storage.prototype.setItem = orig;
      }
    });
  });
});
