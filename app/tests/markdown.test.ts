import { parseInline, parseMarkdown, plainText } from "../src/core/markdown";

const styles = (s: string) => parseInline(s).map((x) => [x.text, x.bold ? "b" : "", x.italic ? "i" : ""].join("|"));

describe("inline", () => {
  test("bold and italic", () => {
    expect(styles("a **b** c *d*")).toEqual(["a ||", "b|b|", " c ||", "d||i"]);
  });
  test("an unclosed marker stays open to the end instead of showing asterisks", () => {
    expect(styles("a **bol")).toEqual(["a ||", "bol|b|"]);
    expect(plainText(parseInline("a **bol"))).toBe("a bol");
  });
  test("a lone trailing marker draws nothing", () => {
    expect(plainText(parseInline("hello *"))).toBe("hello *"); // followed by nothing: kept as text only if it cannot open
  });
  test("arithmetic and snake_case are literal", () => {
    expect(plainText(parseInline("2 * 3 = 6"))).toBe("2 * 3 = 6");
    expect(plainText(parseInline("snake_case_name"))).toBe("snake_case_name");
    expect(plainText(parseInline("5 * 4 * 3"))).toBe("5 * 4 * 3");
  });
  test("code spans, links and escapes", () => {
    expect(parseInline("use `x*y` now")[1]).toEqual({ text: "x*y", code: true });
    expect(plainText(parseInline("see [the map](http://x/y) here"))).toBe("see the map here");
    expect(plainText(parseInline("a \\*b\\* c"))).toBe("a *b* c");
    expect(plainText(parseInline("[the map](http://x"))).toBe("the map");
  });
  test("strike", () => {
    expect(parseInline("~~gone~~")[0]).toMatchObject({ text: "gone", strike: true });
  });
});

describe("blocks", () => {
  test("paragraphs, headings, lists, quotes, rules, fences", () => {
    const md = "# Title\n\nSome *text*\nmore\n\n- one\n- two\n\n1. a\n2. b\n\n> quoted\n\n---\n\n```\ncode *x*\n```\n";
    const kinds = parseMarkdown(md).map((b) => b.kind);
    expect(kinds).toEqual(["heading", "paragraph", "list", "list", "quote", "rule", "code"]);
    const code = parseMarkdown(md).find((b) => b.kind === "code");
    expect(code).toEqual({ kind: "code", text: "code *x*" });
  });
  test("a table becomes rows", () => {
    const t = parseMarkdown("| A | B |\n|---|---|\n| 1 | **2** |")[0];
    expect(t).toEqual({ kind: "table", rows: [["A", "B"], ["1", "2"]] });
  });
  test("every prefix of a reply parses without error, and the full text equals a one-shot parse", () => {
    const text = "# Hi\n\nThe door **splinters** inward. *Wait*, `x`.\n\n- a\n- b **c**\n\n> q\n\n| a | b |\n|---|---|\n| 1 | 2 |\n";
    for (let i = 0; i <= text.length; i++) expect(() => parseMarkdown(text.slice(0, i), true)).not.toThrow();
    expect(parseMarkdown(text, true)).toEqual(parseMarkdown(text, false));
  });
  test("a final line that is only a block marker is held back while streaming", () => {
    expect(parseMarkdown("Hello\n\n#", true)).toHaveLength(1);
    expect(parseMarkdown("Hello\n\n-", true)).toHaveLength(1);
    expect(parseMarkdown("Hello\n\n---", true)).toHaveLength(2); // a rule is a rule
  });
});
