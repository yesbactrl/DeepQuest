import { useCallback, useSyncExternalStore } from "react";

// Черновики полей ввода в браузере: текст переживает переход на другую страницу и
// обновление вкладки. Ключ — что это за поле: «diary», «plan», «report:12»…
// Хранилище может быть недоступно (приватный режим) — тогда поле просто живёт в памяти.

const PREFIX = "deepquest:draft:";
const listeners = new Map<string, Set<() => void>>();
const memory = new Map<string, string>();

export function readDraft(key: string): string {
  try {
    return localStorage.getItem(PREFIX + key) ?? "";
  } catch {
    return memory.get(key) ?? "";
  }
}

export function writeDraft(key: string, value: string): void {
  try {
    if (value) localStorage.setItem(PREFIX + key, value);
    else localStorage.removeItem(PREFIX + key);
  } catch {
    if (value) memory.set(key, value);
    else memory.delete(key);
  }
  listeners.get(key)?.forEach((listener) => listener());
}

// Расшифровка дописывается к тому, что уже набрано в поле.
export function appendText(current: string, addition: string): string {
  const base = current.trimEnd();
  return base ? `${base} ${addition}` : addition;
}

export function appendDraft(key: string, text: string): void {
  writeDraft(key, appendText(readDraft(key), text));
}

function subscribe(key: string, listener: () => void): () => void {
  const set = listeners.get(key) ?? new Set();
  set.add(listener);
  listeners.set(key, set);
  return () => set.delete(listener);
}

// Состояние поля, привязанное к черновику: как useState, только переживает уход со страницы.
export function useDraft(key: string): [string, (value: string | ((current: string) => string)) => void] {
  const value = useSyncExternalStore(
    useCallback((listener) => subscribe(key, listener), [key]),
    () => readDraft(key),
  );
  const setValue = useCallback(
    (next: string | ((current: string) => string)) =>
      writeDraft(key, typeof next === "function" ? next(readDraft(key)) : next),
    [key],
  );
  return [value, setValue];
}
