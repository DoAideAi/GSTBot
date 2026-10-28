import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ErrorBoundary, { isChunkLoadError, SectionBoundary } from "./ErrorBoundary";

/** Throws on render when `explode` is true. */
function Bomb({ explode, message = "Cannot read properties of null" }) {
  if (explode) throw new Error(message);
  return <p>Everything is fine</p>;
}

/** Throws something that is not an Error, which React catches all the same. */
function RawThrow({ value }) {
  throw value;
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // The boundary logs to console.error by design — it is the only reporting
    // channel this app has. Silenced so a passing run is not full of stacks.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => vi.restoreAllMocks());

  it("renders its children when nothing throws", () => {
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <Bomb explode={false} />
        </ErrorBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByText("Everything is fine")).toBeInTheDocument();
  });

  it("says the app was updated when a screen's file cannot be fetched", () => {
    // After a deploy an open tab asks for a chunk that no longer exists. Try
    // again cannot fix that (React.lazy keeps the rejected import), and the
    // text to quote would be the browser's own.
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <Bomb explode message="Failed to fetch dynamically imported module: /assets/Filing-3f2a.js" />
        </ErrorBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "This app has been updated" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.queryByText(/dynamically imported module/)).not.toBeInTheDocument();
  });

  it("recognises each browser's wording for a failed chunk, and nothing else", () => {
    for (const message of [
      "Failed to fetch dynamically imported module: https://x/a.js", // Chrome
      "error loading dynamically imported module", // Firefox
      "Importing a module script failed.", // Safari
    ]) {
      expect(isChunkLoadError(new TypeError(message))).toBe(true);
    }
    expect(isChunkLoadError(Object.assign(new Error("x"), { name: "ChunkLoadError" }))).toBe(true);
    expect(isChunkLoadError(new Error("Cannot read properties of null"))).toBe(false);
    expect(isChunkLoadError("a string")).toBe(false);
  });

  it("catches a render crash instead of blanking the app", () => {
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <Bomb explode />
        </ErrorBoundary>
      </MemoryRouter>,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("This screen hit an error")).toBeInTheDocument();
  });

  it("tells the user their data is safe", () => {
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <Bomb explode />
        </ErrorBoundary>
      </MemoryRouter>,
    );

    // The fear after a crash mid-upload is "did my invoice save?". The
    // fallback answers it, because the boundary only catches render failures.
    expect(screen.getByText(/Nothing you have entered was lost/)).toBeInTheDocument();
  });

  it("shows the underlying message rather than swallowing it", () => {
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <Bomb explode message="total_value of null" />
        </ErrorBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByText(/total_value of null/)).toBeInTheDocument();
  });

  it("introduces that message as something to quote, not as the explanation", () => {
    // The one line on this screen not written for the person reading it. Sat
    // under an apology and nothing else, "total_value of null" reads as the
    // app's account of what happened — addressed to a reader it cannot mean
    // anything to, and giving them nothing to do. The label is what makes the
    // same string useful to them: it is the part they pass on.
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <Bomb explode message="total_value of null" />
        </ErrorBoundary>
      </MemoryRouter>,
    );

    // Asserted through the raw text's own parent rather than by searching for
    // the whole sentence: the label and the message are separate nodes, which
    // is what keeps the message findable on its own by every test above.
    expect(screen.getByText("total_value of null").parentElement).toHaveTextContent(
      "If you report this, quote: total_value of null",
    );
  });

  it("shows a thrown value that is not an Error, rather than an empty detail", () => {
    // `throw` takes any value, and a bundled dependency rejecting a render
    // with a string is the realistic source. Reading `.message` off it gives
    // undefined, and the detail line then renders as nothing at all — which
    // is the one line telling anyone what actually broke.
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <RawThrow value="chart series is not an array" />
        </ErrorBoundary>
      </MemoryRouter>,
    );

    expect(screen.getByText("chart series is not an array")).toBeInTheDocument();
  });

  it("still logs, so there is something to debug from", () => {
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <Bomb explode />
        </ErrorBoundary>
      </MemoryRouter>,
    );
    expect(console.error).toHaveBeenCalled();
  });

  it("recovers when Try again is clicked and the cause is gone", async () => {
    const user = userEvent.setup();

    function Flaky() {
      const [explode, setExplode] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setExplode(false)}>
            Fix it
          </button>
          <ErrorBoundary>
            <Bomb explode={explode} />
          </ErrorBoundary>
        </>
      );
    }

    render(
      <MemoryRouter>
        <Flaky />
      </MemoryRouter>,
    );

    expect(screen.getByText("This screen hit an error")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Fix it" }));
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(screen.getByText("Everything is fine")).toBeInTheDocument();
  });

  it("clears itself on navigation", async () => {
    const user = userEvent.setup();

    function Nav() {
      const navigate = useNavigate();
      return (
        <button type="button" onClick={() => navigate("/safe")}>
          Go elsewhere
        </button>
      );
    }

    render(
      <MemoryRouter initialEntries={["/broken"]}>
        <Nav />
        <ErrorBoundary>
          <Routes>
            <Route path="/broken" element={<Bomb explode />} />
            <Route path="/safe" element={<p>A different screen</p>} />
          </Routes>
        </ErrorBoundary>
      </MemoryRouter>,
    );

    expect(screen.getByText("This screen hit an error")).toBeInTheDocument();

    // Without the reset-on-navigation the boundary stays broken and every
    // later route renders the fallback, which looks like the whole app died.
    await user.click(screen.getByRole("button", { name: "Go elsewhere" }));
    expect(screen.getByText("A different screen")).toBeInTheDocument();
  });

  it("offers a reload as the second escape hatch, and it reloads", async () => {
    // Clicked rather than merely found. "Try again" re-renders and nothing
    // else, so when the cause is state a re-render cannot clear, this button
    // is the last thing between the user and clearing site data — and one
    // wired to nothing looks exactly like one that works.
    const user = userEvent.setup();
    const reload = vi.fn();
    const real = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...real, reload },
    });

    try {
      render(
        <MemoryRouter>
          <ErrorBoundary>
            <Bomb explode />
          </ErrorBoundary>
        </MemoryRouter>,
      );

      await user.click(screen.getByRole("button", { name: "Reload the app" }));

      expect(reload).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: real });
    }
  });
});

