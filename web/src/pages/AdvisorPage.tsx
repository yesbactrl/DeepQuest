import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Drawer,
  Group,
  Loader,
  Menu,
  NavLink,
  Paper,
  ScrollArea,
  Select,
  Stack,
  Text,
  Textarea,
  Title,
  Tooltip,
  Typography,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { IconBrain, IconDots, IconPlus, IconSend, IconTrash } from "@tabler/icons-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import Markdown from "react-markdown";
import { useSearchParams } from "react-router";
import remarkGfm from "remark-gfm";

import {
  type AdvisorMessage,
  type LiveAnswer,
  useAdvisorInfo,
  useChat,
  useChats,
  useCreateChat,
  useDeleteChat,
  useDeleteNote,
  useEditChat,
  useLiveAnswer,
  useNotes,
  useSend,
} from "../api/advisor";
import { api } from "../api/client";
import { VoiceButton } from "../components/VoiceButton";
import { useDraft } from "../lib/drafts";

// Что советник делал по пути к ответу — по-человечески.
const TOOL_LABELS: Record<string, string> = {
  overview: "сводка",
  list_goals: "цели",
  list_tasks: "задачи",
  get_task: "карточка задачи",
  get_plan: "план",
  get_diary: "дневник",
  get_sleep: "сон",
  get_review: "итоги",
  search: "поиск",
  create_task: "завёл задачу",
  schedule_task: "поставил в план",
  add_diary_entry: "записал в дневник",
  log_sleep: "записал сон",
  remember: "запомнил",
  forget: "забыл",
};

const SUGGESTIONS = [
  "Что у меня сегодня и с чего начать?",
  "Есть два свободных часа — что лучше сделать?",
  "Как у меня со сном за последнюю неделю и что с этим делать?",
  "Подведи итоги недели: что получилось, что буксует?",
];

function Tools({ tools }: { tools: string[] }) {
  const unique = [...new Set(tools)];
  if (unique.length === 0) return null;
  return (
    <Group gap={4}>
      {unique.map((tool) => (
        <Badge key={tool} size="xs" variant="light" color="gray" tt="none">
          {TOOL_LABELS[tool] ?? tool}
        </Badge>
      ))}
    </Group>
  );
}

function AssistantText({ text }: { text: string }) {
  return (
    <Typography fz="sm" style={{ overflowWrap: "anywhere" }}>
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </Typography>
  );
}

function Message({ message }: { message: AdvisorMessage }) {
  if (message.role === "user") {
    return (
      <Group justify="flex-end">
        <Paper px="md" py="xs" radius="lg" bg="var(--mantine-color-violet-light)" maw="80%">
          <Text size="sm" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
            {message.text}
          </Text>
        </Paper>
      </Group>
    );
  }
  return (
    <Stack gap={4} maw="90%">
      <Tools tools={message.tools} />
      {message.text && <AssistantText text={message.text} />}
      {message.error && (
        <Alert color="red" variant="light" p="xs">
          <Text size="sm">{message.error}</Text>
        </Alert>
      )}
    </Stack>
  );
}

function Live({ answer }: { answer: LiveAnswer }) {
  return (
    <Stack gap={4} maw="90%">
      <Tools tools={answer.tools} />
      {answer.text ? (
        <AssistantText text={answer.text} />
      ) : (
        <Group gap="xs">
          <Loader size="xs" type="dots" />
          <Text size="sm" c="dimmed">
            {answer.tools.length ? "смотрит данные…" : "думает…"}
          </Text>
        </Group>
      )}
    </Stack>
  );
}

