<template>
  <el-container class="app-container">
    <!-- 侧边栏 -->
    <el-aside width="240px" class="app-aside">
      <div class="logo">
        <div class="logo-icon">
          <el-icon :size="32"><Cloudy /></el-icon>
        </div>
        <div class="logo-text">
          <h1>SESORA</h1>
          <p>云原生成熟度评估</p>
        </div>
      </div>
      
      <el-menu
        :default-active="$route.path"
        router
        class="app-menu"
      >
        <el-menu-item index="/config">
          <el-icon><Setting /></el-icon>
          <template #title>配置管理</template>
        </el-menu-item>
        <el-menu-item index="/mock">
          <el-icon><UploadFilled /></el-icon>
          <template #title>Mock 数据</template>
        </el-menu-item>
        <el-menu-item index="/collect">
          <el-icon><Connection /></el-icon>
          <template #title>数据采集</template>
        </el-menu-item>
        <el-menu-item index="/knowledge">
          <el-icon><FolderOpened /></el-icon>
          <template #title>知识库</template>
        </el-menu-item>
        <el-menu-item index="/analyze">
          <el-icon><TrendCharts /></el-icon>
          <template #title>评估分析</template>
        </el-menu-item>
      </el-menu>
      
      <div class="aside-footer">
        <div class="version-info">
          <el-icon><InfoFilled /></el-icon>
          <span>v1.0.0</span>
        </div>
      </div>
    </el-aside>
    
    <!-- 主内容区 -->
    <el-container class="main-container">
      <el-header class="app-header">
        <div class="header-left">
          <h2>{{ $route.meta.title }}</h2>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ $route.meta.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <el-tooltip content="API 文档" placement="bottom">
            <el-button circle @click="openApiDocs">
              <el-icon><Document /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip content="刷新" placement="bottom">
            <el-button circle @click="refreshPage">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
  

</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const openApiDocs = () => {
  window.open('/api/docs', '_blank')
}

const refreshPage = () => {
  window.location.reload()
}
</script>

<style>
html, body, #app {
  height: 100%;
}

.app-container {
  height: 100vh;
  background: var(--color-bg-body);
}

/* 侧边栏样式 */
.app-aside {
  background: var(--color-bg-white);
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--color-border);
}

.logo {
  padding: 20px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--color-border);
  height: 60px;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: var(--color-primary);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.logo-text h1 {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: 0.5px;
}

.logo-text p {
  font-size: 11px;
  color: var(--color-text-tertiary);
  margin-top: 1px;
}

/* 菜单样式 */
.app-menu {
  flex: 1;
  background: transparent;
  border: none !important;
  padding: 8px 0;
}

.app-menu .el-menu-item {
  height: 44px;
  line-height: 44px;
  margin: 2px 8px;
  border-radius: 6px;
  color: var(--color-text-secondary);
  font-size: 14px;
  transition: all 0.2s ease;
}

.app-menu .el-menu-item .el-icon {
  font-size: 16px;
  margin-right: 8px;
  color: var(--color-text-tertiary);
}

.app-menu .el-menu-item:hover {
  background: var(--color-bg-1);
  color: var(--color-text-primary);
}

.app-menu .el-menu-item:hover .el-icon {
  color: var(--color-primary);
}

.app-menu .el-menu-item.is-active {
  background: var(--color-primary-bg);
  color: var(--color-primary);
  font-weight: 500;
}

.app-menu .el-menu-item.is-active .el-icon {
  color: var(--color-primary);
}

.aside-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--color-border);
}

.version-info {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-tertiary);
  font-size: 12px;
}

/* 主容器 */
.main-container {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 头部样式 */
.app-header {
  background: var(--color-bg-white);
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid var(--color-border);
  z-index: 10;
  flex-shrink: 0;
}

.header-left h2 {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 2px;
}

.header-left .el-breadcrumb {
  font-size: 12px;
}

.header-right {
  display: flex;
  gap: 8px;
  align-items: center;
}

.header-right .el-button {
  border: 1px solid var(--color-border);
  background: var(--color-bg-white);
  color: var(--color-text-secondary);
}

.header-right .el-button:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-bg);
}

/* 主内容区 */
.app-main {
  padding: 0;
  background: var(--color-bg-white);
  overflow-y: auto;
  flex: 1;
}
</style>
