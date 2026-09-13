import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the app calls a relative "/api" base (same as production behind
// CloudFront). Proxy those calls to the local FastAPI server on :8000 so
// `npm run dev` works without CORS or a hardcoded backend URL.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
