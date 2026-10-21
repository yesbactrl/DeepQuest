import { ActionIcon, Group, Menu, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconHistory, IconMicrophone, IconPlayerStopFilled } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";

import { useVoiceHistory, useVoiceStatus } from "../api/voice";
import { appendDraft } from "../lib/drafts";
import { formatClock, formatTime, useNow } from "../lib/time";
import { transcribeInto, useTranscribing } from "../lib/voiceJobs";

// Дольше сервер распознавать не станет: на это ушли бы минуты.
const MAX_SECONDS = 5 * 60;

const SUPPORTED =
  typeof window !== "undefined" && "MediaRecorder" in window && !!navigator.mediaDevices?.getUserMedia;

// «Последние диктовки»: вставить любую из недавних расшифровок в это поле.
function VoiceHistory({ draftKey, size }: { draftKey: string; size: number }) {
  const [opened, setOpened] = useState(false);
  const history = useVoiceHistory(opened);
  return (
    <Menu opened={opened} onChange={setOpened} position="bottom-end" withinPortal width={320}>
      <Menu.Target>
        <Tooltip label="Последние диктовки" disabled={opened}>
          <ActionIcon size={size} variant="subtle" color="gray" aria-label="Последние диктовки">
            <IconHistory size={16} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Последние диктовки — вставить в поле</Menu.Label>
        {history.isPending && <Menu.Item disabled>Загружаю…</Menu.Item>}
        {history.data?.length === 0 && <Menu.Item disabled>Пока пусто</Menu.Item>}
        {history.data?.map((item) => (
          <Menu.Item key={item.id} onClick={() => appendDraft(draftKey, item.text)}>
            <Text size="xs" c="dimmed">
              {formatTime(item.created_at)}
            </Text>
            <Text size="sm" lineClamp={2}>
              {item.text}
            </Text>
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}

// Кнопка микрофона у поля ввода: запись → распознавание на сервере → текст в черновик поля
// (`draftKey`). Сама ничего не отправляет: расшифровку можно поправить перед отправкой.
// Уход со страницы запись не теряет: она останавливается и всё равно распознаётся.
export function VoiceButton({
  draftKey,
  disabled,
  size = 36,
}: {
  draftKey: string;
  disabled?: boolean;
  size?: number;
}) {
  const status = useVoiceStatus();
  const transcribing = useTranscribing(draftKey);
  const recorder = useRef<MediaRecorder | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const now = useNow(startedAt !== null);

  // Ушли со страницы посреди записи — останавливаем, и запись уходит на распознавание.
  useEffect(() => () => recorder.current?.stop(), []);

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
      if (audio.size > 0) void transcribeInto(draftKey, audio);
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
    <Group gap={2} wrap="nowrap">
      <Tooltip label={transcribing ? "Распознаю — можно уйти со страницы, текст не пропадёт" : "Надиктовать"}>
        <ActionIcon
          size={size}
          variant="default"
          aria-label="Надиктовать голосом"
          loading={transcribing}
          disabled={disabled}
          onClick={start}
        >
          <IconMicrophone size={18} />
        </ActionIcon>
      </Tooltip>
      <VoiceHistory draftKey={draftKey} size={size} />
    </Group>
  );
}
