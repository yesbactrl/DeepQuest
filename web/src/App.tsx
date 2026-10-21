import { Navigate, Route, Routes } from "react-router";

import { Layout } from "./components/Layout";
import { CharacterPage } from "./pages/CharacterPage";
import { LevelsPage } from "./pages/LevelsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DiaryPage } from "./pages/DiaryPage";
import { GoalsPage } from "./pages/GoalsPage";
import { TasksPage } from "./pages/TasksPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="character" element={<CharacterPage />} />
        <Route path="levels" element={<LevelsPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="diary" element={<DiaryPage />} />
        <Route path="goals" element={<GoalsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
