import { Center, ColorSwatch, Group, Loader, ScrollArea, Table, Text, useComputedColorScheme } from "@mantine/core";
import { useMemo } from "react";

import { type ChartConfig, type ChartData, useChartData } from "../../api/dashboard";
import { buildOption, formatValue, isEmpty } from "../../lib/chartOption";
import { chartTheme } from "../../lib/chartTheme";
import { EChart } from "./EChart";

// Табличный вид тех же данных: точные числа, и график не держится на одном цвете.
function DataTable({ config, data }: { config: ChartConfig; data: ChartData }) {
  const theme = chartTheme(useComputedColorScheme("light"));
  return (
    <ScrollArea h={260}>
      <Table striped stickyHeader fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Период</Table.Th>
            {data.series.map((series) => (
              <Table.Th key={series.key}>
                <Group gap={6} wrap="nowrap">
                  <ColorSwatch color={theme.series(series.slot)} size={10} />
                  {series.name}
                </Group>
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {data.labels.map((label, i) => (
            <Table.Tr key={data.buckets[i]}>
              <Table.Td>{label}</Table.Td>
              {data.series.map((series) => (
                <Table.Td key={series.key}>{formatValue(config.metric, series.values[i])}</Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}

export function ChartBody({
  config,
  view,
  height = 260,
}: {
  config: ChartConfig;
  view: "chart" | "table";
  height?: number;
}) {
  const scheme = useComputedColorScheme("light");
  const query = useChartData(config);
  const option = useMemo(
    () => (query.data ? buildOption(config, query.data, chartTheme(scheme)) : null),
    [config, query.data, scheme],
  );

  if (query.isError) {
    return (
      <Center h={height}>
        <Text c="red" size="sm">
          {query.error.message}
        </Text>
      </Center>
    );
  }
  if (!query.data || !option) {
    return (
      <Center h={height}>
        <Loader size="sm" />
      </Center>
    );
  }
  if (isEmpty(query.data)) {
    return (
      <Center h={height}>
        <Text c="dimmed" size="sm">
          За этот период данных пока нет
        </Text>
      </Center>
    );
  }
  return view === "table" ? <DataTable config={config} data={query.data} /> : <EChart option={option} height={height} />;
}
