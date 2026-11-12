import {defineConfig} from 'vite';

// The administrator remains a separate static Vite application.
export default defineConfig({build:{rollupOptions:{input:['admin.html']}}});
