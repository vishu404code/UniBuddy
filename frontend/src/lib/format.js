export const TICKET_STATUS_LABEL = {
  submitted: "Submitted",
  assigned: "Assigned",
  in_progress: "In progress",
  resolved: "Resolved",
};

export const DOCUMENT_PROCESSING_LABEL = {
  pending: "Queued",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
};

export const PUBLICATION_LABEL = { draft: "Draft", published: "Published", archived: "Archived" };

export const MAX_UPLOAD_MB = 20;

export function formatDate(iso) {
  return iso ? new Date(iso).toLocaleString() : "";
}

export function formatCitation(citation) {
  return citation.page ? `${citation.title}, page ${citation.page}` : `${citation.title} (page not recorded)`;
}

// Client-side convenience only. The server validates the file again.
export function fileProblem(file) {
  if (!file) return "Choose a PDF file.";
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "Only PDF files can be uploaded.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `The file is larger than ${MAX_UPLOAD_MB} MB.`;
  return null;
}

export function isStillProcessing(documents) {
  return documents.some((d) => d.processing_status === "pending" || d.processing_status === "processing");
}
