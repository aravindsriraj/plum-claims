import type { ClaimPayload, ClaimResponse, StageEvent, StreamEvent } from "./types";

// Server-side calls go through the Next rewrite (/api/* -> backend).
// Client components call this; it runs in the browser, so we use the
// same-origin /api path.
export async function submitClaim(payload: ClaimPayload): Promise<ClaimResponse> {
  const res = await fetch("/api/claims", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Claim submission failed (${res.status}): ${text}`);
  }
  return res.json();
}

/**
 * Submit a claim with live progress: POSTs to /claims/stream and invokes
 * onStage for each pipeline stage event as it arrives (NDJSON over the same
 * POST). Resolves with the final ClaimResponse.
 *
 * Fallback: if the stream cannot be OPENED (network error, non-2xx before
 * any bytes), we silently retry via the plain POST — claims are stateless,
 * so the retry is safe. A failure MID-stream throws instead of double-
 * processing.
 */
export async function submitClaimStream(
  payload: ClaimPayload,
  onStage: (event: StageEvent) => void
): Promise<ClaimResponse> {
  let res: Response;
  try {
    res = await fetch("/api/claims/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/x-ndjson",
      },
      body: JSON.stringify(payload),
    });
  } catch {
    return submitClaim(payload); // stream never opened — safe to retry plainly
  }
  if (!res.ok || !res.body) {
    return submitClaim(payload); // same: nothing was processed on our behalf
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ClaimResponse | null = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? ""; // last chunk may be an incomplete line
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as StreamEvent;
      if (event.type === "stage") onStage(event);
      else result = event.response;
    }
  }
  if (buffer.trim()) {
    const event = JSON.parse(buffer) as StreamEvent;
    if (event.type === "stage") onStage(event);
    else result = event.response;
  }
  if (!result) throw new Error("Stream ended without a result");
  return result;
}

export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.split(",")[1]); // strip data:*/*;base64, prefix
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
