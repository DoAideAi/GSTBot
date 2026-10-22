import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import NotFoundPage from "./NotFoundPage";

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <NotFoundPage />
    </MemoryRouter>,
  );
}

describe("NotFoundPage", () => {
  it("names the path that did not resolve rather than pretending it did", () => {
    renderAt("/gst-calcualtor");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Page not found");
    expect(screen.getByText("/gst-calcualtor")).toBeInTheDocument();
    expect(document.title).toMatch(/^Page not found/);
  });

  it("offers the free tools and a way home", () => {
    renderAt("/old-link");
    expect(screen.getByRole("link", { name: "GST Calculator" })).toHaveAttribute("href", "/calculator");
    expect(screen.getByRole("link", { name: "GSTIN Verification" })).toHaveAttribute("href", "/lookup");
    expect(screen.getByRole("link", { name: /homepage/i })).toHaveAttribute("href", "/");
  });

  it("asks search engines not to index it, and leaves no tag behind on the next page", () => {
    const { unmount } = renderAt("/old-link");
    expect(document.querySelector('meta[name="robots"]')).toHaveAttribute("content", "noindex");
    unmount();
    expect(document.querySelector('meta[name="robots"]')).toBeNull();
  });

  it("restores a robots tag the previous page had set", () => {
    const meta = document.createElement("meta");
    meta.setAttribute("name", "robots");
    meta.setAttribute("content", "index, follow");
    document.head.appendChild(meta);

    const { unmount } = renderAt("/old-link");
    expect(meta).toHaveAttribute("content", "noindex");
    unmount();
    expect(meta).toHaveAttribute("content", "index, follow");
    meta.remove();
  });
});
