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
  window.open('http://localhost:8000/api/docs', '_blank')
}

const refreshPage = () => {
  window.location.reload()
}
</script>

<style>
/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

.app-container {
  height: 100vh;
  background: #f0f2f5;
}

/* 侧边栏样式 */
.app-aside {
  background: linear-gradient(180deg, #1e3a5f 0%, #0d1b2a 100%);
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.15);
}

.logo {
  padding: 24px 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.logo-icon {
  width: 48px;
  height: 48px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.logo-text h1 {
  font-size: 20px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 1px;
}

.logo-text p {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
  margin-top: 2px;
}

/* 菜单样式 */
.app-menu {
  flex: 1;
  background: transparent;
  border: none;
  padding: 12px 0;
}

.app-menu .el-menu-item {
  height: 50px;
  line-height: 50px;
  margin: 4px 12px;
  border-radius: 10px;
  color: rgba(255, 255, 255, 0.7);
  transition: all 0.3s ease;
}

.app-menu .el-menu-item .el-icon {
  font-size: 18px;
  margin-right: 10px;
}

.app-menu .el-menu-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.app-menu .el-menu-item.is-active {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.menu-badge {
  width: 18px;
  height: 18px;
  background: #f56c6c;
  border-radius: 50%;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: auto;
  color: #fff;
}

.aside-footer {
  padding: 16px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.version-info {
  display: flex;
  align-items: center;
  gap: 6px;
  color: rgba(255, 255, 255, 0.4);
  font-size: 12px;
}

/* 主容器 */
.main-container {
  display: flex;
  flex-direction: column;
}

/* 头部样式 */
.app-header {
  background: #fff;
  height: 70px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
  z-index: 10;
}

.header-left h2 {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 4px;
}

.header-left .el-breadcrumb {
  font-size: 12px;
}

.header-right {
  display: flex;
  gap: 8px;
}

.header-right .el-button {
  border: none;
  background: #f5f7fa;
}

.header-right .el-button:hover {
  background: #e8f0fe;
  color: #667eea;
}

/* 主内容区 */
.app-main {
  padding: 24px;
  background: #f0f2f5;
  overflow-y: auto;
}

/* 页面过渡动画 */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.25s ease;
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

/* 配置弹窗 */
.config-dialog .dialog-content {
  text-align: center;
  padding: 20px 0;
}

.config-dialog .dialog-icon {
  color: #67c23a;
  margin-bottom: 16px;
}

.config-dialog .dialog-content p {
  color: #606266;
  font-size: 14px;
}

/* 全局卡片样式优化 */
.el-card {
  border: none;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.el-card__header {
  border-bottom: 1px solid #f0f0f0;
  padding: 16px 20px;
  font-weight: 600;
  color: #1f2937;
}

/* 按钮样式优化 */
.el-button--primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
}

.el-button--primary:hover {
  background: linear-gradient(135deg, #5a6fd6 0%, #6a4190 100%);
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-thumb {
  background: #c0c4cc;
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: #909399;
}

::-webkit-scrollbar-track {
  background: transparent;
}
</style>
