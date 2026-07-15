# Phase 27.2 产品简化清理报告

## 变更摘要

### 1. 删除 Organization Dashboard
- **文件删除**: `frontend/src/components/Dashboard/OrganizationDashboard.jsx`
- **AppShell**: 移除 lazy import + org-dashboard 路由
- **Sidebar**: 移除 NAV_ITEMS 中的 org-dashboard
- **i18n**: 移除 `nav.org_dashboard` 键

### 2. 重命名 AI Ops → AI 自动化
- **AIOpsCenter.jsx**: 页面标题 "AI 运维中心" → "AI 自动化"
- **i18n/zh.js**: `nav.ai_ops` 值更新
- **i18n/en.js**: 新增 `nav.ai_ops` 翻译键

### 3. 删除 System Health 用户入口
- **Sidebar**: 移除 NAV_ITEMS 中的 system-health
- **i18n**: 移除 `nav.system_health` 键
- **Settings**: API Keys 标签底部新增 **Diagnostics** 按钮（调用 `onNavigate('system-health')`）
- **组件保留**: `SystemHealthView` 及其 AppShell 路由不变

### 4. 删除 User Mode
- **AppShell**: 移除 `userMode` state/localStorage/persistence；dashboard 直接渲染 `DashboardPage`；移除 `showDashboard` prop 传递；TaskModeView/HomePage viewProps 清理
- **SettingsPanel**: 移除 mode tab、USER_MODES 数组、`setUserMode` prop；exec_pref 设置始终可见
- **TaskModeView**: 移除 `userMode` prop
- **TaskProgressPanel**: 移除 `userMode` prop
- **i18n**: 移除 `settings.mode`, `settings.mode_desc`, `settings.expert_controls`, `settings.model_strategy_*` 键

### 5. 删除 队友大脑(Brain) 用户入口
- **Sidebar**: 移除 NAV_ITEMS 中的 brain
- **i18n**: 移除 `nav.brain` 键

### 6. 清理未使用的 i18n 键
- 移除: `sidebar.tasks`, `nav.dashboard`, `nav.results`, `nav.org_dashboard`, `nav.system_health`, `nav.brain`

## 测试结果
- **pytest** (backend, unit tests): ✅ 684 passed, 0 failed
- **vite build** (frontend): ✅ built in 7.07s, 无错误

## 剩余事项
- Inbox 组件保留（下一阶段准备，本次未实现邮件模式）
- `DeveloperCenter` 组件文件仍存在（不再 import，可后续清理）
