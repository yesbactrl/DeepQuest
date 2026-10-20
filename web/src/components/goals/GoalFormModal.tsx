import {
  ActionIcon,
  Alert,
  Button,
  ColorSwatch,
  Group,
  Modal,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCheck } from "@tabler/icons-react";
import { useState, type FormEvent } from "react";

import { type Direction, type Goal, useCreateGoal, useUpdateGoal } from "../../api/goals";
import { GOAL_COLORS, type GoalColor } from "../../lib/chartTheme";
import { GOAL_ICONS, useGoalColor } from "../../lib/goalLook";

const MAX_TITLE = 80;
const MAX_WHY = 1000;

export type GoalForm =
  | { mode: "create" }
  | { mode: "direction"; parent: Goal }
  | { mode: "edit"; target: Goal | Direction; isDirection: boolean };

function heading(form: GoalForm): string {
  switch (form.mode) {
    case "create":
      return "Новая цель";
    case "direction":
      return `Направление в «${form.parent.title}»`;
    case "edit":
      return form.isDirection ? "Направление" : "Цель";
  }
}

// «Зачем» обязательно у цели: по нему агент оценивает, насколько задача её двигает.
function whyRequired(form: GoalForm): boolean {
  return form.mode === "create" || (form.mode === "edit" && !form.isDirection);
}

// Цвет и иконка стата: цвета — только из палитры графиков, она проверена в обеих темах.
function LookPicker({
  color,
  icon,
  onColor,
  onIcon,
}: {
  color: GoalColor;
  icon: string | null;
  onColor: (color: GoalColor) => void;
  onIcon: (icon: string) => void;
}) {
  const toHex = useGoalColor();
  return (
    <>
      <Stack gap={6}>
        <Text size="sm" fw={500}>
          Цвет стата
        </Text>
        <Group gap="xs">
          {GOAL_COLORS.map((option) => (
            <Tooltip key={option.value} label={option.label}>
              <ColorSwatch
                component="button"
                type="button"
                color={toHex(option.value)}
                aria-label={option.label}
                aria-pressed={color === option.value}
                onClick={() => onColor(option.value)}
                style={{ cursor: "pointer" }}
              >
                {color === option.value && <IconCheck size={14} color="white" />}
              </ColorSwatch>
            </Tooltip>
          ))}
        </Group>
      </Stack>
      <Stack gap={6}>
        <Text size="sm" fw={500}>
          Иконка
        </Text>
        <Group gap={6}>
          {Object.entries(GOAL_ICONS).map(([name, Icon]) => (
            <ActionIcon
              key={name}
              size="lg"
              variant={(icon ?? "target") === name ? "filled" : "default"}
              color={toHex(color)}
              aria-label={`Иконка ${name}`}
              aria-pressed={(icon ?? "target") === name}
              onClick={() => onIcon(name)}
            >
              <Icon size={18} />
            </ActionIcon>
          ))}
        </Group>
      </Stack>
    </>
  );
}

function FormBody({ form, onClose }: { form: GoalForm; onClose: () => void }) {
  const initial = form.mode === "edit" ? form.target : null;
  const goal = form.mode === "edit" && !form.isDirection ? (form.target as Goal) : null;
  const [title, setTitle] = useState(initial?.title ?? "");
  const [why, setWhy] = useState(initial?.why ?? "");
  const [color, setColor] = useState<GoalColor>(goal?.color ?? "blue");
  const [icon, setIcon] = useState<string | null>(goal?.icon ?? null);
  const [growthOnly, setGrowthOnly] = useState(initial?.growth_only ?? false);
  const [touched, setTouched] = useState(false);
  const create = useCreateGoal();
  const update = useUpdateGoal();
  const mutation = form.mode === "edit" ? update : create;

  const titleError =
    touched && !title.trim()
      ? "Как называется?"
      : title.trim().length > MAX_TITLE
        ? `Не длиннее ${MAX_TITLE} символов`
        : null;
  const whyError =
    touched && whyRequired(form) && !why.trim()
      ? "Зачем это тебе? Пара предложений своими словами"
      : why.trim().length > MAX_WHY
        ? `Не длиннее ${MAX_WHY} символов`
        : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (!title.trim() || title.trim().length > MAX_TITLE) return;
    if ((whyRequired(form) && !why.trim()) || why.trim().length > MAX_WHY) return;

    const done = {
      onSuccess: () => {
        notifications.show({ message: "Сохранено", color: "teal" });
        onClose();
      },
    };
    if (form.mode === "edit") {
      const look = goal ? { color, icon: icon ?? "" } : {};
      update.mutate({ id: form.target.id, title, why, growth_only: growthOnly, ...look }, done);
    } else {
      const parent_id = form.mode === "direction" ? form.parent.id : null;
      create.mutate({ title, why: why.trim() || null, parent_id }, done);
    }
  }

  return (
    <form onSubmit={submit}>
      <Stack>
        <TextInput
          label="Название"
          placeholder={form.mode === "direction" ? "Например, «Арбитраж трафика»" : "Например, «Свой доход»"}
          value={title}
          onChange={(event) => setTitle(event.currentTarget.value)}
          error={titleError}
          data-autofocus
        />
        <Textarea
          label="Зачем"
          description={
            whyRequired(form)
              ? "По этому агент поймёт, какие задачи реально двигают цель"
              : "Необязательно"
          }
          placeholder="Пара предложений своими словами"
          autosize
          minRows={3}
          value={why}
          onChange={(event) => setWhy(event.currentTarget.value)}
          error={whyError}
        />
        {goal && <LookPicker color={color} icon={icon} onColor={setColor} onIcon={setIcon} />}
        {form.mode === "edit" && (
          <Switch
            label="XP только за рост"
            description="Обычная работа здесь задачей не считается — например, рабочие часы в найме. Агент спросит, какой это шаг роста: новый скилл, поиск работы получше."
            checked={growthOnly}
            onChange={(event) => setGrowthOnly(event.currentTarget.checked)}
          />
        )}
        {mutation.error && (
          <Alert color="red" variant="light">
            {mutation.error.message}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" loading={mutation.isPending}>
            Сохранить
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function GoalFormModal({ form, onClose }: { form: GoalForm | null; onClose: () => void }) {
  return (
    // Клик мимо окна не закрывает форму: иначе введённый текст молча пропадает.
    <Modal
      opened={form !== null}
      onClose={onClose}
      title={form ? heading(form) : ""}
      size="lg"
      closeOnClickOutside={false}
    >
      {/* Новый ключ на каждую форму: поля сбрасываются, когда открываем другую цель. */}
      {form && (
        <FormBody
          key={form.mode === "edit" ? `edit-${form.target.id}` : form.mode === "direction" ? `dir-${form.parent.id}` : "create"}
          form={form}
          onClose={onClose}
        />
      )}
    </Modal>
  );
}
