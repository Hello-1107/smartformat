import { createApp } from "vue";
import { createPinia } from "pinia";
import UI from "./ui";
import "element-plus/dist/index.css";
import App from "./App.vue";
import router from "./router";

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(UI);
app.mount("#app");
