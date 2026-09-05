<template>
  <!-- 全局布局：登录后显示顶部导航（含管理员专属入口），路由视图渲染页面 -->
  <div class="app">
    <header v-if="auth.isLoggedIn" class="nav">
      <div class="brand">📚 RAG 知识库问答</div>
      <el-menu mode="horizontal" :default-active="activePath" router class="menu" :ellipsis="false">
        <el-menu-item index="/chat">知识库问答</el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/admin/kb">知识库管理</el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/admin/dashboard">统计仪表盘</el-menu-item>
        <el-menu-item index="/profile">个人中心</el-menu-item>
      </el-menu>
      <div class="user">
        <el-tag size="small" :type="auth.isAdmin ? 'warning' : 'info'">
          {{ auth.user?.username }}{{ auth.isAdmin ? '（管理员）' : '' }}
        </el-tag>
        <el-button link type="primary" @click="onLogout">退出</el-button>
      </div>
    </header>
    <router-view />
  </div>
</template>

<script setup>
// 顶部导航：管理员菜单仅 admin 可见（与后端 require_admin 双重控制）
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// 当前激活菜单项（高亮用）
const activePath = computed(() => route.path)

/** 退出登录：清理状态并回登录页 */
function onLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style>
/* 全局基础样式 */
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { height: 100%; font-family: 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif; }
.app { height: 100%; display: flex; flex-direction: column; }
.nav { display: flex; align-items: center; gap: 24px; background: #fff; border-bottom: 1px solid #e4e7ed; padding: 0 24px; height: 56px; }
.brand { font-weight: 600; white-space: nowrap; }
.menu { flex: 1; border-bottom: none !important; }
.user { display: flex; align-items: center; gap: 12px; white-space: nowrap; }
</style>
