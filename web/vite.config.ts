import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/stac': { target: 'http://127.0.0.1:8080', changeOrigin: true, rewrite: (path) => path.replace(/^\/stac/, '') },
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/tiles': { target: 'http://127.0.0.1:8001', changeOrigin: true, rewrite: (path) => path.replace(/^\/tiles/, '') },
    },
  },
  test: { environment: 'node' },
});
