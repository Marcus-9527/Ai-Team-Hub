---
version: alpha
name: AI Team Hub
description: |
  A Slack-inspired AI team collaboration platform. Deep aubergine primary 
  with warm cream neutrals, electric teal accents for AI intelligence cues, 
  and crisp white surfaces. Pill-shaped CTAs, fluid transitions, and subtle 
  texture gradients signal sophistication and trust.
colors:
  primary: "#4a154b"
  primary-deep: "#3a103b"
  primary-press: "#611f69"
  primary-glow: "oklch(45% 0.18 320)"
  on-primary: "#ffffff"
  accent-teal: "#00b4d8"
  accent-teal-glow: "oklch(68% 0.14 220)"
  accent-coral: "#ff6b6b"
  ink: "#1d1d1d"
  ink-mute: "#5c5c5c"
  ink-faint: "#9ca3af"
  canvas: "#ffffff"
  canvas-cream: "#f4ede4"
  canvas-lavender: "#f9f0ff"
  canvas-warm: "#faf8f5"
  surface-elev: "#ffffff"
  surface-hover: "#f5f3f0"
  surface-active: "#ede8f0"
  surface-aubergine: "#4a154b"
  hairline: "#e8e4df"
  hairline-strong: "#d4cfc7"
  semantic-error: "#cc4117"
  semantic-success: "#007a5a"
  semantic-warning: "#e8913a"

typography:
  display:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: 28px
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  heading:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: 18px
    fontWeight: 700
    lineHeight: 1.35
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: 15px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: 0
  body:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0
  body-sm:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  button:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: 14px
    fontWeight: 600
    lineHeight: 1.0
    letterSpacing: 0
  caption:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: 11px
    fontWeight: 700
    lineHeight: 1.0
    letterSpacing: "0.04em"
  mono:
    fontFamily: "JetBrains Mono, SFMono-Regular, Consolas, monospace"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: 0

rounded:
  none: "0"
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  pill: 9999px

spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 20px
  xxl: 24px
  huge: 32px
  massive: 48px

shadows:
  sm: "0 1px 2px rgba(0,0,0,0.04)"
  md: "0 2px 8px rgba(0,0,0,0.06)"
  lg: "0 4px 16px rgba(0,0,0,0.08)"
  xl: "0 8px 32px rgba(0,0,0,0.12)"
  glow-teal: "0 0 12px oklch(68% 0.14 220 / 0.25)"
  glow-aubergine: "0 0 16px oklch(45% 0.18 320 / 0.2)"

components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: 10px 24px
  button-primary-hover:
    backgroundColor: "{colors.primary-press}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: 10px 24px
  button-secondary:
    backgroundColor: "{colors.canvas-lavender}"
    textColor: "{colors.primary}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: 10px 24px
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-mute}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 8px 12px
  button-ghost-hover:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 8px 12px
  chip-teal:
    backgroundColor: "oklch(68% 0.14 220 / 0.1)"
    textColor: "{colors.accent-teal}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: 2px 10px
  chip-aubergine:
    backgroundColor: "{colors.canvas-lavender}"
    textColor: "{colors.primary}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: 2px 10px
  sidebar:
    backgroundColor: "{colors.primary-deep}"
    textColor: "{colors.on-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: 16px
  sidebar-item:
    backgroundColor: "transparent"
    textColor: "oklch(88% 0 0 / 0.7)"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 6px 12px
  sidebar-item-active:
    backgroundColor: "oklch(100% 0 0 / 0.12)"
    textColor: "{colors.on-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 6px 12px
  message-ai:
    backgroundColor: "{colors.canvas-lavender}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 12px 16px
  message-user:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 12px 16px
  input-field:
    backgroundColor: "{colors.surface-elev}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: 10px 16px
  card:
    backgroundColor: "{colors.surface-elev}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.xl}"
    padding: 24px
  modal-overlay:
    backgroundColor: "rgba(0,0,0,0.5)"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: 0px
  modal:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.xl}"
    padding: 32px
---

## Overview

**AI Team Hub** — 将 AI 智能体融入团队协作的下一代工作平台。借鉴 Slack 的频道制沟通，融合 AI 队友的实时分析能力，让用户像管理真人团队一样管理 AI 角色。

**品牌气质**: 专业而不冰冷，智能而不疏离。深茄紫主色调传递稳重与创新，电光青辅助色暗示 AI 的灵动，暖奶油底色调保证长时间使用的舒适感。

## Colors

- **Primary (#4a154b) — Deep Aubergine**: 主导品牌色。用于主按钮、用户消息气泡、侧边栏背景。深而不沉，紫中带暖。
- **Accent Teal (#00b4d8)**: AI 智能信号色。用于 AI 消息指示器、AI 队友标识、加载状态。蓝色系的清新变体，暗示科技感。
- **Accent Coral (#ff6b6b)**: 强调与提醒。用于错误状态、@提及高亮、重要通知。
- **Canvas Cream (#f4ede4)**: 温暖底色。页面背景，缓解纯白界面的冰冷感。
- **Surface Hover (#f5f3f0)**: 几乎所有 hover 状态的统一底色，比纯灰更温暖。

## Typography

全站使用 Inter 字体族 — 现代几何无衬线，x-height 高，数字清晰，专为 UI 场景优化。代码块使用 JetBrains Mono。层级严格控制在 4 级：Display > Heading > Title > Body。

## Components

所有可交互元素使用 pill 圆角（9999px），卡片使用 xl 圆角（16px）。输入框使用 lg 圆角（8px）。阴影系统极轻量，仅在悬浮卡片上使用 — 不做 heavy drop shadow 的 Material 风格。

## Motion

- 页面切换: 200ms ease-out fade + 轻微 Y 轴位移
- Hover 状态: 150ms ease 背景/颜色过渡
- 消息出现: 300ms spring 弹性动画
- AI 思考中: 脉冲发光动画 (glow pulse)，使用 teal 色系
- 侧边栏展开: 250ms cubic-bezier(0.4, 0, 0.2, 1)

## Do's and Don'ts

✅ DO: 使用暖奶油底色做页面背景，避免纯白
✅ DO: AI 回复使用浅紫气泡 + teal 光点作为"正在输入"指示
✅ DO: 按钮文字一个字不加省略号，保持完整
✅ DO: AI 队友头像使用渐变圆形 + 首字母
❌ DON'T: 不要使用纯黑白配色 — 永远有色彩倾向
❌ DON'T: 不用直角 — 至少用 8px 圆角
❌ DON'T: 不要在一条消息中混合多个 AI 的回复
❌ DON'T: 不要使用超过 3 种强调色同时出现
