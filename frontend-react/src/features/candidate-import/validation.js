const MIB = 1024 * 1024;
const MAX_DOCUMENT_BYTES = 15 * MIB;
const MAX_ARCHIVE_BYTES = 500 * MIB;
const MAX_DIRECT_DOCUMENTS = 500;
const SUPPORTED_EXTENSIONS = new Set([".pdf", ".docx", ".zip"]);

function extensionOf(filename = "") {
  const lower = filename.trim().toLowerCase();
  const dot = lower.lastIndexOf(".");
  return dot >= 0 ? lower.slice(dot) : "";
}

export function validateSelectedFile(file) {
  const extension = extensionOf(file?.name);
  const size = Number(file?.size) || 0;

  if (!SUPPORTED_EXTENSIONS.has(extension)) {
    return `${file?.name || "El archivo"} no es compatible. Usa PDF, DOCX o ZIP.`;
  }
  if (size <= 0) {
    return `${file.name} está vacío y no puede procesarse.`;
  }
  if ((extension === ".pdf" || extension === ".docx") && size > MAX_DOCUMENT_BYTES) {
    return `${file.name} supera el máximo de 15 MB por documento.`;
  }
  if (extension === ".zip" && size > MAX_ARCHIVE_BYTES) {
    return `${file.name} supera el máximo de 500 MB por archivo ZIP.`;
  }
  return null;
}

export function validateSelectedFiles(files) {
  const selected = Array.from(files || []);
  const directDocuments = selected.filter((file) => extensionOf(file.name) !== ".zip");
  if (directDocuments.length > MAX_DIRECT_DOCUMENTS) {
    return "Puedes seleccionar máximo 500 documentos directos por importación.";
  }
  for (const file of selected) {
    const error = validateSelectedFile(file);
    if (error) return error;
  }
  return null;
}
