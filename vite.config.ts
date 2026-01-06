import path from 'path'
import { resolve } from 'path'
import fs from 'fs'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { config } from 'dotenv'
import { VitePWA } from 'vite-plugin-pwa'

const envFilePath = path.join(__dirname, '.env')

if(fs.existsSync(envFilePath)) {
  config({ path: path.join(__dirname, '.env') })
}

// https://vitejs.dev/config/
export default defineConfig({
  base: '/dist/',  // Keep leading slash for Vite, Django will prepend STATIC_URL automatically
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
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'sbomify',
        short_name: 'sbomify',
        description: 'Software Bill of Materials management platform',
        theme_color: '#2563eb',
        background_color: '#ffffff',
        display: 'standalone',
        start_url: '/',
        icons: [
          {
            src: 'img/favicons/favicon-16x16.png',
            sizes: '16x16',
            type: 'image/png'
          },
          {
            src: 'img/favicons/favicon-32x32.png',
            sizes: '32x32',
            type: 'image/png'
          },
          {
            src: 'img/favicons/apple-touch-icon.png',
            sizes: '180x180',
            type: 'image/png'
          },
          {
            src: 'img/favicons/android-chrome-192x192.png',
            sizes: '192x192',
            type: 'image/png'
          },
          {
            src: 'img/favicons/android-chrome-512x512.png',
            sizes: '512x512',
            type: 'image/png'
          },
          {
            src: 'img/favicons/favicon.svg',
            sizes: 'any',
            type: 'image/svg+xml'
          }
        ]
      },
      includeAssets: ['manifest.webmanifest']
    })
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
        sboms: resolve('./sbomify/apps/sboms/js/main.ts'),
        teams: resolve('./sbomify/apps/teams/js/main.ts'),
        billing: resolve('./sbomify/apps/billing/js/main.ts'),
        documents: resolve('./sbomify/apps/documents/js/main.ts'),
        vulnerability_scanning: resolve('./sbomify/apps/vulnerability_scanning/js/main.ts'),
        plugins: resolve('./sbomify/apps/plugins/js/main.ts'),
        alerts: resolve('./sbomify/apps/core/js/alerts-global.ts'),
        djangoMessages: resolve('./sbomify/apps/core/js/django-messages.ts'),
        htmxBundle: resolve('./sbomify/apps/core/js/htmx-bundle.ts'),
      },
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5170,
    cors: true,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization'
    }
  }
})
