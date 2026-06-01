import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
// @ts-ignore -- vite-plugin-pwa doesn't ship .d.ts for node config
import { VitePWA } from 'vite-plugin-pwa'
import { resolve } from 'path'
import { readFileSync } from 'fs'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['nextchord.svg'],
      manifest: {
        name: 'NextChord',
        short_name: 'NextChord',
        description: 'AI楽曲解析 - コード譜・TAB・五線譜',
        theme_color: '#6366f1',
        background_color: '#0a0a0f',
        display: 'standalone',
        icons: [
          { src: 'nextchord.svg', sizes: '512x512', type: 'image/svg+xml', purpose: 'any maskable' }
        ]
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        runtimeCaching: [
          {
            urlPattern: /\/api\//,
            handler: 'NetworkFirst',
            options: { cacheName: 'api-cache', expiration: { maxEntries: 50, maxAgeSeconds: 86400 } }
          },
          {
            urlPattern: /\/result\//,
            handler: 'NetworkFirst',
            options: { cacheName: 'result-cache', expiration: { maxEntries: 30, maxAgeSeconds: 604800 } }
          }
        ]
      }
    }),
    // stdin が閉じられてもプロセスが終了しないようにする (バックグラウンド実行対策)
    // @ts-ignore
    {
      name: 'keep-alive',
      configureServer() {
        process.stdin.resume()
      }
    },
    // Serve kuromoji dict .gz files as raw binary (prevent transparent decompression)
    // @ts-ignore
    {
      name: 'serve-kuromoji-dict',
      configureServer(server: any) {
        server.middlewares.use((req: any, res: any, next: any) => {
          if (req.url && req.url.startsWith('/dict/') && req.url.endsWith('.dat.gz')) {
            const filePath = resolve(__dirname, 'public', req.url.slice(1));
            try {
              const data = readFileSync(filePath);
              res.setHeader('Content-Type', 'application/octet-stream');
              res.setHeader('Content-Length', data.length.toString());
              // Explicitly NOT setting Content-Encoding so browser won't decompress
              res.end(data);
            } catch {
              next();
            }
            return;
          }
          next();
        });
      }
    }
  ],
  resolve: {
    alias: {
      // kuromoji uses path.join for dictionary URLs – provide a browser-compatible shim
      path: resolve(__dirname, 'src/utils/pathShim.js'),
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true
  }
})
