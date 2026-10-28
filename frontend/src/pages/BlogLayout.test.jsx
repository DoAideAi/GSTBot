import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import BlogLayout, { BlogIndex, ARTICLES } from "./BlogLayout";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

function renderBlog(path = "/blog") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/blog" element={<BlogLayout />}>
          <Route index element={<BlogIndex />} />
          <Route path="test" element={<div>Test article</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("BlogLayout", () => {
  it("renders the blog header", () => {
    renderBlog();

    expect(screen.getByText("DoAide GST Blog")).toBeInTheDocument();
    expect(screen.getByText("Guides and resources for GST compliance in India")).toBeInTheDocument();
  });

  it("has a link back to the home page", () => {
    renderBlog();

    const link = screen.getByText(/Back to DoAide GST/);
    expect(link.closest("a")).toHaveAttribute("href", "/");
  });

  it("renders the outlet content", () => {
    renderBlog("/blog/test");

    expect(screen.getByText("Test article")).toBeInTheDocument();
  });

  it("puts the article inside the page's main landmark", () => {
    renderBlog("/blog/test");
    expect(screen.getByRole("main")).toContainElement(screen.getByText("Test article"));
  });
});

describe("BlogIndex", () => {
  it("renders a card for each article", () => {
    renderBlog();

    for (const article of ARTICLES) {
      expect(screen.getByText(article.title)).toBeInTheDocument();
      expect(screen.getByText(article.description)).toBeInTheDocument();
    }
  });

  it("links to each article page", () => {
    renderBlog();

    for (const article of ARTICLES) {
      const link = screen.getByText(article.title).closest("a");
      expect(link).toHaveAttribute("href", `/blog/${article.slug}`);
    }
  });

  it("shows read-more prompts", () => {
    renderBlog();

    const readMores = screen.getAllByText("Read more →");
    expect(readMores).toHaveLength(ARTICLES.length);
  });
});

describe("ARTICLES", () => {
  it("exports articles with unique slugs", () => {
    expect(ARTICLES.length).toBeGreaterThanOrEqual(11);
    const slugs = ARTICLES.map((a) => a.slug);
    expect(new Set(slugs).size).toBe(ARTICLES.length);
  });
});
