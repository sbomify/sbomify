import path from 'path'
import { resolve } from 'path'
import fs from 'fs'
import { defineConfig } from 'vite'
import { config } from 'dotenv'
import tailwindcss from '@tailwindcss/vite'

const envFilePath = path.join(__dirname, '.env')

if(fs.existsSync(envFilePath)) {
  config({ path: path.join(__dirname, '.env') })
}

// https://vitejs.dev/config/
export default defineConfig({
  base: '/dist/',  // Keep leading slash for Vite, Django will prepend STATIC_URL automatically
  // Copied verbatim into outDir, so templates keep linking static/dist/manifest.webmanifest.
  publicDir: resolve('./sbomify/assets/public'),
  css: {
    devSourcemap: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    }
  },
  optimizeDeps: {
    include: ['license-expressions'],
    esbuildOptions: {
      target: 'esnext'
    }
  },
  ssr: {
    noExternal: ['license-expressions']
  },
  plugins: [
    tailwindcss(),
  ],
  build: {
    target: 'esnext',
    outDir: resolve('./sbomify/static/dist/'),
    emptyOutDir: true,
    assetsDir: 'assets',
    manifest: 'manifest.json',
    rollupOptions: {
      input: {
        core: resolve('./sbomify/apps/core/js/main.ts'),
        teams: resolve('./sbomify/apps/teams/js/main.ts'),
        documents: resolve('./sbomify/apps/documents/js/main.ts'),
        plugins: resolve('./sbomify/apps/plugins/js/main.ts'),
        htmxBundle: resolve('./sbomify/apps/core/js/htmx-bundle.ts'),
        // Tailwind CSS entry (source outside static to avoid collectstatic processing)
        tailwind: resolve('./sbomify/assets/css/tailwind.src.css'),
      },
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5170,
    // fs events don't cross the macOS↔Docker bind mount, so poll for changes.
    // Without this, Tailwind never re-scans edited templates until a container restart.
    watch: {
      usePolling: true,
      interval: 100,
    },
    cors: true,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization'
    }
  }
})
