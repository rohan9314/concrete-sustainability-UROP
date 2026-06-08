import type { ResearchReport } from "./research-types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

export interface QuestionSet {
  id: string;
  label: string;
  description: string;
  question_count: number;
}

export interface QuestionSetsResponse {
  question_sets: QuestionSet[];
  default: string;
}

export interface ResearchJobQueued {
  job_id: string;
  status: "queued";
  subject: string;
  question_set: string;
}

export interface ResearchJobRunning {
  job_id: string;
  status: "running";
  progress: {
    step: string;
    message: string;
  };
}

export interface ResearchJobCompleted {
  job_id: string;
  status: "completed";
  result: ResearchReport;
}

export interface ResearchJobFailed {
  job_id: string;
  status: "failed";
  error: {
    code: string;
    message: string;
  };
}

export type ResearchJobStatus =
  | ResearchJobQueued
  | ResearchJobRunning
  | ResearchJobCompleted
  | ResearchJobFailed;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    ...init,
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const data = await response.json();
      message = data.detail || data.message || message;
    } catch {
      // ignore parse errors
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export async function fetchQuestionSets(): Promise<QuestionSetsResponse> {
  return request<QuestionSetsResponse>("/api/question-sets");
}

export async function startResearch(
  subject: string,
  questionSet: string,
): Promise<ResearchJobQueued> {
  return request<ResearchJobQueued>("/api/research", {
    method: "POST",
    body: JSON.stringify({ subject, question_set: questionSet }),
  });
}

export async function fetchResearchJob(jobId: string): Promise<ResearchJobStatus> {
  return request<ResearchJobStatus>(`/api/research/${jobId}`);
}

export function pollResearchJob(
  jobId: string,
  onUpdate: (job: ResearchJobStatus) => void,
  intervalMs = 2000,
): { promise: Promise<ResearchReport>; cancel: () => void } {
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const cancel = () => {
    cancelled = true;
    if (timer) clearTimeout(timer);
  };

  const promise = new Promise<ResearchReport>((resolve, reject) => {
    const poll = async () => {
      if (cancelled) return;

      try {
        const job = await fetchResearchJob(jobId);
        onUpdate(job);

        if (job.status === "completed") {
          resolve(job.result);
          return;
        }

        if (job.status === "failed") {
          reject(new Error(job.error?.message || "Research job failed."));
          return;
        }

        timer = setTimeout(poll, intervalMs);
      } catch (error) {
        reject(error);
      }
    };

    poll();
  });

  return { promise, cancel };
}

export const PROGRESS_LABELS: Record<string, string> = {
  preparing_question_set: "Preparing Question Set",
  searching_internet: "Searching Internet Sources",
  searching_scientific_literature: "Searching Scientific Literature",
  analyzing_evidence: "Analyzing Evidence",
  generating_report: "Generating Report",
};
