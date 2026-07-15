// Safe Markdown (spec_v006 §12.2): rich basics render, raw HTML and unsafe URL
// protocols never survive.
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Markdown from "../src/chat/Markdown";

describe("Markdown", () => {
  it("renders paragraphs, lists, emphasis, code, and tables", () => {
    const md = [
      "Some **bold** and `code`.",
      "",
      "- item one",
      "- item two",
      "",
      "| a | b |",
      "| - | - |",
      "| 1 | 2 |",
    ].join("\n");
    const { container } = render(<Markdown text={md} />);
    expect(container.querySelector("strong")).toBeTruthy();
    expect(container.querySelector("code")).toBeTruthy();
    expect(container.querySelectorAll("li").length).toBe(2);
    expect(container.querySelector("table")).toBeTruthy();
  });

  it("strips script tags and inline handlers", () => {
    const { container } = render(
      <Markdown text={'hello <script>alert(1)</script> <img src=x onerror=alert(1)>'} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.innerHTML).not.toContain("onerror");
  });

  it("removes javascript: URLs", () => {
    const { container } = render(<Markdown text={"[x](javascript:alert(1))"} />);
    const a = container.querySelector("a");
    expect(a?.getAttribute("href") ?? "").not.toContain("javascript:");
  });
});
