import { useCallback, useEffect, useRef, useState } from "react";

import * as candidateImportApi from "./api.js";

const TERMINAL_STATUSES = new Set([
  "COMPLETED",
  "COMPLETED_WITH_ERRORS",
  "FAILED",
]);
const FOREGROUND_POLL_MS = 2000;
const HIDDEN_POLL_MS = 10000;
const UPLOAD_CONCURRENCY = 4;
const STORAGE_KEY = "candidate_import_batch_id";

function isTerminal(batch) {
  return Boolean(batch && TERMINAL_STATUSES.has(batch.status));
}

function phaseForBatch(batch) {
  if (!batch) return "idle";
  if (batch.status === "FAILED") return "failed";
  if (batch.status === "COMPLETED" || batch.status === "COMPLETED_WITH_ERRORS") {
    return "completed";
  }
  if (batch.status === "UPLOADING") return "uploading";
  return "processing";
}

function publicError(error) {
  return (
    error?.response?.data?.detail ||
    error?.message ||
    "No fue posible continuar la importación."
  );
}

function persistBatchId(batchId) {
  if (typeof localStorage === "undefined") return;
  if (batchId) localStorage.setItem(STORAGE_KEY, batchId);
  else localStorage.removeItem(STORAGE_KEY);
}

export function useCandidateImport(jobId = null) {
  const [phase, setPhase] = useState("idle");
  const [batch, setBatch] = useState(null);
  const [items, setItems] = useState([]);
  const [uploadProgress, setUploadProgress] = useState(null);
  const [error, setError] = useState(null);

  const timerRef = useRef(null);
  const pollRef = useRef(null);
  const currentBatchIdRef = useRef(null);
  const mountedRef = useRef(true);

  const clearPolling = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const schedulePoll = useCallback(
    (batchId) => {
      clearPolling();
      if (!batchId || !mountedRef.current) return;
      const delay = document.hidden ? HIDDEN_POLL_MS : FOREGROUND_POLL_MS;
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        pollRef.current?.(batchId);
      }, delay);
    },
    [clearPolling],
  );

  const refreshBatch = useCallback(
    async (batchId) => {
      try {
        const [nextBatch, itemPage] = await Promise.all([
          candidateImportApi.getImportBatch(batchId),
          candidateImportApi.getImportItems(batchId, 1, 100),
        ]);
        if (!mountedRef.current || currentBatchIdRef.current !== batchId) {
          return nextBatch;
        }

        setBatch(nextBatch);
        setItems(itemPage?.items || []);
        setError(null);
        setPhase(phaseForBatch(nextBatch));

        if (isTerminal(nextBatch)) {
          clearPolling();
          currentBatchIdRef.current = null;
          persistBatchId(null);
        } else {
          schedulePoll(batchId);
        }
        return nextBatch;
      } catch (refreshError) {
        if (mountedRef.current && currentBatchIdRef.current === batchId) {
          setError(publicError(refreshError));
          schedulePoll(batchId);
        }
        throw refreshError;
      }
    },
    [clearPolling, schedulePoll],
  );

  useEffect(() => {
    pollRef.current = refreshBatch;
  }, [refreshBatch]);

  const resumeImport = useCallback(
    async (batchId) => {
      clearPolling();
      currentBatchIdRef.current = batchId;
      persistBatchId(batchId);
      setError(null);
      return refreshBatch(batchId);
    },
    [clearPolling, refreshBatch],
  );

  const startImport = useCallback(
    async (selectedJobId, selectedFiles) => {
      const files = Array.from(selectedFiles || []);
      clearPolling();
      setError(null);
      setItems([]);
      setPhase("uploading");

      try {
        const created = await candidateImportApi.createImportBatch(selectedJobId, files);
        const batchId = created.batch_id;
        currentBatchIdRef.current = batchId;
        persistBatchId(batchId);
        setBatch({ ...created, id: batchId, job_id: selectedJobId });

        const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
        const uploadedBytes = new Array(files.length).fill(0);
        setUploadProgress({
          loadedBytes: 0,
          totalBytes,
          percent: totalBytes > 0 ? 0 : 100,
        });

        let cursor = 0;
        const uploadWorker = async () => {
          while (cursor < files.length) {
            const index = cursor;
            cursor += 1;
            const file = files[index];
            const descriptor = created.uploads[index];
            if (!descriptor?.upload) {
              throw new Error("La respuesta de carga no contiene credenciales válidas.");
            }

            await candidateImportApi.uploadToPresignedPost(
              file,
              descriptor.upload,
              (loaded) => {
                uploadedBytes[index] = Math.max(
                  0,
                  Math.min(file.size, Number(loaded) || 0),
                );
                const loadedBytes = uploadedBytes.reduce(
                  (sum, value) => sum + value,
                  0,
                );
                setUploadProgress({
                  loadedBytes,
                  totalBytes,
                  percent:
                    totalBytes > 0
                      ? Math.round((loadedBytes / totalBytes) * 100)
                      : 100,
                });
              },
            );
          }
        };

        const workerCount = Math.min(UPLOAD_CONCURRENCY, files.length);
        await Promise.all(
          Array.from({ length: workerCount }, () => uploadWorker()),
        );

        const nextBatch = await candidateImportApi.completeImportBatch(batchId);
        const itemPage = await candidateImportApi.getImportItems(batchId, 1, 100);
        if (!mountedRef.current || currentBatchIdRef.current !== batchId) {
          return nextBatch;
        }

        setUploadProgress(null);
        setBatch(nextBatch);
        setItems(itemPage?.items || []);
        setPhase(phaseForBatch(nextBatch));

        if (isTerminal(nextBatch)) {
          currentBatchIdRef.current = null;
          persistBatchId(null);
          clearPolling();
        } else {
          schedulePoll(batchId);
        }
        return nextBatch;
      } catch (startError) {
        if (mountedRef.current) {
          setUploadProgress(null);
          setError(publicError(startError));
          setPhase("failed");
        }
        throw startError;
      }
    },
    [clearPolling, schedulePoll],
  );

  const reset = useCallback(() => {
    clearPolling();
    currentBatchIdRef.current = null;
    persistBatchId(null);
    setPhase("idle");
    setBatch(null);
    setItems([]);
    setUploadProgress(null);
    setError(null);
  }, [clearPolling]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearPolling();
    };
  }, [clearPolling]);

  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;

    const recover = async () => {
      try {
        const recent = await candidateImportApi.getRecentImports(jobId);
        if (cancelled) return;
        const active = (recent?.items || []).find((candidateBatch) => !isTerminal(candidateBatch));
        if (active) {
          await resumeImport(active.id);
        }
      } catch (recoveryError) {
        if (!cancelled && mountedRef.current) {
          setError(publicError(recoveryError));
        }
      }
    };

    recover();
    return () => {
      cancelled = true;
    };
  }, [jobId, resumeImport]);

  useEffect(() => {
    const onVisibilityChange = () => {
      const batchId = currentBatchIdRef.current;
      if (!batchId) return;
      schedulePoll(batchId);
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [schedulePoll]);

  return {
    phase,
    batch,
    items,
    uploadProgress,
    error,
    startImport,
    resumeImport,
    reset,
  };
}