describe("SectionBoundary", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => vi.restoreAllMocks());

  /** A page with a widget that throws, and content either side of it. */
  function Page({ explode }) {
    return (
      <MemoryRouter>
        <p>Net liability ₹41,200</p>
        <SectionBoundary name="The net liability trend">
          <Bomb explode={explode} message="Cannot read properties of null" />
        </SectionBoundary>
        <p>Plan usage</p>
      </MemoryRouter>
    );
  }

  it("renders its children when nothing throws", () => {
    render(<Page explode={false} />);
    expect(screen.getByText("Everything is fine")).toBeInTheDocument();
  });

  it("shows a thrown value that is not an Error here too", () => {
    // The quiet fallback has the same detail line, and the same way to lose it.
    render(
      <MemoryRouter>
        <SectionBoundary name="The net liability trend">
          <RawThrow value="series[3].total is null" />
        </SectionBoundary>
      </MemoryRouter>,
    );

    expect(screen.getByText("series[3].total is null")).toBeInTheDocument();
  });

  it("costs the page only the section that failed", () => {
    render(<Page explode />);

    // The whole reason this is not the page boundary. A null in one of six
    // period summaries used to take the stat cards and the tax table with it —
    // everything the user actually came for.
    expect(screen.getByText("Net liability ₹41,200")).toBeInTheDocument();
    expect(screen.getByText("Plan usage")).toBeInTheDocument();
  });

  it("names what is missing", () => {
    render(<Page explode />);
    // "Something went wrong" floating between two panels does not tell the user
    // what they are no longer looking at.
    expect(
      screen.getByText("The net liability trend could not be displayed"),
    ).toBeInTheDocument();
  });

  it("does not interrupt with an alert", () => {
    render(<Page explode />);

    // A chart that failed to draw, while the numbers it summarises are still on
    // screen, is not worth cutting across whatever a screen reader is saying.
    // The page-level boundary is the loud one.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("still shows the underlying message", () => {
    render(<Page explode />);
    expect(screen.getByText(/Cannot read properties of null/)).toBeInTheDocument();
  });

  it("still logs", () => {
    render(<Page explode />);
    expect(console.error).toHaveBeenCalled();
  });

  it("retries just the section", async () => {
    const user = userEvent.setup();

    function Flaky() {
      const [explode, setExplode] = useState(true);
      return (
        <MemoryRouter>
          <button type="button" onClick={() => setExplode(false)}>
            Fix it
          </button>
          <SectionBoundary name="The net liability trend">
            <Bomb explode={explode} />
          </SectionBoundary>
        </MemoryRouter>
      );
    }

    render(<Flaky />);
    expect(screen.getByText("The net liability trend could not be displayed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Fix it" }));
    await user.click(screen.getByRole("button", { name: "Retry this section" }));

    expect(screen.getByText("Everything is fine")).toBeInTheDocument();
  });

  it("clears itself on navigation like the page boundary does", async () => {
    const user = userEvent.setup();

    function Nav() {
      const navigate = useNavigate();
      return (
        <button type="button" onClick={() => navigate("/safe")}>
          Go elsewhere
        </button>
      );
    }

    render(
      <MemoryRouter initialEntries={["/broken"]}>
        <Nav />
        <SectionBoundary name="The chart">
          <Routes>
            <Route path="/broken" element={<Bomb explode />} />
            <Route path="/safe" element={<p>A different screen</p>} />
          </Routes>
        </SectionBoundary>
      </MemoryRouter>,
    );

    expect(screen.getByText("The chart could not be displayed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Go elsewhere" }));
    expect(screen.getByText("A different screen")).toBeInTheDocument();
  });
});
