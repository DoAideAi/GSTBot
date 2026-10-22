import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthContext } from "../hooks/useAuth";
import SavePrompt, { getCalcCount, incrementCalcCount } from "./SavePrompt";

const noAuth = {
  user: null,
  loading: false,
  canWrite: false,
  login: () => {},
  register: () => {},
  logout: () => {},
  switchBusiness: () => {},
};

const authed = {
  ...noAuth,
  user: { id: 1, email: "test@example.com" },
};

function renderPrompt({ calcCount = 3, onDismiss = () => {}, auth = noAuth } = {}) {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={auth}>
        <SavePrompt calcCount={calcCount} onDismiss={onDismiss} />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe("SavePrompt", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("shows after 3 calculations for anonymous users", () => {
    renderPrompt({ calcCount: 3 });
    expect(screen.getByText("Save your calculations")).toBeInTheDocument();
  });

  it("does not show before 3 calculations", () => {
    renderPrompt({ calcCount: 2 });
    expect(screen.queryByText("Save your calculations")).not.toBeInTheDocument();
  });

  it("does not show for logged-in users", () => {
    renderPrompt({ calcCount: 5, auth: authed });
    expect(screen.queryByText("Save your calculations")).not.toBeInTheDocument();
  });

  it("has a sign-up link", () => {
    renderPrompt();
    expect(screen.getByRole("link", { name: "Sign up free" })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  it("calls onDismiss when Not now is clicked", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    renderPrompt({ onDismiss });
    await user.click(screen.getByRole("button", { name: "Not now" }));
    expect(onDismiss).toHaveBeenCalled();
  });
});

describe("calc counter", () => {
  beforeEach(() => localStorage.clear());

  it("starts at zero", () => {
    expect(getCalcCount()).toBe(0);
  });

  it("increments", () => {
    expect(incrementCalcCount()).toBe(1);
    expect(incrementCalcCount()).toBe(2);
    expect(getCalcCount()).toBe(2);
  });

  it("survives localStorage being unavailable", () => {
    const origGetItem = localStorage.getItem;
    localStorage.getItem = () => { throw new Error("blocked"); };
    expect(getCalcCount()).toBe(0);
    localStorage.getItem = origGetItem;
  });
});
