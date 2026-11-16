<template>
  <!-- 个人中心：修改密码（校验原密码） -->
  <div class="page">
    <el-card class="card">
      <h2>个人中心</h2>
      <el-descriptions :column="1" border class="info">
        <el-descriptions-item label="用户名">{{ auth.user?.username }}</el-descriptions-item>
        <el-descriptions-item label="角色">{{ auth.user?.role === 'admin' ? '管理员' : '普通用户' }}</el-descriptions-item>
      </el-descriptions>

      <h3 class="sub">修改密码</h3>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px" class="form">
        <el-form-item label="原密码" prop="old_password">
          <el-input v-model="form.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="form.new_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm">
          <el-input v-model="form.confirm" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="onSubmit">保存修改</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
// 改密逻辑：PUT /auth/password（校验原密码），成功后提示需用新密码登录
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../../api/request'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const formRef = ref()
const loading = ref(false)

// 修改密码表单
const form = reactive({ old_password: '', new_password: '', confirm: '' })

/** 确认密码一致性校验 */
const validateConfirm = (rule, value, callback) => {
  if (value !== form.new_password) {
    callback(new Error('两次输入的新密码不一致'))
  } else {
    callback()
  }
}

// 校验规则
const rules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 64, message: '新密码至少 6 位', trigger: 'blur' }
  ],
  confirm: [
    { required: true, message: '请确认新密码', trigger: 'blur' },
    { validator: validateConfirm, trigger: 'blur' }
  ]
}

/** 提交修改密码 */
async function onSubmit() {
  await formRef.value.validate()
  loading.value = true
  try {
    await request.put('/auth/password', {
      old_password: form.old_password,
      new_password: form.new_password
    })
    ElMessage.success('密码修改成功')
    form.old_password = ''
    form.new_password = ''
    form.confirm = ''
  } catch (e) {
    ElMessage.error(e.message || '修改失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.page { padding: 24px; display: flex; justify-content: center; }
.card { width: 520px; }
.info { margin: 16px 0; }
.sub { margin: 20px 0 12px; }
</style>
