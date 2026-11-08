import { describe, expect, it } from "vitest";
import { fileProblem, formatCitation, isStillProcessing } from "./format";

describe("formatCitation", () => {
  it("shows the title and page the server returned", () => {
    expect(formatCitation({ title: "Fee Policy", page: 3 })).toBe("Fee Policy, page 3");
  });

  it("never invents a page number", () => {
    expect(formatCitation({ title: "Fee Policy", page: null })).toBe("Fee Policy (page not recorded)");
  });
});

describe("fileProblem", () => {
  it("accepts a small PDF", () => {
    expect(fileProblem({ name: "policy.pdf", type: "application/pdf", size: 1024 })).toBeNull();
  });

  it("refuses other file types and oversize files", () => {
    expect(fileProblem({ name: "notes.docx", type: "application/msword", size: 10 })).toMatch(/Only PDF/);
    expect(fileProblem({ name: "big.pdf", type: "application/pdf", size: 21 * 1024 * 1024 })).toMatch(/larger than 20 MB/);
    expect(fileProblem(undefined)).toMatch(/Choose a PDF/);
  });
});

describe("isStillProcessing", () => {
  it("polls only while a document is queued or processing", () => {
    expect(isStillProcessing([{ processing_status: "ready" }, { processing_status: "pending" }])).toBe(true);
    expect(isStillProcessing([{ processing_status: "ready" }, { processing_status: "failed" }])).toBe(false);
  });
});
