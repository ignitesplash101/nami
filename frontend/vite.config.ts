import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    // The lazily-loaded Plotly partial (plotly.js-finance-dist-min via
    // PlotLazy) is a single ~1.2MB pre-minified chunk by design. Anything
    // above this limit means the FULL plotly bundle leaked back in — treat
    // the warning as a build regression.
    chunkSizeWarningLimit: 1300
  },
  server: {
    proxy: {
      "/api": "http://localhost:8080"
    }
  }
});
