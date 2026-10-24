import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "./client";

export interface AdvisorInfo {
  available: boolean;
  models: Record<string, string>;
  default_model: string;
}

export interface AdvisorChat {
  id: number;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
  // Ответ сейчас пишется.
  running: boolean;
}

export interface AdvisorMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  // Какие инструменты советник вызвал: ["overview", "get_sleep"].
  tools: string[];
  error: string | null;
  latency_ms: number | null;
  created_at: string;
}

export interface AdvisorChatDetail extends AdvisorChat {
  messages: AdvisorMessage[];
}

export interface AdvisorNote {
  id: number;
  text: string;
  created_at: string;
}

const KEY = ["advisor"] as const;

export function useAdvisorInfo() {
  return useQuery({ queryKey: [...KEY, "info"], queryFn: () => api.get<AdvisorInfo>("/advisor") });
}

export function useChats() {
  return useQuery({ queryKey: [...KEY, "chats"], queryFn: () => api.get<AdvisorChat[]>("/advisor/chats") });
}

export function useChat(id: number | null) {
  return useQuery({
    queryKey: [...KEY, "chat", id],
    queryFn: () => api.get<AdvisorChatDetail>(`/advisor/chats/${id}`),
    enabled: id !== null,
  });
}

export function useNotes() {
  return useQuery({ queryKey: [...KEY, "notes"], queryFn: () => api.get<AdvisorNote[]>("/advisor/notes") });
}

function useAdvisorMutation<I, O>(mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({ mutationFn, onSuccess: () => client.invalidateQueries({ queryKey: KEY }) });
}

export function useCreateChat() {
  return useAdvisorMutation((model: string | null) => api.post<AdvisorChat>("/advisor/chats", { model }));
}

export function useEditChat(id: number) {
  return useAdvisorMutation((changes: { title?: string; model?: string }) =>
    api.patch<AdvisorChat>(`/advisor/chats/${id}`, changes),
  );
}

export function useDeleteChat() {
  return useAdvisorMutation((id: number) => api.delete(`/advisor/chats/${id}`));
}

export function useSend(id: number) {
  return useAdvisorMutation((text: string) => api.post<AdvisorMessage>(`/advisor/chats/${id}/messages`, { text }));
}

export function useDeleteNote() {
  return useAdvisorMutation((id: number) => api.delete(`/advisor/notes/${id}`));
}

export interface LiveAnswer {
  text: string;
  tools: string[];
}

// Ответ, который сейчас пишется: читаем поток событий (SSE) и собираем текст по кусочкам.
// Когда ответ готов, перечитываем разговор — готовое сообщение уже в базе.
export function useLiveAnswer(chatId: number | null, running: boolean): LiveAnswer | null {
  const client = useQueryClient();
  const [live, setLive] = useState<LiveAnswer | null>(null);

  useEffect(() => {
    if (chatId === null || !running) {
      setLive(null);
      return;
    }
    const controller = new AbortController();
    let answer: LiveAnswer = { text: "", tools: [] };
    setLive(answer);

    async function read() {
      const response = await fetch(`/api/advisor/chats/${chatId}/stream`, { signal: controller.signal });
      if (!response.body) return;
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          if (!part.startsWith("data: ")) continue;
          const event = JSON.parse(part.slice(6));
          if (event.type === "snapshot") answer = { text: event.text, tools: event.tools };
          else if (event.type === "text") answer = { ...answer, text: answer.text + event.text };
          else if (event.type === "tool") answer = { ...answer, tools: [...answer.tools, event.name] };
          setLive(answer);
        }
      }
      void client.invalidateQueries({ queryKey: KEY });
    }

    read().catch((error: unknown) => {
      if (!controller.signal.aborted) {
        console.error(error);
        void client.invalidateQueries({ queryKey: KEY });
      }
    });
    return () => controller.abort();
  }, [chatId, running, client]);

  return live;
}
