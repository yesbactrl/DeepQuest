import { Alert, Button, Paper, SimpleGrid, Skeleton, Stack, Text, Title } from "@mantine/core";
import { IconTarget } from "@tabler/icons-react";
import { Link } from "react-router";

import { useCharacter } from "../api/character";
import { CharacterHeader } from "../components/character/CharacterHeader";
import { StatCard } from "../components/character/StatCard";

// Персонаж: цели — это статы, направления — скиллы. XP за задачу идёт сразу в общий
// уровень, стат и скилл; самый отстающий за сезон стат получает бонус.
export function CharacterPage() {
  const character = useCharacter();

  return (
    <Stack gap="lg">
      <Title order={2}>Персонаж</Title>

      {character.isError && (
        <Alert color="red" title="Не удалось загрузить персонажа">
          {character.error.message}
        </Alert>
      )}
      {character.isPending && (
        <>
          <Skeleton h={190} />
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} h={220} />
            ))}
          </SimpleGrid>
        </>
      )}

      {character.data && (
        <>
          <CharacterHeader character={character.data} />
          {character.data.stats.length === 0 ? (
            <Paper withBorder p="xl">
              <Stack align="center" gap="xs">
                <IconTarget size={32} stroke={1.4} />
                <Text c="dimmed" ta="center" maw={460}>
                  Статы персонажа — это твои цели, а скиллы — их направления. Заведи цели, и здесь
                  появятся их уровни.
                </Text>
                <Button component={Link} to="/goals" variant="light">
                  К целям
                </Button>
              </Stack>
            </Paper>
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
              {character.data.stats.map((stat) => (
                <StatCard key={stat.id} stat={stat} weakMult={character.data.weak_stat_mult} />
              ))}
            </SimpleGrid>
          )}
        </>
      )}
    </Stack>
  );
}
