import { Alert, Highlight, Kbd, Loader, Stack, Text, TextInput, Title } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconSearch } from "@tabler/icons-react";
import { useState } from "react";
import { useSearchParams } from "react-router";

import type { DiaryEntry } from "../api/diary";
import { useSummary } from "../api/dashboard";
import { useSearch } from "../api/search";
import { EntryCard } from "../components/diary/EntryCard";
import { EntryEditModal } from "../components/diary/EntryEditModal";
import { TaskDrawer } from "../components/tasks/TaskDrawer";
import { TaskList } from "../components/tasks/TaskList";
import { dayLabel } from "../lib/diary";

// Подсветка — по словам запроса, как их ищет сервер: каждое слово отдельно.
const terms = (query: string) => query.trim().split(/\s+/).filter(Boolean);

// Поиск по задачам (название, результат, уточнение, отчёты) и дневнику.
// Запрос живёт в адресе: ⌘K из любой страницы открывает поиск, «назад» возвращает к результатам.
export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const [debounced] = useDebouncedValue(query, 250);
  const search = useSearch(debounced);
  const summary = useSummary();
  const today = summary.data?.streak.today ?? new Date().toISOString().slice(0, 10);
  const [openTaskId, setOpenTaskId] = useState<number | null>(null);
  const [editing, setEditing] = useState<DiaryEntry | null>(null);

  const setQuery = (value: string) => setParams(value ? { q: value } : {}, { replace: true });
  const words = terms(debounced);
  const data = search.data;
  const nothing = data && data.tasks.length === 0 && data.entries.length === 0;

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Title order={2}>Поиск</Title>
        <Text c="dimmed" size="sm">
          По задачам с отчётами и по дневнику. Открыть с любой страницы — <Kbd>⌘</Kbd> + <Kbd>K</Kbd>.
        </Text>
      </Stack>

      <TextInput
        autoFocus
        size="md"
        placeholder="Например, бег или аренда"
        leftSection={<IconSearch size={18} />}
        rightSection={search.isFetching ? <Loader size="xs" /> : null}
        value={query}
        onChange={(e) => setQuery(e.currentTarget.value)}
        aria-label="Что найти"
      />

      {search.isError && (
        <Alert color="red" title="Поиск не удался">
          {search.error.message}
        </Alert>
      )}
      {!query.trim() && (
        <Text c="dimmed" ta="center" py="xl">
          Напиши слово или несколько: найдутся задачи и записи, где есть все они.
        </Text>
      )}
      {query.trim() && nothing && (
        <Text c="dimmed" ta="center" py="xl">
          Ничего не нашлось.
        </Text>
      )}

      {data && data.tasks.length > 0 && (
        <Stack gap="xs">
          <Title order={4}>
            Задачи · {data.tasks.length}
          </Title>
          <TaskList
            tasks={data.tasks.map((hit) => hit.task)}
            loading={false}
            empty=""
            onOpen={setOpenTaskId}
            notes={Object.fromEntries(
              data.tasks
                .filter((hit) => hit.snippet)
                .map((hit) => [
                  hit.task.id,
                  <Text key={hit.task.id} size="xs" lineClamp={2}>
                    <Text span size="xs" c="dimmed">
                      {hit.where}:{" "}
                    </Text>
                    <Highlight component="span" size="xs" highlight={words}>
                      {hit.snippet ?? ""}
                    </Highlight>
                  </Text>,
                ]),
            )}
          />
        </Stack>
      )}

      {data && data.entries.length > 0 && (
        <Stack gap="xs">
          <Title order={4}>
            Дневник · {data.entries.length}
          </Title>
          {data.entries.map((entry) => (
            <Stack key={entry.id} gap={4}>
              <Text size="sm" fw={600}>
                {dayLabel(entry.logical_date, today)}
              </Text>
              <EntryCard entry={entry} onEdit={setEditing} />
            </Stack>
          ))}
        </Stack>
      )}

      <TaskDrawer taskId={openTaskId} onClose={() => setOpenTaskId(null)} onPlanned={() => setOpenTaskId(null)} />
      <EntryEditModal entry={editing} onClose={() => setEditing(null)} />
    </Stack>
  );
}