function NotesDrawer({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const notes = useNotes();
  const remove = useDeleteNote();
  return (
    <Drawer opened={opened} onClose={onClose} title="Что советник помнит" position="right">
      <Stack gap="xs">
        <Text size="sm" c="dimmed">
          Советник сам записывает сюда устойчивое о тебе — предпочтения и договорённости — и видит
          это в каждом новом разговоре. Устаревшее можно убрать.
        </Text>
        {notes.data?.length === 0 && <Text c="dimmed">Пока ничего.</Text>}
        {notes.data?.map((note) => (
          <Paper key={note.id} withBorder p="xs">
            <Group justify="space-between" wrap="nowrap" align="flex-start">
              <Text size="sm">{note.text}</Text>
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label="Забыть"
                onClick={() => remove.mutate(note.id)}
              >
                <IconTrash size={14} />
              </ActionIcon>
            </Group>
          </Paper>
        ))}
      </Stack>
    </Drawer>
  );
}

function ChatList({ selected, onSelect, onNew }: { selected: number | null; onSelect: (id: number) => void; onNew: () => void }) {
  const chats = useChats();
  const remove = useDeleteChat();
  const confirmDelete = (id: number, title: string) =>
    modals.openConfirmModal({
      title: "Удалить разговор?",
      children: <Text size="sm">«{title}» пропадёт вместе с сообщениями. Память советника останется.</Text>,
      labels: { confirm: "Удалить", cancel: "Отмена" },
      confirmProps: { color: "red" },
      onConfirm: () => remove.mutate(id, { onSuccess: () => id === selected && onNew() }),
    });
  return (
    <Stack gap={4}>
      <Button leftSection={<IconPlus size={16} />} variant="light" onClick={onNew} mb="xs">
        Новый разговор
      </Button>
      {chats.data?.map((chat) => (
        <NavLink
          key={chat.id}
          active={chat.id === selected}
          label={<Text size="sm" truncate>{chat.title}</Text>}
          description={new Date(chat.updated_at).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}
          onClick={() => onSelect(chat.id)}
          leftSection={chat.running ? <Loader size={12} /> : null}
          rightSection={
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  size="sm"
                  aria-label="Действия с разговором"
                  onClick={(e) => e.stopPropagation()}
                >
                  <IconDots size={14} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown onClick={(e) => e.stopPropagation()}>
                <Menu.Item color="red" leftSection={<IconTrash size={14} />} onClick={() => confirmDelete(chat.id, chat.title)}>
                  Удалить
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          }
          style={{ borderRadius: 6 }}
        />
      ))}
    </Stack>
  );
}

// На узком экране список разговоров — выпадающим списком над чатом.
function ChatSelect({ selected, onSelect }: { selected: number | null; onSelect: (id: number) => void }) {
  const chats = useChats();
  if (!chats.data?.length) return null;
  return (
    <Select
      size="xs"
      placeholder="Прошлые разговоры"
      data={chats.data.map((c) => ({ value: String(c.id), label: c.title }))}
      value={selected === null ? null : String(selected)}
      onChange={(value) => value && onSelect(Number(value))}
      aria-label="Прошлые разговоры"
    />
  );
}

function Composer({
  chatId,
  busy,
  onSend,
}: {
  chatId: number | null;
  busy: boolean;
  onSend: (text: string) => Promise<boolean>;
}) {
  const draftKey = `advisor-${chatId ?? "new"}`;
  const [text, setText] = useDraft(draftKey);
  const [sending, setSending] = useState(false);

  async function submit() {
    const value = text.trim();
    if (!value || busy || sending) return;
    setSending(true);
    if (await onSend(value)) setText("");
    setSending(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter — отправить, Shift+Enter — новая строка.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <Group gap="xs" align="flex-end" wrap="nowrap">
      <Textarea
        style={{ flex: 1 }}
        autosize
        minRows={1}
        maxRows={8}
        placeholder={busy ? "Советник отвечает…" : "Спроси о задачах, плане, сне, самочувствии…"}
        value={text}
        onChange={(e) => setText(e.currentTarget.value)}
        onKeyDown={onKeyDown}
        aria-label="Сообщение советнику"
      />
      <VoiceButton draftKey={draftKey} />
      <ActionIcon
        size={36}
        variant="filled"
        color="violet"
        aria-label="Отправить"
        loading={sending}
        disabled={busy || !text.trim()}
        onClick={() => void submit()}
      >
        <IconSend size={18} />
      </ActionIcon>
    </Group>
  );
}

// Советник: разговоры с Claude, у которого есть доступ к данным DeepQuest. Каждый разговор —
// свой контекст; ответ пишется в фоне и не теряется, если уйти со страницы.
export function AdvisorPage() {
  const [params, setParams] = useSearchParams();
  const chatId = params.get("chat") ? Number(params.get("chat")) : null;
  const info = useAdvisorInfo();
  const client = useQueryClient();
  const chat = useChat(chatId);
  const create = useCreateChat();
  const send = useSend(chatId ?? 0);
  const edit = useEditChat(chatId ?? 0);
  const live = useLiveAnswer(chatId, chat.data?.running ?? false);
  const [newModel, setNewModel] = useState<string | null>(null);
  const [notesOpened, setNotesOpened] = useState(false);
  const wide = useMediaQuery("(min-width: 62em)");
  // Отступ страницы на телефоне меньше (см. Layout): высота чата считается от него.
  const phone = useMediaQuery("(max-width: 48em)");
  const bottom = useRef<HTMLDivElement>(null);

  const select = (id: number | null) => setParams(id === null ? {} : { chat: String(id) });
  const model = chat.data?.model ?? newModel ?? info.data?.default_model ?? null;

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [chat.data?.messages.length, live?.text, live?.tools.length]);

  async function onSend(text: string): Promise<boolean> {
    try {
      let id = chatId;
      if (id === null) {
        id = (await create.mutateAsync(newModel)).id;
        await api.post(`/advisor/chats/${id}/messages`, { text });
        // Название разговора — первые слова вопроса: обновляем список сразу.
        void client.invalidateQueries({ queryKey: ["advisor"] });
        select(id);
      } else {
        await send.mutateAsync(text);
      }
      return true;
    } catch (error) {
      notifications.show({ color: "red", message: (error as Error).message });
      return false;
    }
  }

  function changeModel(value: string | null) {
    if (!value) return;
    if (chatId === null) setNewModel(value);
    else edit.mutate({ model: value });
  }

  if (info.data && !info.data.available) {
    return (
      <Alert color="yellow" title="Советник недоступен">
        Не найден Claude Code (`claude`). Установи его и войди по подписке, потом перезапусти DeepQuest.
      </Alert>
    );
  }

  const messages = chat.data?.messages ?? [];
  const busy = chat.data?.running ?? false;

  return (
    <Group
      align="stretch"
      gap="lg"
      wrap="nowrap"
      h={`calc(100dvh - 56px - 2 * var(--mantine-spacing-${phone ? "md" : "lg"}))`}
    >
      {wide && (
        <Box w={260} style={{ flexShrink: 0 }}>
          <ScrollArea h="100%">
            <ChatList selected={chatId} onSelect={select} onNew={() => select(null)} />
          </ScrollArea>
        </Box>
      )}
      <Stack style={{ flex: 1, minWidth: 0 }} gap="sm">
        <Group justify="space-between" wrap="nowrap">
          {/* На узком экране название разговора видно в выборе разговора ниже. */}
          {wide && (
            <Title order={3} lineClamp={1}>
              {chat.data?.title ?? "Советник"}
            </Title>
          )}
          <Group gap="xs" wrap="nowrap" ml={wide ? undefined : "auto"}>
            {!wide && (
              <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => select(null)}>
                Новый
              </Button>
            )}
            {info.data && (
              <Select
                size="xs"
                w={170}
                data={Object.entries(info.data.models).map(([value, label]) => ({ value, label }))}
                value={model}
                onChange={changeModel}
                allowDeselect={false}
                aria-label="Модель"
              />
            )}
            <Tooltip label="Что советник помнит">
              <ActionIcon variant="default" size="lg" aria-label="Память советника" onClick={() => setNotesOpened(true)}>
                <IconBrain size={18} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
        {!wide && <ChatSelect selected={chatId} onSelect={select} />}

        <Paper withBorder style={{ flex: 1, minHeight: 0 }}>
          <ScrollArea h="100%" p="md">
            <Stack gap="lg">
              {chatId === null && (
                <Stack gap="sm" py="lg">
                  <Text c="dimmed">
                    Советник видит твои цели, задачи, план, дневник, сон и итоги и может завести задачу,
                    поставить её на день, записать в дневник или сон. О чём поговорим?
                  </Text>
                  <Group gap="xs">
                    {SUGGESTIONS.map((suggestion) => (
                      <Button
                        key={suggestion}
                        size="xs"
                        variant="default"
                        h="auto"
                        py={6}
                        // Длинная подсказка переносится, а не обрезается на телефоне.
                        styles={{ label: { whiteSpace: "normal", textAlign: "left" } }}
                        onClick={() => void onSend(suggestion)}
                      >
                        {suggestion}
                      </Button>
                    ))}
                  </Group>
                </Stack>
              )}
              {messages.map((message) => (
                <Message key={message.id} message={message} />
              ))}
              {busy && live && <Live answer={live} />}
              <div ref={bottom} />
            </Stack>
          </ScrollArea>
        </Paper>

        <Composer chatId={chatId} busy={busy} onSend={onSend} />
      </Stack>
      <NotesDrawer opened={notesOpened} onClose={() => setNotesOpened(false)} />
    </Group>
  );
}
