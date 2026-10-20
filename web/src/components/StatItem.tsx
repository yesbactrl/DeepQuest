import { Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";

export function StatItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600} lts={0.3}>
        {label}
      </Text>
      <Text fw={600} size="md">
        {value}
      </Text>
    </Stack>
  );
}
