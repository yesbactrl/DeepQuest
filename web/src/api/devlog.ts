import { useQuery } from "@tanstack/react-query";

import { api } from "./client";

export type CommitKind = "milestone" | "feature" | "fix" | "polish";

export interface DevCommit {
  hash: string;
  short: string;
  // Время коммита с его поясом: «2026-10-24T22:00:42+07:00».
  at: string;
  subject: string;
  title: string;
  // Код вехи плана: «M0», «W2», «D1.5».
  milestone: string | null;
  area: string | null;
  kind: CommitKind;
  points: string[];
  files: number;
  insertions: number;
  deletions: number;
}

export interface DevDay {
  day: string;
  insertions: number;
  deletions: number;
  // Свежие сверху.
  commits: DevCommit[];
}

export interface Devlog {
  commits: number;
  milestones: number;
  insertions: number;
  days: DevDay[];
}

export function useDevlog() {
  return useQuery({ queryKey: ["devlog"], queryFn: () => api.get<Devlog>("/devlog") });
}
