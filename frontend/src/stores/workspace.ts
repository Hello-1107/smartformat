import { defineStore } from "pinia";
import { ref } from "vue";
import { workspaceApi } from "@/api";
import type { Workspace } from "@/types";

// 工作区状态：列表 + 当前选中项。
export const useWorkspaceStore = defineStore("workspace", () => {
  const workspaces = ref<Workspace[]>([]);
  const currentId = ref<number | null>(null);
  const loaded = ref(false);

  async function load() {
    const resp = await workspaceApi.list();
    workspaces.value = resp.data;
    loaded.value = true;
    if (!workspaces.value.some(item => item.id === currentId.value)) {
      currentId.value = workspaces.value[0]?.id ?? null;
    }
  }

  async function create(name: string) {
    const resp = await workspaceApi.create(name);
    workspaces.value.push(resp.data);
    currentId.value = resp.data.id;
    return resp.data;
  }

  async function remove(id: number) {
    await workspaceApi.remove(id);
    workspaces.value = workspaces.value.filter(item => item.id !== id);
    if (currentId.value === id) currentId.value = workspaces.value[0]?.id ?? null;
  }

  function reset() {
    workspaces.value = [];
    currentId.value = null;
    loaded.value = false;
  }

  return { workspaces, currentId, loaded, load, create, remove, reset };
});
