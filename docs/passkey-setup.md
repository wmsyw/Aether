# Passkey 通行密钥登录配置指南

本文档介绍如何在 Aether 项目中配置和使用 Passkey (WebAuthn) 通行密钥登录功能。

## 功能概述

Passkey 是一种基于 WebAuthn 标准的无密码认证方式，用户可以使用：
- 指纹/面容识别 (Touch ID / Face ID)
- 设备 PIN 码/图案
- 硬件安全密钥 (YubiKey 等)

进行安全、便捷的登录，无需记忆复杂密码。

## 配置步骤

### 1. 安装依赖

后端依赖已添加到 `pyproject.toml`：
```bash
uv sync
```

前端依赖已包含在 `frontend/package.json` 中：
```bash
cd frontend && npm install
```

### 2. 环境变量配置

在 `.env` 文件中添加以下配置：

```env
# Passkey/WebAuthn 配置
# RP ID: 必须与浏览器地址栏的域名一致（不含端口）
PASSKEY_RP_ID=aether.example.com

# RP 名称: 显示在 Passkey 提示中的名称
PASSKEY_RP_NAME=Aether

# Origin: 必须与浏览器地址栏的完整 origin 一致
PASSKEY_ORIGIN=https://aether.example.com
```

**重要说明**：
- `PASSKEY_RP_ID` 必须是有效的域名，且与浏览器访问的域名一致
- `PASSKEY_ORIGIN` 必须包含协议 (`https://` 或 `http://`) 和端口（如使用非标准端口）
- 生产环境必须使用 HTTPS

### 3. 数据库迁移

运行 Alembic 迁移创建 `user_passkey_credentials` 表：

```bash
# 使用 Docker Compose
docker compose exec app alembic upgrade head

# 或本地开发环境
DATABASE_URL="postgresql://user:pass@host:5432/aether" uv run alembic upgrade head
```

### 4. 验证配置

启动应用后，访问以下端点验证 Passkey 是否启用：

```bash
curl http://localhost:8084/api/auth/passkey/settings
```

应返回：
```json
{
  "enabled": true,
  "rp_id": "aether.example.com",
  "rp_name": "Aether"
}
```

## 使用指南

### 用户注册 Passkey

1. 使用传统方式（邮箱/密码）登录
2. 进入「个人设置」页面
3. 找到「通行密钥 (Passkey)」区域
4. 点击「添加通行密钥」
5. 按照浏览器提示完成注册（验证指纹/面容/PIN）

### 使用 Passkey 登录

1. 在登录页面点击「使用通行密钥登录」
2. 浏览器会弹出认证提示
3. 使用已注册的 Passkey 完成认证
4. 自动登录并跳转到控制台

### 管理 Passkey

在「个人设置」页面可以：
- 查看已注册的所有 Passkey
- 重命名 Passkey（便于识别）
- 删除不再使用的 Passkey

## 浏览器兼容性

Passkey 需要现代浏览器支持：

| 浏览器 | 最低版本 | 说明 |
|--------|----------|------|
| Chrome | 108+ | Windows, macOS, Android |
| Safari | 16+ | macOS, iOS |
| Edge | 108+ | Windows, macOS |
| Firefox | 122+ | 实验性支持 |

**注意**：
- iOS 16+ 和 macOS Ventura+ 支持 iCloud 钥匙串同步 Passkey
- Android 9+ 支持 Google 密码管理器同步
- Windows 10/11 支持 Windows Hello

## 安全注意事项

1. **RP ID 必须正确配置**：错误的 RP ID 会导致 Passkey 无法使用
2. **生产环境必须使用 HTTPS**：WebAuthn 要求安全上下文
3. **用户可以有多个 Passkey**：建议为常用设备分别注册
4. **Passkey 与账号绑定**：删除用户账号会级联删除所有 Passkey

## 故障排除

### "您的浏览器不支持通行密钥"

- 检查浏览器版本是否符合要求
- 确保网站使用 HTTPS（生产环境）
- 检查浏览器是否禁用了 WebAuthn API

### "挑战已过期或无效"

- 检查服务器和客户端时间是否同步
- 确认 `PASSKEY_RP_ID` 和 `PASSKEY_ORIGIN` 配置正确
- 检查网络连接是否正常

### "凭证验证失败"

- 确认 RP ID 与访问域名匹配
- 检查 `PASSKEY_ORIGIN` 是否包含正确的协议和端口
- 查看服务器日志获取详细错误信息

## 技术实现

### 后端架构

- **路由**: `/api/auth/passkey/*`
- **服务**: `src/services/auth/passkey_service.py`
- **模型**: `UserPasskeyCredential` (src/models/database.py)
- **库**: `webauthn` (pywebauthn)

### 前端架构

- **API**: `frontend/src/api/passkey.ts`
- **组合式函数**: `frontend/src/composables/usePasskey.ts`
- **组件**:
  - `PasskeyLoginButton.vue` - 登录按钮
  - `PasskeyManager.vue` - 凭证管理
- **库**: `@simplewebauthn/browser`

### 数据流程

1. **注册**:
   ```
   前端请求注册选项 → 后端生成挑战 → 浏览器创建凭证 → 后端验证并存储
   ```

2. **登录**:
   ```
   前端请求登录选项 → 后端生成挑战 → 浏览器使用凭证签名 → 后端验证 → 返回 JWT
   ```

## 参考资料

- [WebAuthn 规范](https://www.w3.org/TR/webauthn-2/)
- [pywebauthn 文档](https://github.com/duo-labs/py_webauthn)
- [SimpleWebAuthn 文档](https://simplewebauthn.dev/)
- [Apple Passkey 指南](https://developer.apple.com/documentation/authenticationservices/public-private_key_authentication/supporting_passkeys/)
