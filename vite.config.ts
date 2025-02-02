import path from 'path'
import { resolve } from 'path'
import fs from 'fs'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

import { config } from 'dotenv'

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
  plugins: [vue()],
  build: {
    target: 'esnext',
    outDir: resolve('./static/'),
    emptyOutDir: false,
    assetsDir: '',
    manifest: 'manifest.json',
    rollupOptions: {
      watch: false,
      treeshake: false,
      cache: false,
      input: {
        core: resolve('./core/js/main.ts'),
        sboms: resolve('./sboms/js/main.ts'),
        teams: resolve('./teams/js/main.ts'),
      },
    }
  },
  server: {
    host: '127.0.0.1',
    port: 5170
  }
})
