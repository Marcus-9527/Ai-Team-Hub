# 学校代理绕过方案

## 问题分析

学校代理的 DPI（深度包检测）行为：
- ✅ 放行：普通 HTML 页面请求（GET, Accept: text/html）
- ❌ 拦截：XHR/fetch API 请求（POST /api/*, Content-Type: application/json）

## 方案选择

### ❌ 方案1: 自定义域名（需要公网域名）
买/注册一个正规域名指向 Worker，代理会放行正常域名。

### ❌ 方案2: VPN/代理（需要额外工具）
设置浏览器代理绕过学校网关。

### ✅ 方案3: API 伪装层（推荐，零成本）
在 Worker 上添加 `/p/` 前缀的伪装路由：
- 路径看起来像页面：`/p/channels` → 实际是 `/api/channels`
- 响应 Content-Type 设为 `text/html; charset=utf-8`
- JSON 数据包裹在 `<script type="application/json">` 标签内
- 前端用 `response.text()` + JSON.parse 提取数据
- 代理看到 URL 路径不含 `/api`，Content-Type 是 text/html → 放行

### ✅ 方案4: 一体化同域部署（推荐补充）
前端 build 产物 + Worker API 同域名，前端不走跨域。
代理对同域请求更宽松。

## 实施优先级
1. 先做方案4（一体化部署，确保前端和 API 同域）
2. 再做方案3（API 伪装层，绕过 DPI 路径检测）
