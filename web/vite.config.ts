import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// В разработке фронтенд работает на Vite, а /api уходит в бота (он же веб-сервер).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8484", changeOrigin: true },
    },
  },
});
