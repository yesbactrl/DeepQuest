import { Button, Group, Modal, SegmentedControl, Stack, Text, TextInput } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useState } from "react";

import {
  type SleepInput,
  type SleepKind,
  type SleepSession,
  useAddSleep,
  useDeleteSleep,
  useEditSleep,
} from "../../api/sleep";
import { hours, wallMinutes } from "../../lib/sleep";
import { ScorePicker } from "../diary/Spheres";

// Что открыть в форме: существующий сон или новый с подставленным временем.
export type SleepDraft = { session: SleepSession } | { input: SleepInput };

function initial(draft: SleepDraft): SleepInput {
  if ("input" in draft) return draft.input;
  const { kind, start, end, quality, note } = draft.session;
  return { kind, start: start.slice(0, 16), end: end.slice(0, 16), quality, note };
}

function Body({ draft, onClose }: { draft: SleepDraft; onClose: () => void }) {
  const existing = "session" in draft ? draft.session : null;
  const [value, setValue] = useState<SleepInput>(() => initial(draft));
  const add = useAddSleep();
  const edit = useEditSleep(existing?.id ?? 0);
  const remove = useDeleteSleep(existing?.id ?? 0);
  const save = existing ? edit : add;
  const set = (changes: Partial<SleepInput>) => setValue({ ...value, ...changes });
  const minutes = value.start && value.end ? wallMinutes(value.end) - wallMinutes(value.start) : 0;

  const submit = () =>
    save.mutate(
      { ...value, note: value.note?.trim() || null },
      {
        onSuccess: onClose,
        onError: (error) => notifications.show({ color: "red", message: error.message }),
      },
    );

  const confirmDelete = () =>
    modals.openConfirmModal({
      title: "Удалить запись сна?",
      labels: { confirm: "Удалить", cancel: "Отмена" },
      confirmProps: { color: "red" },
      onConfirm: () => remove.mutate(undefined, { onSuccess: onClose }),
    });

  return (
    <Stack>
      <SegmentedControl
        value={value.kind}
        onChange={(kind) => set({ kind: kind as SleepKind })}
        data={[
          { value: "night", label: "🌙 Ночной сон" },
          { value: "nap", label: "☀️ Дневной сон" },
        ]}
      />
      <Group grow align="flex-start">
        <TextInput
          type="datetime-local"
          label="Лёг"
          value={value.start}
          onChange={(e) => set({ start: e.currentTarget.value })}
        />
        <TextInput
          type="datetime-local"
          label="Проснулся"
          value={value.end}
          onChange={(e) => set({ end: e.currentTarget.value })}
        />
      </Group>
      <Text size="sm" c={minutes > 0 ? "dimmed" : "red"}>
        {minutes > 0 ? `Сон: ${hours(minutes)}` : "Проснуться можно только после того, как лёг"}
      </Text>
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Как выспался
        </Text>
        <ScorePicker value={value.quality} onChange={(quality) => set({ quality })} />
      </Stack>
      <TextInput
        label="Заметка"
        placeholder="Например, кофе вечером, шумно, снились кошмары"
        value={value.note ?? ""}
        onChange={(e) => set({ note: e.currentTarget.value })}
      />
      <Group justify="space-between">
        {existing ? (
          <Button variant="subtle" color="red" onClick={confirmDelete} loading={remove.isPending}>
            Удалить
          </Button>
        ) : (
          <span />
        )}
        <Group>
          <Button variant="default" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={submit} loading={save.isPending} disabled={minutes <= 0}>
            Сохранить
          </Button>
        </Group>
      </Group>
    </Stack>
  );
}

export function SleepForm({ draft, onClose }: { draft: SleepDraft | null; onClose: () => void }) {
  const title = draft && "session" in draft ? "Сон" : "Записать сон";
  return (
    <Modal opened={draft !== null} onClose={onClose} title={title} closeOnClickOutside={false}>
      {draft && <Body draft={draft} onClose={onClose} />}
    </Modal>
  );
}
