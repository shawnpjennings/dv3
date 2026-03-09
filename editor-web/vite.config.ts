import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';
import type { Connect } from 'vite';

const ANIMATIONS_DIR = path.resolve(__dirname, '../animations');

/** Vite middleware plugin — adds write endpoints so the editor can save
 *  directly to the animations/ directory without File System Access API. */
function animationsApiPlugin() {
  return {
    name: 'animations-api',
    configureServer(server: { middlewares: { use: (fn: Connect.NextHandleFunction) => void } }) {
      server.middlewares.use(async (req, res, next) => {
        // POST /api/write-file?path=library/foo.webp  — body is raw bytes
        if (req.method === 'POST' && req.url?.startsWith('/api/write-file?')) {
          const url = new URL(req.url, 'http://localhost');
          const relPath = url.searchParams.get('path');
          if (!relPath || relPath.includes('..')) {
            res.statusCode = 400;
            res.end('Bad path');
            return;
          }
          const absPath = path.join(ANIMATIONS_DIR, relPath);
          const dir = path.dirname(absPath);
          fs.mkdirSync(dir, { recursive: true });

          const chunks: Buffer[] = [];
          req.on('data', (c: Buffer) => chunks.push(c));
          req.on('end', () => {
            fs.writeFileSync(absPath, Buffer.concat(chunks));
            res.statusCode = 200;
            res.end('OK');
          });
          return;
        }

        // DELETE /api/delete-file?path=inbox/foo.webp
        if (req.method === 'DELETE' && req.url?.startsWith('/api/delete-file?')) {
          const url = new URL(req.url, 'http://localhost');
          const relPath = url.searchParams.get('path');
          if (!relPath || relPath.includes('..')) {
            res.statusCode = 400;
            res.end('Bad path');
            return;
          }
          const absPath = path.join(ANIMATIONS_DIR, relPath);
          try { fs.unlinkSync(absPath); } catch { /* already gone */ }
          res.statusCode = 200;
          res.end('OK');
          return;
        }

        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), animationsApiPlugin()],
  optimizeDeps: {
    exclude: ['@ffmpeg/ffmpeg', '@ffmpeg/util'],
  },
  server: {
    headers: {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
    },
    allowedHosts: true,
    // Serve DV3's animation directory
    fs: {
      allow: ['.', path.resolve(__dirname, '../animations')],
    },
  },
});
