// eslint-disable-next-line no-unused-vars
import React from "react";

import { readFileSync } from "node:fs";
import { act, render, renderHook, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import apiClient from "../api/client.js";

vi.mock("../features/candidate-import/api.js", async () => {
  const actual = await vi.importActual("../features/candidate-import/api.js");
  return {
    ...actual,
    createImportBatch: vi.fn(),
    uploadToPresignedPost: vi.fn(),
    completeImportBatch: vi.fn(),
    getImportBatch: vi.fn(),
    getImportItems: vi.fn(),
    getRecentImports: vi.fn(),
  };
});

import * as candidateImportApi from "../features/candidate-import/api.js";
import ImportProgress from "../features/candidate-import/ImportProgress.jsx";
import ImportSummary from "../features/candidate-import/ImportSummary.jsx";
import { useCandidateImport } from "../features/candidate-import/useCandidateImport.js";
import {
  validateSelectedFile,
  validateSelectedFiles,
} from "../features/candidate-import/validation.js";

let actualApi;

beforeAll(async () => {
  actualApi = await vi.importActual("../features/candidate-import/api.js");
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  localStorage.clear();
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
});

function processingBatch(overrides = {}) {
  return {
    id: "batch-1",
    job_id: "job-1",
    status: "PROCESSING",
    current_stage: "EVALUATING",
    upload_total: 1,
    uploaded_items: 1,
    total_items: 10,
    processed_items: 10,
    successful_items: 10,
    reused_items: 0,
    failed_items: 0,
    evaluated_items: 2,
    evaluation_failed_items: 0,
    ranking_ready: false,
    ranking_version: null,
    ...overrides,
  };
}

function completedBatch(overrides = {}) {
  return processingBatch({
    status: "COMPLETED",
    current_stage: "COMPLETED",
    evaluated_items: 10,
    ranking_ready: true,
    ranking_version: 4,
    ...overrides,
  });
}

describe("candidate import API", () => {
  it("creates a backend manifest from browser Files", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { batch_id: "batch-1", status: "UPLOADING", uploads: [] },
    });
    const pdf = new File(["pdf"], "Ana CV.pdf", { type: "application/pdf" });
    const docx = new File(["docx"], "Bea.docx", { type: "" });

    const result = await actualApi.createImportBatch("job-1", [pdf, docx]);

    expect(result.batch_id).toBe("batch-1");
    expect(post).toHaveBeenCalledWith("/api/import-batches", {
      job_id: "job-1",
      uploads: [
        {
          filename: "Ana CV.pdf",
          size_bytes: pdf.size,
          content_type: "application/pdf",
        },
        {
          filename: "Bea.docx",
          size_bytes: docx.size,
          content_type: "application/octet-stream",
        },
      ],
    });
  });

  it("uses the owner-scoped batch endpoints and pagination parameters", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { ok: true } });
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: { items: [] } });

    await actualApi.completeImportBatch("batch-1");
    await actualApi.getImportBatch("batch-1");
    await actualApi.getImportItems("batch-1", 2, 50);
    await actualApi.getRecentImports("job-1");

    expect(post).toHaveBeenCalledWith("/api/import-batches/batch-1/complete");
    expect(get).toHaveBeenNthCalledWith(1, "/api/import-batches/batch-1");
    expect(get).toHaveBeenNthCalledWith(2, "/api/import-batches/batch-1/items", {
      params: { page: 2, page_size: 50 },
    });
    expect(get).toHaveBeenNthCalledWith(3, "/api/import-batches", {
      params: { job_id: "job-1", limit: 10 },
    });
  });

  it("reports real S3 byte progress from XMLHttpRequest", async () => {
    class FakeXHR {
      static instances = [];

      constructor() {
        this.upload = {};
        this.status = 0;
        FakeXHR.instances.push(this);
      }

      open(method, url) {
        this.method = method;
        this.url = url;
      }

      send(body) {
        this.body = body;
      }
    }

    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const onProgress = vi.fn();
    const file = new File(["candidate"], "ana.pdf", { type: "application/pdf" });
    const uploadPromise = actualApi.uploadToPresignedPost(
      file,
      {
        url: "https://staging.example/upload",
        fields: { key: "imports/batch-1/item-1/ana.pdf", policy: "signed" },
      },
      onProgress,
    );

    const xhr = FakeXHR.instances[0];
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("https://staging.example/upload");

    xhr.upload.onprogress({ lengthComputable: true, loaded: 5, total: 10 });
    expect(onProgress).toHaveBeenCalledWith(5, 10);
    expect(xhr.body.get("key")).toBe("imports/batch-1/item-1/ana.pdf");
    expect(xhr.body.get("file")).toBe(file);

    xhr.status = 204;
    xhr.onload();
    await expect(uploadPromise).resolves.toBeUndefined();
    vi.unstubAllGlobals();
  });
});

