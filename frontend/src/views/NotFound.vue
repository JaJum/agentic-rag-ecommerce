<template>
  <!-- 4404 页面 -->
  <div class="page-center">
    <el-result icon="warning" title="404" sub-title="页面不存在">
      <template #extra>
        <el-button type="primary" @click="$router.push('/chat')">返回问答</el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.page-center { height: 100%; display: flex; align-items: center; justify-content: center; }
</style>
