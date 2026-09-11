import { act, renderHook } from "@testing-library/react";
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
import { useCandidateImport } from "../features/candidate-import/useCandidateImport.js";

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
