import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // stdin が閉じられてもプロセスが終了しないようにする (バックグラウンド実行対策)
    {
      name: 'keep-alive',
      configureServer() {
        process.stdin.resume()
      }
    }
  ],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true
  }
})
