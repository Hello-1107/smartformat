<template>
  <div class="login-wrap" :style="{ backgroundImage: `url(${loginBackground})` }">
    <div class="image-shade" aria-hidden="true"></div>
    <el-card class="login-card" shadow="never">
      <div class="login-brand"><span class="brand-mark">S</span><div><b>审格式</b><small>SMARTFORMAT</small></div></div>
      <div class="welcome"><p>AI FORMAT REVIEW</p><h1>{{ mode === "login" ? "欢迎回来" : "创建你的工作空间" }}</h1><span>上传 Word 文档，使用智能规则完成高效、准确的格式审查。</span></div>
      <el-tabs v-model="mode" stretch>
        <el-tab-pane label="登录" name="login" />
        <el-tab-pane label="注册" name="register" />
      </el-tabs>

      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="账号">
          <el-input
            v-model="username"
            placeholder="2-20 位字母、数字、下划线或中文"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            show-password
            placeholder="至少 6 位"
          />
        </el-form-item>
        <el-form-item v-if="mode === 'register'" label="确认密码">
          <el-input
            v-model="confirmPassword"
            type="password"
            show-password
            placeholder="请再次输入密码"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button
          type="primary"
          native-type="submit"
          :loading="loading"
          class="submit"
        >
          {{ mode === "login" ? "登录" : "注册并登录" }}
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus/es/components/message/index";
import { authApi } from "@/api";
import { errText } from "@/api/http";
import { useAuthStore } from "@/stores/auth";
import loginBackground from "@/assets/login-document-review-bg.png";

const router = useRouter();
const auth = useAuthStore();

const mode = ref<"login" | "register">("login");
const username = ref("");
const password = ref("");
const confirmPassword = ref("");
const loading = ref(false);

// 切换登录/注册时清空密码，避免残留导致误提交
watch(mode, () => {
  password.value = "";
  confirmPassword.value = "";
});

async function submit() {
  const account = username.value.trim();
  if (!account || !password.value) {
    ElMessage.warning("请填写账号和密码");
    return;
  }
  // 注册时先做一次本地核验，避免无谓请求
  if (mode.value === "register") {
    if (account.length < 2 || !/^[A-Za-z0-9_\u4e00-\u9fa5]{2,20}$/.test(account)) {
      ElMessage.warning("账号需为 2-20 位字母、数字、下划线或中文");
      return;
    }
    if (password.value.length < 6) {
      ElMessage.warning("密码至少 6 位");
      return;
    }
    if (password.value !== confirmPassword.value) {
      ElMessage.error("两次输入的密码不一致");
      return;
    }
  }
  loading.value = true;
  try {
    const resp =
      mode.value === "login"
        ? await authApi.login({ username: account, password: password.value })
        : await authApi.register({
            username: account,
            password: password.value,
            confirm_password: confirmPassword.value,
          });
    auth.setSession(resp.data.access_token, resp.data.user);
    router.push("/");
  } catch (e) {
    ElMessage.error(errText(e));
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-wrap {
  position: relative;
  overflow: hidden;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 40px clamp(28px, 7vw, 128px);
  background-position: center;
  background-size: cover;
  background-repeat: no-repeat;
}
.image-shade {
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, rgba(2, 12, 39, .04) 0%, rgba(2, 12, 39, .08) 47%, rgba(1, 9, 30, .5) 100%);
}
.login-card {
  z-index: 1;
  width: min(440px, 100%);
  padding: 8px 12px;
  border: 1px solid rgba(255, 255, 255, .72);
  border-radius: 24px;
  background: rgba(255, 255, 255, .94);
  box-shadow: 0 28px 80px rgba(0, 12, 49, .38);
  backdrop-filter: blur(18px);
}
.login-card :deep(.el-card__body) { padding: 25px 24px; }
.login-brand { display: flex; align-items: center; gap: 11px; margin-bottom: 30px; color: #172442; }.brand-mark { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 11px; color: #fff; background: linear-gradient(135deg, #6385ff, #284bd2); box-shadow: 0 7px 18px rgba(48, 80, 208, .3); font-family: Georgia, serif; font-size: 21px; }.login-brand b { display: block; font-size: 17px; }.login-brand small { display: block; margin-top: 1px; color: #8290aa; font-size: 8px; font-weight: 800; letter-spacing: .16em; }.welcome { margin-bottom: 24px; }.welcome p { margin: 0 0 8px; color: #5271d8; font-size: 10px; font-weight: 800; letter-spacing: .16em; }.welcome h1 { margin: 0; color: #152442; font-size: 28px; line-height: 1.25; letter-spacing: -.035em; }.welcome span { display: block; margin-top: 10px; color: #77869e; font-size: 13px; line-height: 1.7; }
.login-card :deep(.el-tabs__header) { margin-bottom: 22px; }.login-card :deep(.el-tabs__nav-wrap::after) { height: 1px; background: #edf0f5; }.login-card :deep(.el-tabs__item.is-active) { color: #4667df; font-weight: 700; }.login-card :deep(.el-input__wrapper) { min-height: 39px; border-radius: 8px; background: #f8faff; box-shadow: 0 0 0 1px #e8edf5 inset; }.login-card :deep(.el-form-item__label) { color: #53627b; font-weight: 600; }
.submit { height: 44px; border: 0; border-radius: 9px; background: linear-gradient(135deg, #6383f7, #3455d8); box-shadow: 0 8px 18px rgba(50, 82, 211, .27); }
.submit { width: 100%; }
@media (max-width: 760px) {
  .login-wrap { justify-content: center; padding: 22px; background-position: 38% center; }
  .image-shade { background: rgba(2, 10, 32, .48); }
  .login-card { width: min(430px, 100%); border-radius: 20px; }
}
@media (max-height: 700px) {
  .login-wrap { align-items: flex-start; overflow-y: auto; padding-top: 24px; padding-bottom: 24px; }
  .login-brand { margin-bottom: 18px; }
  .welcome { margin-bottom: 16px; }
  .welcome span { margin-top: 6px; }
}
</style>
