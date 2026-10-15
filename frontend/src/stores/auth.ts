import { defineStore } from "pinia";
import { ref, computed } from "vue";
import type { User } from "@/types";

// 认证状态：token 与用户信息，持久化到 localStorage。
export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(localStorage.getItem("token"));
  const user = ref<User | null>(_readUser());

  function _readUser(): User | null {
    const raw = localStorage.getItem("user");
    if (!raw) return null;
    try {
      return JSON.parse(raw) as User;
    } catch {
      return null;
    }
  }

  const isLoggedIn = computed(() => !!token.value);

  function setSession(t: string, u: User) {
    token.value = t;
    user.value = u;
    localStorage.setItem("token", t);
    localStorage.setItem("user", JSON.stringify(u));
  }

  function logout() {
    token.value = null;
    user.value = null;
    localStorage.removeItem("token");
    localStorage.removeItem("user");
  }

  return { token, user, isLoggedIn, setSession, logout };
});
