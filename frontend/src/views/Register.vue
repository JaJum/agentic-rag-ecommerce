<template>
  <!-- 注册页：用户名/密码/确认密码 → POST /auth/register（需求 5） -->
  <div class="page-center">
    <el-card class="box">
      <h2 class="title">注册</h2>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名（3~32 位）" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码（至少 6 位）" show-password :prefix-icon="Lock" />
        </el-form-item>
        <el-form-item prop="confirm">
          <el-input v-model="form.confirm" type="password" placeholder="确认密码" show-password :prefix-icon="Lock" />
        </el-form-item>
        <el-button type="primary" class="btn" :loading="loading" @click="onSubmit">
          注册
        </el-button>
      </el-form>
      <div class="links">
        已有账号？<router-link to="/login">返回登录</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
// 注册逻辑：两次密码一致性校验 → 注册成功后引导回登录页
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import request from '../api/request'

const router = useRouter()
const formRef = ref()
const loading = ref(false)

// 注册表单数据
const form = reactive({ username: '', password: '', confirm: '' })

/** 确认密码一致性自定义校验 */
const validateConfirm = (rule, value, callback) => {
  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

// 表单校验规则（与后端 schema 对齐）
const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 32, message: '长度 3~32 位', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 64, message: '密码至少 6 位', trigger: 'blur' }
  ],
  confirm: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirm, trigger: 'blur' }
  ]
}

/** 提交注册：成功后跳回登录页 */
async function onSubmit() {
  await formRef.value.validate()
  loading.value = true
  try {
    await request.post('/auth/register', {
      username: form.username,
      password: form.password
    })
    ElMessage.success('注册成功，请登录')
    router.push('/login')
  } catch (e) {
    ElMessage.error(e.message || '注册失败')
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
