import { ActionIcon, Group, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconMicrophone, IconPlayerStopFilled } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";

import { useTranscribe, useVoiceStatus } from "../api/voice";
import { formatClock, useNow } from "../lib/time";

// Дольше сервер распознавать не станет: на это ушли бы минуты.
const MAX_SECONDS = 5 * 60;

const SUPPORTED =
  typeof window !== "undefined" && "MediaRecorder" in window && !!navigator.mediaDevices?.getUserMedia;

// Расшифровка дописывается к тому, что уже набрано в поле.
export function appendText(current: string, addition: string): string {
  const base = current.trimEnd();
  return base ? `${base} ${addition}` : addition;
}

// Кнопка микрофона у поля ввода: запись → распознавание на сервере → текст в поле.
// Сама ничего не отправляет: расшифровку можно поправить перед отправкой.
export function VoiceButton({
  onText,
  disabled,
  size = 36,
}: {
  onText: (text: string) => void;
  disabled?: boolean;
  size?: number;
}) {
  const status = useVoiceStatus();
  const transcribe = useTranscribe();
  const recorder = useRef<MediaRecorder | null>(null);
  // Поле закрыли посреди записи — расшифровка уже никому не нужна.
  const discard = useRef(false);
  const onTextRef = useRef(onText);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const now = useNow(startedAt !== null);

  useEffect(() => {
    onTextRef.current = onText;
  }, [onText]);

  useEffect(() => {
    discard.current = false;
    return () => {
      discard.current = true;
      recorder.current?.stop();
    };
  }, []);

  useEffect(() => {
    if (startedAt === null) return;
    const timer = window.setTimeout(() => recorder.current?.stop(), MAX_SECONDS * 1000);
    return () => window.clearTimeout(timer);
  }, [startedAt]);

  if (!SUPPORTED || !status.data?.enabled) return null;

  async function start() {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      notifications.show({
        color: "red",
        title: "Нет доступа к микрофону",
        message: "Разреши микрофон для этой страницы в настройках браузера.",
      });
      return;
    }
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    rec.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      recorder.current = null;
      setStartedAt(null);
      const audio = new Blob(chunks, { type: rec.mimeType });
      if (discard.current || audio.size === 0) return;
      transcribe.mutate(audio, {
        onSuccess: (text) => onTextRef.current(text),
        onError: (error) => notifications.show({ color: "red", message: error.message }),
      });
    };
    rec.start();
    recorder.current = rec;
    setStartedAt(Date.now());
  }

  if (startedAt !== null) {
    return (
      <Group gap={6} wrap="nowrap">
        <Text size="sm" c="red" ff="monospace" aria-live="polite">
          {formatClock((now - startedAt) / 1000)}
        </Text>
        <Tooltip label="Остановить и распознать">
          <ActionIcon
            size={size}
            color="red"
            variant="filled"
            aria-label="Остановить запись"
            onClick={() => recorder.current?.stop()}
          >
            <IconPlayerStopFilled size={16} />
          </ActionIcon>
        </Tooltip>
      </Group>
    );
  }

  return (
    <Tooltip label={transcribe.isPending ? "Распознаю…" : "Надиктовать"}>
      <ActionIcon
        size={size}
        variant="default"
        aria-label="Надиктовать голосом"
        loading={transcribe.isPending}
        disabled={disabled}
        onClick={start}
      >
        <IconMicrophone size={18} />
      </ActionIcon>
    </Tooltip>
  );
}
