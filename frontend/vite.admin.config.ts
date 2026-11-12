import { defineConfig } from 'vite';
import {fileURLToPath} from 'node:url';

export default defineConfig({
  plugins: [{name:'admin-route-boundary', configureServer(server) {
    server.middlewares.use((request,response,next) => {
      if (/^\/(api\/shop|internal|assets)(\/|\?|$)/.test(request.url ?? '')) {
        response.statusCode=404; response.end('Not found'); return;
      }
      if (request.url === '/') request.url = '/admin.html';
      next();
    });
  }}],
  server: {host:process.env.RECARENA_WEB_HOST ?? '127.0.0.1', port:Number(process.env.RECARENA_ADMIN_PORT ?? 5174), strictPort:true,
    fs:{strict:true,allow:[fileURLToPath(new URL('./',import.meta.url)),fileURLToPath(new URL('../node_modules/',import.meta.url))]},
    proxy:{'/api/control/':process.env.RECARENA_PLATFORM_URL ?? 'http://127.0.0.1:8010',
           '/api/sessions':process.env.RECARENA_PLATFORM_URL ?? 'http://127.0.0.1:8010'}},
});
