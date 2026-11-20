import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The compiled interface ships inside the Python wheel, served by `roclec view`.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../src/roclec_spec_kit/viewer/static",
    emptyOutDir: true,
    sourcemap: false,
    assetsInlineLimit: 0,
  },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
