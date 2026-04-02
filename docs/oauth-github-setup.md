# GitHub OAuth 登录配置指南

本文档介绍如何在 Aether 中启用 GitHub OAuth 登录/绑定，并说明管理员侧需要填写的关键配置。

## 适用范围

- Aether 管理后台的 **OAuth 配置**
- GitHub OAuth App
- 前端登录页与用户设置页中的 GitHub 登录/绑定入口

> 如果你的管理后台里还没有 `GitHub` 这个 Provider 选项，说明当前实例版本尚未包含 GitHub OAuth Provider 支持，需要先升级到包含该功能的版本。

## GitHub 侧准备

1. 登录 GitHub
2. 进入 **Settings → Developer settings → OAuth Apps**
3. 点击 **New OAuth App**
4. 填写应用信息：

| 字段 | 建议值 |
| --- | --- |
| Application name | `Aether` 或你的站点名称 |
| Homepage URL | 你的前端地址，例如 `https://aether.example.com` |
| Authorization callback URL | 后端回调地址，例如 `https://aether.example.com/api/oauth/github/callback` |

创建完成后，记录：

- `Client ID`
- `Client Secret`

## Aether 管理后台配置

进入 **管理后台 → OAuth 配置 → GitHub**，填写以下字段。

### 基础字段

| 字段 | 说明 |
| --- | --- |
| Client ID | GitHub OAuth App 的 Client ID |
| Client Secret | GitHub OAuth App 的 Client Secret |
| Redirect URI（后端回调） | 必须与 GitHub OAuth App 的 callback URL 完全一致 |
| 前端回调页 | 前端登录完成后的落地页，通常为 `https://你的前端域名/auth/callback` |

### 推荐默认值

如果你不需要覆盖端点，可直接使用默认值：

| 字段 | 建议值 |
| --- | --- |
| Authorization URL | `https://github.com/login/oauth/authorize` |
| Token URL | `https://github.com/login/oauth/access_token` |
| Userinfo URL | `https://api.github.com/user` |
| Scopes | `read:user user:email` |

其中：

- `read:user` 用于读取 GitHub 基本资料
- `user:email` 用于读取用户邮箱，避免 `/user` 响应里邮箱为空时无法完成账号匹配或注册

## 回调地址示例

假设你的部署域名为 `https://aether.example.com`：

```text
后端回调（Redirect URI）
https://aether.example.com/api/oauth/github/callback

前端回调页（frontend_callback_url）
https://aether.example.com/auth/callback
```

如果前后端分域部署，需要分别填写真实可访问地址，并确保：

- GitHub 只回调后端地址
- 后端处理完成后再跳转到前端回调页

## 启用前检查

保存并启用前，建议逐项确认：

1. `Client ID` / `Client Secret` 已复制完整
2. GitHub OAuth App 的回调地址与 Aether 后端回调地址完全一致
3. 前端回调页路径以 `/auth/callback` 结尾
4. Aether 实例可访问 GitHub OAuth 相关域名
5. 生产环境优先使用 HTTPS

## 验证流程

配置完成后，可以按以下顺序验证：

1. 管理后台点击 **测试**
2. 登录页确认出现 **GitHub 登录** 入口
3. 点击 GitHub 登录，检查是否正确跳转到 GitHub 授权页
4. GitHub 授权完成后，确认浏览器跳回 `/auth/callback`
5. 已登录用户进入 **个人设置**，确认可以绑定/解绑 GitHub

## 常见问题

### 1. 管理后台没有 GitHub 选项

当前部署版本还未注册 GitHub OAuth Provider。先升级版本，再刷新 **OAuth 配置** 页面。

### 2. GitHub 提示 `The redirect_uri is not associated with this application`

说明 GitHub OAuth App 中配置的 callback URL 与 Aether 中填写的 `Redirect URI` 不一致。两边必须完全相同，包括：

- 协议（http / https）
- 域名
- 端口
- 路径

### 3. 登录后回到了前端，但没有完成登录

优先检查：

- `frontend_callback_url` 是否填写为真实前端地址
- 前端是否部署了 `/auth/callback` 页面
- 浏览器是否拦截了 Cookie

### 4. GitHub 账号没有邮箱或邮箱读取失败

建议使用 `read:user user:email`。如果缺少 `user:email`，GitHub 可能无法返回用户邮箱，进而影响注册或账号匹配。

## 运维建议

- 为开发环境和生产环境分别创建独立的 GitHub OAuth App
- 不要在不同域名之间复用同一个回调地址
- 如果切换域名，记得同时更新 GitHub OAuth App 与 Aether 管理后台配置
