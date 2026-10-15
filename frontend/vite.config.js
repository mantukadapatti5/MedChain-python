import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // accept connections from outside the container (Docker), not just localhost
    proxy: {
      "/api": {
        // In Docker, the backend is a separate container reachable by its
        // service name ("backend"), not "localhost" — docker-compose.yml
        // sets API_PROXY_TARGET accordingly. Running the frontend locally
        // (outside Docker) keeps working via the localhost default below.
        target: process.env.API_PROXY_TARGET || "http://localhost:5000",
        changeOrigin: true,
      },
    },
  },
});