describe("useCandidateImport", () => {
  it("stops polling when the server reaches a terminal status", async () => {
    vi.useFakeTimers();
    candidateImportApi.getImportBatch
      .mockResolvedValueOnce(processingBatch())
      .mockResolvedValueOnce(completedBatch());
    candidateImportApi.getImportItems.mockResolvedValue({ items: [], total: 0 });

    const { result, unmount } = renderHook(() => useCandidateImport());
    await act(async () => result.current.resumeImport("batch-1"));
    expect(candidateImportApi.getImportBatch).toHaveBeenCalledTimes(1);

    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.batch.status).toBe("COMPLETED");
    expect(candidateImportApi.getImportBatch).toHaveBeenCalledTimes(2);
    expect(result.current).not.toHaveProperty("overallPercent");

    await act(async () => vi.advanceTimersByTimeAsync(10000));
    expect(candidateImportApi.getImportBatch).toHaveBeenCalledTimes(2);
    unmount();
  });

  it("uses slower polling while the document is hidden", async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    candidateImportApi.getImportBatch
      .mockResolvedValueOnce(processingBatch())
      .mockResolvedValueOnce(completedBatch());
    candidateImportApi.getImportItems.mockResolvedValue({ items: [], total: 0 });

    const { result, unmount } = renderHook(() => useCandidateImport());
    await act(async () => result.current.resumeImport("batch-1"));

    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(candidateImportApi.getImportBatch).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTimeAsync(8000));
    expect(candidateImportApi.getImportBatch).toHaveBeenCalledTimes(2);
    expect(result.current.batch.status).toBe("COMPLETED");
    unmount();
  });

  it("recovers an active backend batch for the selected job after remount", async () => {
    vi.useFakeTimers();
    const recent = processingBatch({ current_stage: "INGESTING" });
    candidateImportApi.getRecentImports.mockResolvedValue({ items: [recent] });
    candidateImportApi.getImportBatch.mockResolvedValue(recent);
    candidateImportApi.getImportItems.mockResolvedValue({ items: [], total: 0 });

    const { result, unmount } = renderHook(() => useCandidateImport("job-1"));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(candidateImportApi.getRecentImports).toHaveBeenCalledWith("job-1");
    expect(result.current.batch?.id).toBe("batch-1");
    expect(result.current.phase).toBe("processing");
    unmount();
  });

  it("uploads at most four files concurrently and clears upload percentage after completion", async () => {
    const files = Array.from({ length: 6 }, (_, index) =>
      new File([`cv-${index}`], `candidate-${index}.pdf`, { type: "application/pdf" }),
    );
    candidateImportApi.createImportBatch.mockResolvedValue({
      batch_id: "batch-1",
      status: "UPLOADING",
      current_stage: "UPLOADING",
      uploads: files.map((file, index) => ({
        item_id: `item-${index}`,
        filename: file.name,
        size_bytes: file.size,
        upload: { url: "https://staging.example", fields: { key: `key-${index}` } },
      })),
    });
    candidateImportApi.completeImportBatch.mockResolvedValue(completedBatch());
    candidateImportApi.getImportItems.mockResolvedValue({ items: [], total: 0 });

    let active = 0;
    let maxActive = 0;
    const pending = [];
    candidateImportApi.uploadToPresignedPost.mockImplementation((file, _descriptor, onProgress) =>
      new Promise((resolve) => {
        active += 1;
        maxActive = Math.max(maxActive, active);
        pending.push(() => {
          onProgress(file.size, file.size);
          active -= 1;
          resolve();
        });
      }),
    );

    const { result, unmount } = renderHook(() => useCandidateImport());
    let startPromise;
    act(() => {
      startPromise = result.current.startImport("job-1", files);
    });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(candidateImportApi.uploadToPresignedPost).toHaveBeenCalledTimes(4);
    expect(maxActive).toBe(4);

    await act(async () => {
      pending.splice(0, 4).forEach((resolve) => resolve());
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(candidateImportApi.uploadToPresignedPost).toHaveBeenCalledTimes(6);
    expect(maxActive).toBe(4);

    await act(async () => {
      pending.splice(0).forEach((resolve) => resolve());
      await startPromise;
    });

    expect(candidateImportApi.completeImportBatch).toHaveBeenCalledWith("batch-1");
    expect(result.current.phase).toBe("completed");
    expect(result.current.uploadProgress).toBeNull();
    expect(result.current.batch.status).toBe("COMPLETED");
    unmount();
  });
});

