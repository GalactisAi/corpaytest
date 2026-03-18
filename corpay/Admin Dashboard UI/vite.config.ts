import { defineConfig } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  define: {
    'import.meta.env.VITE_API_URL': JSON.stringify(process.env.VITE_API_URL || 'http://localhost:8000'),
  },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      devOptions: { enabled: true },
      manifest: {
        name: 'Corpay Admin Dashboard',
        short_name: 'Corpay Admin',
        description: 'Admin Dashboard UI for Corpay',
        theme_color: '#981239',
        background_color: '#0f0f0f',
        display: 'standalone',
        scope: '/',
        start_url: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,png,svg,json,woff2,ico}'],
        // Do not serve SPA fallback for API, PDF files, or external Power BI URLs.
        navigateFallbackDenylist: [
          /^\/api\//,
          /\.pdf$/i,
          /^https?:\/\/.*powerbi\.com/i,
          /^https?:\/\/.*analysis\.windows\.net/i,
        ],
        // Ensure Power BI iframes always go to the network (never cached by the SW).
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/(?:app\.powerbi\.com|.*\.powerbi\.com|.*\.analysis\.windows\.net)\/.*/i,
            handler: 'NetworkOnly',
            options: {
              cacheName: 'powerbi-network-only',
            },
          },
        ],
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  resolve: {
    alias: {
      // Alias @ to the src directory
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
