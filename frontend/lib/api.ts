import type { ClaimPayload, ClaimResponse } from "./types";

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
