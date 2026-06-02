import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { readFileSync } from 'fs'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // TODO: PWA — 有効化するには `npm install -D vite-plugin-pwa` 後に設定追加
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
      // kuromoji package.json points to src/ which doesn't exist; use build output
      kuromoji: resolve(__dirname, 'node_modules/kuromoji/build/kuromoji.js'),
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true
  }
})
