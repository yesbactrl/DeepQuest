import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "./client";
import type { DiaryEntry } from "./diary";
import type { Task } from "./tasks";

export interface TaskHit {
  task: Task;
  // Где нашлось и кусок текста вокруг; null — нашлось в названии.
  where: string | null;
  snippet: string | null;
}

export interface SearchResult {
  tasks: TaskHit[];
  entries: DiaryEntry[];
}

export function useSearch(query: string) {
  const q = query.trim();
  return useQuery({
    // Ключ начинается с «diary»: правка записи прямо из поиска обновит и результаты.
    queryKey: ["diary", "search", q],
    queryFn: () => api.get<SearchResult>(`/search?q=${encodeURIComponent(q)}`),
    enabled: q.length > 0,
    placeholderData: keepPreviousData,
  });
}
