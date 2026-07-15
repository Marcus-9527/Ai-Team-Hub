# Phase 28: i18n 清理报告

## 删除的语言文件 (11)
ru.js, ko.js, nl.js, pt.js, it.js, ja.js, fr.js, hi.js, es.js, ar.js, de.js

## 修改的文件 (4)
| 文件 | 改动 |
|------|------|
| frontend/src/i18n/index.js | 移除多余 loader 和 SUPPORTED_LANGUAGES 注册项，只保留 zh/en |
| frontend/src/i18n/en.js | 补充 22 个缺失 key 的中文翻译 |
| frontend/src/components/Settings/SettingsPanel.jsx | 移除语言按钮上的国旗图标 |
| frontend/src/components/Landing/Navbar.jsx | 移除语言按钮上的国旗图标 |

## i18n Key 审计结果
- zh.js: 487 keys, en.js: 487 keys（完全对齐）
- 代码 t() 调用：222 个唯一 key
- 缺失 key：**0**（全部 key 在 zh.js 和 en.js 中均有定义）
- 补充到 en.js 的 key 列表：
  - `sidebar.new_topic_action`
  - `task.tab.activity`, `task.tab.delivery`, `task.tab.run`
  - `task.dag_plan`, `task.techlead`, `task.techlead_confidence`, `task.techlead_risk`, `task.techlead_steps`
  - `teammate.chat_advanced`, `teammate.chat_memory`, `teammate.chat_memory_hint`
  - `teammate.chat_model_auto_hint`, `teammate.chat_model_manual`
  - `teammate.chat_role_template`, `teammate.chat_role_template_ph`
  - `teammate.chat_system_prompt`, `teammate.chat_system_prompt_ph`
  - `teammate.chat_tools`, `teammate.chat_tools_ph`
  - `teammate.create_btn`, `teammate.creating`

## 测试结果
- **前端 build: ✅ 通过**（7.17s）
- 未改动后端，无需后端测试
- 语言切换链路校验：`setLang → localStorage → LangProvider → re-render` 链路未改动，保持正常

## 完成标准
| 标准 | 状态 |
|------|------|
| ✅ 只剩中文/英文 | ✅ |
| ✅ 切换可靠 | ✅（链路未改动） |
| ✅ 无翻译 key 泄露 | ✅（双文件 key 完全对齐） |
| ✅ 无机翻语言入口 | ✅ |
| ✅ 前端 build 通过 | ✅ |
