import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import router from './router';

const app = createApp(App);

// Suppress known warnings from external packages
app.config.warnHandler = (msg, instance, trace) => {
  // Ignore extraneous non-emits event warnings from @videodb/chat-vue
  if (msg.includes('Extraneous non-emits event listeners') && msg.includes('videoClick')) {
    return;
  }
  // Log other warnings normally
  console.warn(msg, trace);
};

app.use(router).mount('#app')

