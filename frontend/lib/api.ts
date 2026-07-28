import type {
  ClaimPayload,
  ClaimResponse,
  InterruptEvent,
  StageEvent,
  StreamEvent,
} from "./types";

export async function submitClaim(payload: ClaimPayload): Promise<ClaimResponse> {
  const res = await fetch("/api/claims", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await formatHttpError("Claim submission failed", res));
  }
  return res.json();
}

export async function resumeClaim(
  claimId: string,
  action: "approve" | "reject",
  note?: string
): Promise<ClaimResponse> {
  const res = await fetch(`/api/claims/${claimId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, note }),
  });
  if (!res.ok) {
    throw new Error(await formatHttpError("Resume failed", res));
  }
  return res.json();
}

async function formatHttpError(prefix: string, res: Response): Promise<string> {
  const text = await res.text();
  try {
    const json = JSON.parse(text) as { detail?: unknown };
    if (typeof json.detail === "string") return `${prefix} (${res.status}): ${json.detail}`;
  } catch {
    /* not JSON */
  }
  if (text.trimStart().startsWith("<!DOCTYPE") || text.includes("<html")) {
    return `${prefix} (${res.status}): API proxy returned an HTML page — is the backend up and API_URL set?`;
  }
  return `${prefix} (${res.status}): ${text.slice(0, 300)}`;
}

/**
 * Submit a claim with live progress. Resolves with the final ClaimResponse
 * and optionally surfaces an HITL interrupt payload when the graph pauses.
 */
export async function submitClaimStream(
  payload: ClaimPayload,
  onStage: (event: StageEvent) => void,
  onInterrupt?: (event: InterruptEvent) => void
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
    return submitClaim(payload);
  }
  if (!res.ok || !res.body) {
    return submitClaim(payload);
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
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as StreamEvent;
      if (event.type === "stage") onStage(event);
      else if (event.type === "interrupt") onInterrupt?.(event);
      else result = event.response;
    }
  }
  if (buffer.trim()) {
    const event = JSON.parse(buffer) as StreamEvent;
    if (event.type === "stage") onStage(event);
    else if (event.type === "interrupt") onInterrupt?.(event);
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
      resolve(result.split(",")[1]);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
