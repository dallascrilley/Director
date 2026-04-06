import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';

export default ({ mode }) => {
  // Load environment variables based on the current mode (e.g., 'development', 'production')
  const env = loadEnv(mode, process.cwd());

  return defineConfig({
    plugins: [
      vue({
        template: {
          compilerOptions: {
            // Suppress Vue warnings for events that external packages don't explicitly declare
            // Fixes: "Extraneous non-emits event listeners (videoClick)" from @videodb/chat-vue
            isCustomElement: (tag) => tag.includes('-'),
          },
        },
      }),
    ],
    server: {
      host: '0.0.0.0',
      port: parseInt(env.VITE_PORT),  // Access the port directly from the env object
      open: env.VITE_OPEN_BROWSER === 'false' ? false : true,  // Use the environment variable to control browser opening, default to true
    },
  });
};