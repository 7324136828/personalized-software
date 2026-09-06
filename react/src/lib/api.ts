/** API helpers for server-backed free-text Q&A sessions. */

export interface QASessionResponse {
  id: string;
  question: string;
  answer: string;
}

export interface QASession {
  id: string;
  qaFile: string;
  title: string;
  status: "in_progress" | "completed";
  currentQuestion: number;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
  responses: QASessionResponse[];
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload.error) message = payload.error;
    } catch {
      // Keep the status-based message for non-JSON errors.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export function createQASession(
  qaFile: string,
  title: string,
  questions: { id: string; question: string }[],
): Promise<QASession> {
  return requestJson<QASession>("/api/qa/sessions", {
    method: "POST",
    body: JSON.stringify({ qaFile, title, questions }),
  });
}

export function getQASession(sessionId: string): Promise<QASession> {
  return requestJson<QASession>(`/api/qa/sessions/${encodeURIComponent(sessionId)}`);
}

export function updateQASession(
  sessionId: string,
  answers: string[],
  currentQuestion: number,
  completed: boolean,
): Promise<QASession> {
  return requestJson<QASession>(`/api/qa/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PUT",
    body: JSON.stringify({ answers, currentQuestion, completed }),
  });
}

export function qaDownloadUrl(sessionId: string): string {
  return `/api/qa/sessions/${encodeURIComponent(sessionId)}/download`;
}
