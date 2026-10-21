import { notifications } from "@mantine/notifications";
import { useSyncExternalStore } from "react";

import { api } from "../api/client";
import { appendDraft } from "./drafts";

// Распознавание не привязано к странице: запрос живёт здесь, а не в компоненте. Если пока
// он идёт уйти в другой раздел, расшифровка всё равно допишется в черновик своего поля
// и появится там, когда вернёшься. Обновление вкладки запрос обрывает, но сервер доведёт
// распознавание до конца и сохранит текст в «Последние диктовки».

const pending = new Map<string, number>();
const listeners = new Set<() => void>();
const historyListeners = new Set<() => void>();

function notify() {
  listeners.forEach((listener) => listener());
}

// Chrome пишет webm, Safari — mp4: сервер разберёт оба, расширение — для логов и отладки.
function extension(type: string): string {
  if (type.includes("ogg")) return "ogg";
  if (type.includes("mp4") || type.includes("aac")) return "m4a";
  return "webm";
}

export async function transcribeInto(draftKey: string, audio: Blob): Promise<void> {
  pending.set(draftKey, (pending.get(draftKey) ?? 0) + 1);
  notify();
  try {
    const form = new FormData();
    form.append("audio", audio, `voice.${extension(audio.type)}`);
    const { text } = await api.upload<{ text: string }>("/voice", form);
    appendDraft(draftKey, text);
    historyListeners.forEach((listener) => listener());
  } catch (error) {
    notifications.show({
      color: "red",
      message: error instanceof Error ? error.message : "Не удалось распознать запись",
    });
  } finally {
    const left = (pending.get(draftKey) ?? 1) - 1;
    if (left > 0) pending.set(draftKey, left);
    else pending.delete(draftKey);
    notify();
  }
}

export function useTranscribing(draftKey: string): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => pending.has(draftKey),
  );
}

// Подписка на новые расшифровки — чтобы освежить «Последние диктовки».
export function onTranscribed(listener: () => void): () => void {
  historyListeners.add(listener);
  return () => historyListeners.delete(listener);
}
