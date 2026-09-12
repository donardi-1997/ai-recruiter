import api from "../../api/client.js";

const FALLBACK_CONTENT_TYPE = "application/octet-stream";

export async function createImportBatch(jobId, files) {
  const uploads = Array.from(files).map((file) => ({
    filename: file.name,
    size_bytes: file.size,
    content_type: file.type || FALLBACK_CONTENT_TYPE,
  }));

  const { data } = await api.post("/api/import-batches", {
    job_id: jobId,
    uploads,
  });
  return data;
}

export function uploadToPresignedPost(file, descriptor, onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", descriptor.url);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(event.loaded, event.total);
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
        return;
      }
      reject(new Error(`S3 upload failed: ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("S3 upload failed"));
    xhr.onabort = () => reject(new Error("S3 upload aborted"));

    const form = new FormData();
    Object.entries(descriptor.fields || {}).forEach(([key, value]) => {
      form.append(key, value);
    });
    form.append("file", file);
    xhr.send(form);
  });
}

export async function completeImportBatch(batchId) {
  const { data } = await api.post(`/api/import-batches/${batchId}/complete`);
  return data;
}

export async function getImportBatch(batchId) {
  const { data } = await api.get(`/api/import-batches/${batchId}`);
  return data;
}

export async function getImportItems(batchId, page = 1, pageSize = 100) {
  const { data } = await api.get(`/api/import-batches/${batchId}/items`, {
    params: { page, page_size: pageSize },
  });
  return data;
}

export async function getRecentImports(jobId, limit = 10) {
  const { data } = await api.get("/api/import-batches", {
    params: { job_id: jobId, limit },
  });
  return data;
}
