import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

// Sanitized Markdown (spec_v006 §12.2): paragraphs, lists, emphasis, code, and
// small tables only. Raw HTML is never emitted by the parser, and DOMPurify
// strips unsafe tags/attributes and unsafe URL protocols as defense in depth.
const ALLOWED_TAGS = [
  "p", "br", "hr", "strong", "em", "del", "code", "pre", "blockquote",
  "ul", "ol", "li", "a", "h1", "h2", "h3", "h4",
  "table", "thead", "tbody", "tr", "th", "td",
];
const ALLOWED_ATTR = ["href", "title"];

marked.setOptions({ gfm: true, breaks: true });

function render(md: string): string {
  const raw = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: false,
    FORBID_ATTR: ["style", "onerror", "onclick"],
  });
}

export default function Markdown({ text }: { text: string }) {
  const html = useMemo(() => render(text), [text]);
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}