describe("candidate import UX", () => {
  it("renders evaluation count and indeterminate ingestion without a fake overall percent", () => {
    const { rerender } = render(
      <ImportProgress
        batch={processingBatch({
          successful_items: 327,
          evaluated_items: 143,
        })}
        uploadProgress={null}
      />,
    );

    expect(screen.getByText(/143 \/ 327/)).toBeInTheDocument();
    expect(screen.queryByText(/68%/)).not.toBeInTheDocument();

    rerender(
      <ImportProgress
        batch={processingBatch({ current_stage: "INGESTING" })}
        uploadProgress={null}
      />,
    );
    expect(screen.getByTestId("indeterminate-progress")).toBeInTheDocument();
  });

  it("shows only measured byte percentage during browser upload", () => {
    render(
      <ImportProgress
        batch={{ status: "UPLOADING", current_stage: "UPLOADING" }}
        uploadProgress={{ loadedBytes: 50, totalBytes: 100, percent: 50 }}
      />,
    );

    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText(/50 B de 100 B/)).toBeInTheDocument();
  });

  it("accepts PDF DOCX and ZIP but rejects unsupported direct files", () => {
    expect(
      validateSelectedFile({
        name: "a.pdf",
        size: 1024,
        type: "application/pdf",
      }),
    ).toBeNull();
    expect(
      validateSelectedFile({
        name: "a.docx",
        size: 1024,
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      }),
    ).toBeNull();
    expect(
      validateSelectedFile({
        name: "a.zip",
        size: 1024,
        type: "application/zip",
      }),
    ).toBeNull();
    expect(
      validateSelectedFile({
        name: "a.txt",
        size: 1024,
        type: "text/plain",
      }),
    ).toMatch(/PDF, DOCX o ZIP/);
  });

  it("enforces the 15 MiB direct-document limit and 500 direct-document ceiling", () => {
    expect(
      validateSelectedFile({
        name: "large.pdf",
        size: 15 * 1024 * 1024 + 1,
        type: "application/pdf",
      }),
    ).toMatch(/15 MB/);

    const tooMany = Array.from({ length: 501 }, (_, index) => ({
      name: `candidate-${index}.pdf`,
      size: 1024,
      type: "application/pdf",
    }));
    expect(validateSelectedFiles(tooMany)).toMatch(/500/);
  });

  it("renders completed-with-errors summary and ranking deep link", () => {
    render(
      <MemoryRouter>
        <ImportSummary
          batch={completedBatch({
            status: "COMPLETED_WITH_ERRORS",
            job_id: "job-1",
            successful_items: 8,
            reused_items: 3,
            failed_items: 2,
            evaluation_failed_items: 1,
          })}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText(/completada con novedades/i)).toBeInTheDocument();
    expect(screen.getByText(/8/)).toBeInTheDocument();
    expect(screen.getByText(/3/)).toBeInTheDocument();
    expect(screen.getByText(/2/)).toBeInTheDocument();
    expect(screen.getByText(/1/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ver ranking/i })).toHaveAttribute(
      "href",
      "/ranking?job_id=job-1",
    );
  });

  it("does not offer ranking when the batch failed before ranking", () => {
    render(
      <MemoryRouter>
        <ImportSummary
          batch={processingBatch({
            status: "FAILED",
            current_stage: "INGESTING",
            ranking_ready: false,
            last_error_message: "No se pudo completar la ingestión.",
          })}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText(/no se pudo completar la ingestión/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /ver ranking/i })).not.toBeInTheDocument();
  });

  it("disables nonessential candidate-import motion for reduced-motion users", () => {
    const css = readFileSync(
      new URL("../features/candidate-import/candidate-import.css", import.meta.url),
      "utf8",
    );
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(css).toMatch(/animation:\s*none\s*!important/);
    expect(css).toMatch(/transition:\s*none\s*!important/);
  });
});
