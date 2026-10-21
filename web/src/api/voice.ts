import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { onTranscribed } from "../lib/voiceJobs";
import { api } from "./client";

export function useVoiceStatus() {
  return useQuery({
    queryKey: ["voice"],
    queryFn: () => api.get<{ enabled: boolean }>("/voice"),
    // Включён ли голос, меняется только перезапуском сервера.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
}

export interface Transcript {
  id: number;
  text: string;
  created_at: string;
}

// Последние диктовки: страховка, если расшифровка не дошла до поля.
export function useVoiceHistory(enabled: boolean) {
  const client = useQueryClient();
  useEffect(
    () => onTranscribed(() => void client.invalidateQueries({ queryKey: ["voice-history"] })),
    [client],
  );
  return useQuery({
    queryKey: ["voice-history"],
    queryFn: () => api.get<Transcript[]>("/voice/history"),
    enabled,
  });
}
