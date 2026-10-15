<template>
  <div class="login-wrap">
    <div class="backdrop blob-one"></div><div class="backdrop blob-two"></div>
    <el-card class="login-card" shadow="never">
      <div class="login-brand"><span class="brand-mark">S</span><div><b>审格式</b><small>SMARTFORMAT</small></div></div>
      <div class="welcome"><p>AI FORMAT REVIEW</p><h1>让每一份文档<br />都恰到好处。</h1><span>上传 Word 文档，使用智能规则完成高效、准确的格式审查。</span></div>
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
import { ElMessage } from "element-plus";
import { authApi } from "@/api";
import { errText } from "@/api/http";
import { useAuthStore } from "@/stores/auth";

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
  justify-content: center;
  background: radial-gradient(circle at 15% 20%, #edf1ff 0, transparent 32%), linear-gradient(135deg, #f8faff 0%, #edf2fa 100%);
}
.login-card {
  z-index: 1;
  width: 405px;
  padding: 6px 8px;
  border: 1px solid rgba(222, 229, 242, .9);
  border-radius: 18px;
  box-shadow: 0 20px 60px rgba(56, 75, 124, .14);
}
.login-brand { display: flex; align-items: center; gap: 10px; margin-bottom: 28px; color: #172442; }.brand-mark { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; color: #fff; background: linear-gradient(135deg, #5b77f4, #314fd4); box-shadow: 0 5px 13px rgba(59, 82, 205, .28); font-family: Georgia, serif; font-size: 20px; }.login-brand b { display: block; font-size: 16px; }.login-brand small { display: block; margin-top: 1px; color: #92a0b8; font-size: 8px; font-weight: 700; letter-spacing: .13em; }.welcome { margin-bottom: 22px; }.welcome p { margin: 0 0 8px; color: #6680d8; font-size: 10px; font-weight: 800; letter-spacing: .14em; }.welcome h1 { margin: 0; color: #1a2845; font-size: 25px; line-height: 1.26; letter-spacing: -.04em; }.welcome span { display: block; margin-top: 10px; color: #8794aa; font-size: 13px; line-height: 1.65; }
.login-card :deep(.el-tabs__header) { margin-bottom: 22px; }.login-card :deep(.el-tabs__nav-wrap::after) { height: 1px; background: #edf0f5; }.login-card :deep(.el-tabs__item.is-active) { color: #4667df; font-weight: 700; }.login-card :deep(.el-input__wrapper) { min-height: 39px; border-radius: 8px; background: #f8faff; box-shadow: 0 0 0 1px #e8edf5 inset; }.login-card :deep(.el-form-item__label) { color: #53627b; font-weight: 600; }
.backdrop { position: absolute; border-radius: 50%; opacity: .55; filter: blur(1px); }.blob-one { width: 390px; height: 390px; top: -160px; right: -70px; background: radial-gradient(circle, #d9e3ff, transparent 68%); }.blob-two { width: 350px; height: 350px; bottom: -180px; left: -120px; background: radial-gradient(circle, #dbeeff, transparent 67%); }
.submit { height: 42px; border: 0; border-radius: 8px; background: linear-gradient(135deg, #5f7bf5, #4160dc); box-shadow: 0 7px 16px rgba(65, 96, 220, .22); }
.submit { width: 100%; }
</style>
