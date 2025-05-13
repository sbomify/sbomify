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

const STATIC_URL = process.env.STATIC_URL || '/static/'

// https://vitejs.dev/config/
export default defineConfig({
  base: `${STATIC_URL}`,
  css: {
    devSourcemap: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.')
    }
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
      }
    })
  ],
  build: {
    target: 'esnext',
    outDir: resolve('./staticfiles/'),
    emptyOutDir: false,
    assetsDir: '',
    manifest: 'manifest.json',
    rollupOptions: {
      input: {
        core: resolve('./core/js/main.ts'),
        sboms: resolve('./sboms/js/main.ts'),
        teams: resolve('./teams/js/main.ts'),
        billing: resolve('./billing/js/main.ts'),
        alerts: resolve('./core/js/alerts-global.ts'),
        djangoMessages: resolve('./core/js/django-messages.ts'),
      },
    }
  },
  server: {
    host: '127.0.0.1',
    port: 5170
  }
})
