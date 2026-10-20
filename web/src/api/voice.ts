import { useMutation, useQuery } from "@tanstack/react-query";

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

// Chrome пишет webm, Safari — mp4: сервер разберёт оба, расширение — для логов и отладки.
function extension(type: string): string {
  if (type.includes("ogg")) return "ogg";
  if (type.includes("mp4") || type.includes("aac")) return "m4a";
  return "webm";
}

export function useTranscribe() {
  return useMutation({
    mutationFn: async (audio: Blob) => {
      const form = new FormData();
      form.append("audio", audio, `voice.${extension(audio.type)}`);
      return (await api.upload<{ text: string }>("/voice", form)).text;
    },
  });
}
