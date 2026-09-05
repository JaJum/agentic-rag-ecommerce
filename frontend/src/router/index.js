/**
 * 路由与守卫：
 * - requiresAuth：需登录（M1 起生效）
 * - requiresAdmin：仅管理员（前端守卫；后端接口另有 require_admin 双重控制）
 */
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/register', name: 'Register', component: () => import('../views/Register.vue'), meta: { public: true } },
  { path: '/chat/:sessionId?', name: 'Chat', component: () => import('../views/chat/ChatLayout.vue'), meta: { requiresAuth: true } },
  { path: '/admin/kb', name: 'KnowledgeBase', component: () => import('../views/admin/KnowledgeBase.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/admin/dashboard', name: 'Dashboard', component: () => import('../views/admin/Dashboard.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
  { path: '/profile', name: 'Profile', component: () => import('../views/user/Profile.vue'), meta: { requiresAuth: true } },
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('../views/NotFound.vue') }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 全局前置守卫：登录与管理员权限双重校验（前端侧）
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    return { path: '/login' }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { path: '/chat' }
  }
})

export default router
