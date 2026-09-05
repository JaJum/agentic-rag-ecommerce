<template>
  <!-- 登录页：用户名/密码 → JWT 持久化 → 进入问答（需求 5） -->
  <div class="page-center">
    <el-card class="box">
      <h2 class="title">登录</h2>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            show-password
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-button type="primary" class="btn" :loading="loading" @click="onSubmit">
          登录
        </el-button>
      </el-form>
      <div class="links">
        还没有账号？<router-link to="/register">立即注册</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
// 登录逻辑：表单校验 → POST /auth/login → 保存 token/用户 → 跳转问答页
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import request from '../api/request'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const formRef = ref()
const loading = ref(false)

// 登录表单数据
const form = reactive({ username: '', password: '' })
// 表单校验规则
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

/** 提交登录：成功后写入认证状态并跳转；失败弹错误提示 */
async function onSubmit() {
  await formRef.value.validate()
  loading.value = true
  try {
    const data = await request.post('/auth/login', form)
    auth.setAuth(data.access_token, data.user)
    ElMessage.success('登录成功')
    router.push('/chat')
  } catch (e) {
    ElMessage.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.page-center { height: 100%; display: flex; align-items: center; justify-content: center; background: #f5f7fa; }
.box { width: 380px; padding: 8px 12px; }
.title { text-align: center; margin-bottom: 20px; }
.btn { width: 100%; }
.links { text-align: center; margin-top: 14px; color: #909399; font-size: 14px; }
</style>
