# Apple Passkey / WebAuthn 在 iOS/macOS 应用中的完整实现指南

## 目录

1. [概述](#概述)
2. [前置配置](#前置配置)
3. [核心组件](#核心组件)
4. [注册 Passkey 完整流程](#注册-passkey-完整流程)
5. [使用 Passkey 登录完整流程](#使用-passkey-登录完整流程)
6. [AutoFill 集成](#autofill-集成)
7. [错误处理](#错误处理)
8. [与现有认证系统集成](#与现有认证系统集成)
9. [企业环境部署](#企业环境部署)
10. [最佳实践总结](#最佳实践总结)

---

## 概述

Passkey 是基于 WebAuthn 和 FIDO2 标准的无密码认证方式，使用公钥加密技术替代传统密码。在 iOS/macOS 平台上，Apple 通过 `AuthenticationServices` 框架提供完整的 Passkey 支持。

### Passkey 的核心优势

- **防钓鱼攻击**：每个 Passkey 与特定应用/网站绑定
- **无密码泄露风险**：服务器只存储公钥，私钥永远不会离开设备
- **跨设备同步**：通过 iCloud Keychain 在所有 Apple 设备间同步
- **生物识别验证**：使用 Face ID / Touch ID / 设备密码验证用户身份
- **跨平台支持**：可在非 Apple 设备上使用（通过二维码扫描）

### 系统要求

- iOS 16.0+ / iPadOS 16.0+ / macOS 13.0+
- 需要配置 Associated Domains
- 后端需要支持 WebAuthn 标准

---

## 前置配置

### 1. 配置 Associated Domains

在 Xcode 项目中启用 Associated Domains 能力：

```
1. 选择项目 Target → Signing & Capabilities
2. 点击 "+ Capability"
3. 添加 "Associated Domains"
4. 添加条目: webcredentials:yourdomain.com
```

### 2. 配置 Apple App Site Association 文件

在服务器上创建 `apple-app-site-association` 文件，路径为：
`https://yourdomain.com/.well-known/apple-app-site-association`

```json
{
    "webcredentials": {
        "apps": [
            "TEAMID.com.yourcompany.yourapp"
        ]
    }
}
```

**注意**：
- 替换 `TEAMID` 为你的 Apple Developer Team ID
- 替换 `com.yourcompany.yourapp` 为你的 Bundle Identifier
- 文件不要添加 `.json` 扩展名
- 确保可通过 HTTPS 访问

### 3. 配置 Info.plist（可选）

如果使用凭证提供程序扩展：

```xml
<dict>
    <key>NSExtensionAttributes</key>
    <dict>
        <key>ASCredentialProviderExtensionCapabilities</key>
        <dict>
            <key>ProvidesPasswords</key>
            <true/>
            <key>ProvidesPasskeys</key>
            <true/>
            <key>SupportsConditionalPasskeyRegistration</key>
            <true/>
            <key>ProvidesOneTimeCodes</key>
            <true/>
        </dict>
    </dict>
</dict>
```

---

## 核心组件

### AuthenticationServices 框架关键类

| 类 | 用途 |
|---|---|
| `ASAuthorizationPlatformPublicKeyCredentialProvider` | 创建 Passkey 请求 |
| `ASAuthorizationController` | 管理认证流程 |
| `ASAuthorizationPlatformPublicKeyCredentialRegistration` | 注册凭证结果 |
| `ASAuthorizationPlatformPublicKeyCredentialAssertion` | 登录断言结果 |

---

## 注册 Passkey 完整流程

### 流程图

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   用户输入    │────▶│ 请求注册挑战   │────▶│  后端生成    │
│  (用户名/邮箱) │     │             │     │  Challenge  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                                               ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  后端验证并   │◀────│ 发送注册数据   │◀────│ 系统创建     │
│  存储公钥    │     │             │     │  Passkey    │
└─────────────┘     └─────────────┘     └─────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │  Face ID /  │
                   │ Touch ID    │
                   │ 验证        │
                   └─────────────┘
```

### 完整代码实现

```swift
import AuthenticationServices
import Combine

// MARK: - 数据模型

struct PasskeyRegistrationRequest {
    let challenge: Data
    let userID: Data
    let username: String
}

struct PasskeyRegistrationResponse {
    let credentialID: Data
    let rawClientDataJSON: Data
    let rawAttestationObject: Data?
}

// MARK: - Passkey 管理器

final class PasskeyManager: NSObject, ObservableObject {
    
    // MARK: - 属性
    
    private var authorizationController: ASAuthorizationController?
    private var registrationContinuation: CheckedContinuation<ASAuthorizationPlatformPublicKeyCredentialRegistration, Error>?
    private var assertionContinuation: CheckedContinuation<ASAuthorizationPlatformPublicKeyCredentialAssertion, Error>?
    
    /// 依赖方标识符（必须与 Associated Domains 配置匹配）
    private let relyingPartyIdentifier: String
    
    // MARK: - 初始化
    
    init(relyingPartyIdentifier: String) {
        self.relyingPartyIdentifier = relyingPartyIdentifier
        super.init()
    }
    
    // MARK: - 注册 Passkey
    
    /// 注册新的 Passkey
    /// - Parameters:
    ///   - challenge: 后端生成的 challenge（Base64URL 解码后的 Data）
    ///   - userID: 用户唯一标识（后端生成的稳定 ID）
    ///   - username: 显示的用户名（如邮箱）
    ///   - requestStyle: 请求样式（.modal 或 .conditional）
    /// - Returns: 注册凭证
    func registerPasskey(
        challenge: Data,
        userID: Data,
        username: String,
        requestStyle: ASAuthorization.RequestStyle = .modal
    ) async throws -> PasskeyRegistrationResponse {
        
        // 1. 创建凭证提供者
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(
            relyingPartyIdentifier: relyingPartyIdentifier
        )
        
        // 2. 创建注册请求
        let request = provider.createCredentialRegistrationRequest(
            challenge: challenge,
            name: username,
            userID: userID
        )
        
        // iOS 17+ 支持条件式注册（自动升级）
        if #available(iOS 17.0, macOS 14.0, *) {
            request.requestStyle = requestStyle
        }
        
        // 3. 创建授权控制器
        let controller = ASAuthorizationController(authorizationRequests: [request])
        controller.delegate = self
        controller.presentationContextProvider = self
        
        // 4. 执行请求并等待结果
        return try await withCheckedThrowingContinuation { continuation in
            self.registrationContinuation = continuation as? CheckedContinuation<ASAuthorizationPlatformPublicKeyCredentialRegistration, Error>
            controller.performRequests()
        }
    }
    
    /// 处理注册结果
    private func handleRegistration(
        credential: ASAuthorizationPlatformPublicKeyCredentialRegistration
    ) -> PasskeyRegistrationResponse {
        return PasskeyRegistrationResponse(
            credentialID: credential.credentialID,
            rawClientDataJSON: credential.rawClientDataJSON,
            rawAttestationObject: credential.rawAttestationObject
        )
    }
}

// MARK: - ASAuthorizationControllerDelegate

extension PasskeyManager: ASAuthorizationControllerDelegate {
    
    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        // 处理注册完成
        if let credential = authorization.credential 
            as? ASAuthorizationPlatformPublicKeyCredentialRegistration {
            registrationContinuation?.resume(returning: credential)
            registrationContinuation = nil
        }
        
        // 处理登录完成
        if let credential = authorization.credential 
            as? ASAuthorizationPlatformPublicKeyCredentialAssertion {
            assertionContinuation?.resume(returning: credential)
            assertionContinuation = nil
        }
    }
    
    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        // 处理注册错误
        if registrationContinuation != nil {
            registrationContinuation?.resume(throwing: error)
            registrationContinuation = nil
        }
        
        // 处理登录错误
        if assertionContinuation != nil {
            assertionContinuation?.resume(throwing: error)
            assertionContinuation = nil
        }
    }
}

// MARK: - ASAuthorizationControllerPresentationContextProviding

extension PasskeyManager: ASAuthorizationControllerPresentationContextProviding {
    
    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        // 返回当前窗口作为展示锚点
        return UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap { $0.windows }
            .first { $0.isKeyWindow } ?? UIWindow()
    }
}
```

### 后端交互流程

```swift
// MARK: - 注册流程协调器

final class RegistrationCoordinator: ObservableObject {
    
    private let passkeyManager: PasskeyManager
    private let apiService: APIService
    
    init(relyingPartyIdentifier: String, apiService: APIService) {
        self.passkeyManager = PasskeyManager(relyingPartyIdentifier: relyingPartyIdentifier)
        self.apiService = apiService
    }
    
    /// 完整的注册流程
    func registerPasskey(username: String) async {
        do {
            // 1. 从后端获取注册挑战
            let challengeResponse = try await apiService.requestRegistrationChallenge(
                username: username
            )
            
            // 2. 解码 challenge（假设后端返回 Base64URL 编码）
            guard let challengeData = base64URLDecode(challengeResponse.challenge),
                  let userIDData = base64URLDecode(challengeResponse.userID) else {
                throw PasskeyError.invalidChallenge
            }
            
            // 3. 调用系统创建 Passkey
            let credential = try await passkeyManager.registerPasskey(
                challenge: challengeData,
                userID: userIDData,
                username: username
            )
            
            // 4. 将凭证数据发送给后端验证并存储
            try await apiService.completeRegistration(
                credentialID: credential.credentialID,
                clientDataJSON: credential.rawClientDataJSON,
                attestationObject: credential.rawAttestationObject,
                userID: challengeResponse.userID
            )
            
            print("Passkey 注册成功！")
            
        } catch {
            handleError(error)
        }
    }
    
    /// Base64URL 解码
    private func base64URLDecode(_ string: String) -> Data? {
        var base64 = string
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        
        // 添加填充
        while base64.count % 4 != 0 {
            base64.append("=")
        }
        
        return Data(base64Encoded: base64)
    }
    
    private func handleError(_ error: Error) {
        // 错误处理逻辑
        print("注册失败: \(error.localizedDescription)")
    }
}

// MARK: - 错误类型

enum PasskeyError: Error {
    case invalidChallenge
    case serverError
    case userCancelled
    case notSupported
}
```

---

## 使用 Passkey 登录完整流程

### 流程图

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  用户选择     │────▶│ 请求登录挑战   │────▶│  后端生成    │
│  使用 Passkey │     │             │     │  Challenge  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                                               ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  后端验证签名  │◀────│ 发送签名数据   │◀────│ 系统使用私钥  │
│  并授予访问   │     │             │     │ 签名 Challenge│
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │  Face ID /  │
                                        │ Touch ID    │
                                        │ 验证        │
                                        └─────────────┘
```

### 完整代码实现

```swift
// MARK: - 登录数据模型

struct PasskeyLoginRequest {
    let challenge: Data
}

struct PasskeyLoginResponse {
    let credentialID: Data
    let rawClientDataJSON: Data
    let rawAuthenticatorData: Data
    let signature: Data
}

// MARK: - Passkey 登录管理器扩展

extension PasskeyManager {
    
    /// 使用 Passkey 登录
    /// - Parameters:
    ///   - challenge: 后端生成的 challenge
    ///   - allowedCredentials: 可选的凭证 ID 列表（用于限制可选账户）
    ///   - preferImmediatelyAvailableCredentials: 是否优先使用本地凭证
    /// - Returns: 登录断言
    func loginWithPasskey(
        challenge: Data,
        allowedCredentials: [Data]? = nil,
        preferImmediatelyAvailableCredentials: Bool = false
    ) async throws -> PasskeyLoginResponse {
        
        // 1. 创建凭证提供者
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(
            relyingPartyIdentifier: relyingPartyIdentifier
        )
        
        // 2. 创建断言请求
        let request = provider.createCredentialAssertionRequest(challenge: challenge)
        
        // 可选：添加允许的凭证列表（限制显示的账户）
        if let allowedCredentials = allowedCredentials {
            request.allowedCredentials = allowedCredentials.map { credentialID in
                ASAuthorizationPlatformPublicKeyCredentialDescriptor(
                    credentialID: credentialID
                )
            }
        }
        
        // 3. 创建授权控制器
        let controller = ASAuthorizationController(authorizationRequests: [request])
        controller.delegate = self
        controller.presentationContextProvider = self
        
        // 可选：设置优先使用立即可用的凭证
        if preferImmediatelyAvailableCredentials {
            // 如果没有本地凭证，会立即返回错误而不是显示二维码
            controller.performRequests(options: .preferImmediatelyAvailableCredentials)
        } else {
            controller.performRequests()
        }
        
        // 4. 等待结果
        let credential = try await withCheckedThrowingContinuation { continuation in
            self.assertionContinuation = continuation as? CheckedContinuation<ASAuthorizationPlatformPublicKeyCredentialAssertion, Error>
        }
        
        return PasskeyLoginResponse(
            credentialID: credential.credentialID,
            rawClientDataJSON: credential.rawClientDataJSON,
            rawAuthenticatorData: credential.rawAuthenticatorData,
            signature: credential.signature
        )
    }
}

// MARK: - 登录流程协调器

final class LoginCoordinator: ObservableObject {
    
    private let passkeyManager: PasskeyManager
    private let apiService: APIService
    
    @Published var isLoading = false
    @Published var errorMessage: String?
    
    init(relyingPartyIdentifier: String, apiService: APIService) {
        self.passkeyManager = PasskeyManager(relyingPartyIdentifier: relyingPartyIdentifier)
        self.apiService = apiService
    }
    
    /// 使用 Passkey 登录
    func loginWithPasskey() async {
        isLoading = true
        defer { isLoading = false }
        
        do {
            // 1. 从后端获取登录挑战
            let challengeResponse = try await apiService.requestLoginChallenge()
            
            guard let challengeData = base64URLDecode(challengeResponse.challenge) else {
                throw PasskeyError.invalidChallenge
            }
            
            // 2. 调用系统进行 Passkey 认证
            let assertion = try await passkeyManager.loginWithPasskey(
                challenge: challengeData
            )
            
            // 3. 将断言数据发送给后端验证
            let authResult = try await apiService.verifyLoginAssertion(
                credentialID: assertion.credentialID,
                clientDataJSON: assertion.rawClientDataJSON,
                authenticatorData: assertion.rawAuthenticatorData,
                signature: assertion.signature
            )
            
            // 4. 保存认证令牌
            await saveAuthToken(authResult.token)
            
            print("Passkey 登录成功！")
            
        } catch let error as ASAuthorizationError {
            handleAuthorizationError(error)
        } catch {
            errorMessage = "登录失败: \(error.localizedDescription)"
        }
    }
    
    /// 尝试使用本地凭证快速登录
    func tryQuickLogin() async -> Bool {
        do {
            let challengeResponse = try await apiService.requestLoginChallenge()
            
            guard let challengeData = base64URLDecode(challengeResponse.challenge) else {
                return false
            }
            
            // 尝试使用本地凭证，如果没有则立即失败
            let assertion = try await passkeyManager.loginWithPasskey(
                challenge: challengeData,
                preferImmediatelyAvailableCredentials: true
            )
            
            // 验证并登录
            let authResult = try await apiService.verifyLoginAssertion(
                credentialID: assertion.credentialID,
                clientDataJSON: assertion.rawClientDataJSON,
                authenticatorData: assertion.rawAuthenticatorData,
                signature: assertion.signature
            )
            
            await saveAuthToken(authResult.token)
            return true
            
        } catch {
            // 没有本地凭证或其他错误，返回 false
            return false
        }
    }
    
    private func handleAuthorizationError(_ error: ASAuthorizationError) {
        switch error.code {
        case .canceled:
            errorMessage = "用户取消了登录"
        case .invalidResponse:
            errorMessage = "无效的响应"
        case .notHandled:
            errorMessage = "请求未被处理"
        case .notInteractive:
            errorMessage = "需要用户交互"
        case .failed:
            errorMessage = "认证失败"
        @unknown default:
            errorMessage = "未知错误: \(error.localizedDescription)"
        }
    }
    
    private func saveAuthToken(_ token: String) async {
        // 保存到安全存储（如 Keychain）
        // ...
    }
    
    private func base64URLDecode(_ string: String) -> Data? {
        var base64 = string
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        while base64.count % 4 != 0 {
            base64.append("=")
        }
        return Data(base64Encoded: base64)
    }
}
```

---

## AutoFill 集成

### AutoFill 辅助登录

AutoFill 集成允许 Passkey 在用户聚焦用户名输入框时自动显示在键盘建议栏中。

```swift
// MARK: - AutoFill 集成

final class AutoFillPasskeyManager: NSObject {
    
    private var autoFillController: ASAuthorizationController?
    private weak var viewController: UIViewController?
    
    /// 启动 AutoFill 辅助请求
    /// 应在视图加载时调用，确保键盘出现时 Passkey 已就绪
    func startAutoFillAssistedRequests(
        challenge: Data,
        from viewController: UIViewController
    ) {
        self.viewController = viewController
        
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(
            relyingPartyIdentifier: "yourdomain.com"
        )
        
        let request = provider.createCredentialAssertionRequest(challenge: challenge)
        
        let controller = ASAuthorizationController(authorizationRequests: [request])
        controller.delegate = self
        controller.presentationContextProvider = self
        
        // 启动 AutoFill 辅助请求
        controller.performAutoFillAssistedRequests()
        
        self.autoFillController = controller
    }
    
    /// 取消 AutoFill 请求
    func cancelAutoFillRequests() {
        autoFillController?.cancel()
        autoFillController = nil
    }
}

extension AutoFillPasskeyManager: ASAuthorizationControllerDelegate {
    
    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        if let credential = authorization.credential 
            as? ASAuthorizationPlatformPublicKeyCredentialAssertion {
            // 处理登录断言
            handleAssertion(credential)
        }
    }
    
    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        // AutoFill 请求被取消或失败
        // 如果是用户手动输入，这是正常行为
        print("AutoFill 请求结束: \(error.localizedDescription)")
    }
    
    private func handleAssertion(_ credential: ASAuthorizationPlatformPublicKeyCredentialAssertion) {
        // 发送给后端验证
        // ...
    }
}

extension AutoFillPasskeyManager: ASAuthorizationControllerPresentationContextProviding {
    
    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        return viewController?.view.window ?? UIWindow()
    }
}

// MARK: - 在视图控制器中使用

class LoginViewController: UIViewController {
    
    @IBOutlet weak var usernameTextField: UITextField!
    
    private let autoFillManager = AutoFillPasskeyManager()
    
    override func viewDidLoad() {
        super.viewDidLoad()
        
        // 配置用户名输入框以支持 AutoFill
        usernameTextField.textContentType = .username
        
        // 启动 AutoFill 辅助请求
        Task {
            // 从后端获取 challenge
            let challenge = await fetchChallengeFromServer()
            autoFillManager.startAutoFillAssistedRequests(
                challenge: challenge,
                from: self
            )
        }
    }
    
    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        // 视图消失时取消请求
        autoFillManager.cancelAutoFillRequests()
    }
    
    /// 用户手动输入用户名后点击登录
    @IBAction func loginButtonTapped(_ sender: UIButton) {
        // 取消 AutoFill 请求
        autoFillManager.cancelAutoFillRequests()
        
        // 显示模态 Passkey 登录表单
        showModalPasskeyLogin()
    }
    
    private func showModalPasskeyLogin() {
        // 使用 performRequests() 显示模态表单
        // ...
    }
    
    private func fetchChallengeFromServer() async -> Data {
        // 从后端获取 challenge
        // ...
        return Data()
    }
}
```

---

## 错误处理

### ASAuthorizationError 代码详解

```swift
// MARK: - 错误处理

enum PasskeyErrorHandling {
    
    static func handle(_ error: Error) -> PasskeyErrorType {
        guard let authError = error as? ASAuthorizationError else {
            return .unknown(error)
        }
        
        switch authError.code {
        case .canceled:
            // 用户取消了操作
            // 可能原因：
            // - 用户点击了取消按钮
            // - 使用 preferImmediatelyAvailableCredentials 但没有本地凭证
            return .userCancelled
            
        case .invalidResponse:
            // 从授权服务收到无效响应
            // 可能原因：
            // - 后端返回的数据格式不正确
            // - challenge 解码失败
            return .invalidResponse
            
        case .notHandled:
            // 请求未被处理
            // 可能原因：
            // - 系统无法处理该请求
            // - Associated Domains 配置错误
            return .notHandled
            
        case .notInteractive:
            // 请求需要用户交互但当前无法提供
            // 可能原因：
            // - 应用在后台
            // - 有其他 UI 遮挡
            return .notInteractive
            
        case .failed:
            // 通用失败
            // 可能原因：
            // - 生物识别验证失败
            // - 设备未设置密码
            return .failed
            
        @unknown default:
            return .unknown(authError)
        }
    }
}

enum PasskeyErrorType: Error {
    case userCancelled
    case invalidResponse
    case notHandled
    case notInteractive
    case failed
    case unknown(Error)
    
    var localizedDescription: String {
        switch self {
        case .userCancelled:
            return "用户取消了操作"
        case .invalidResponse:
            return "收到无效响应，请检查配置"
        case .notHandled:
            return "请求无法处理，请检查 Associated Domains 配置"
        case .notInteractive:
            return "需要用户交互，请确保应用在前台"
        case .failed:
            return "认证失败，请重试"
        case .unknown(let error):
            return "未知错误: \(error.localizedDescription)"
        }
    }
    
    /// 是否应该显示错误提示
    var shouldShowError: Bool {
        switch self {
        case .userCancelled:
            return false  // 用户主动取消，不需要提示
        default:
            return true
        }
    }
    
    /// 是否应该回退到密码登录
    var shouldFallbackToPassword: Bool {
        switch self {
        case .userCancelled, .notHandled, .failed:
            return true
        default:
            return false
        }
    }
}

// MARK: - UI 展示

extension UIViewController {
    
    func showPasskeyError(_ error: PasskeyErrorType) {
        guard error.shouldShowError else { return }
        
        let alert = UIAlertController(
            title: "登录失败",
            message: error.localizedDescription,
            preferredStyle: .alert
        )
        
        if error.shouldFallbackToPassword {
            alert.addAction(UIAlertAction(title: "使用密码登录", style: .default) { _ in
                self.showPasswordLogin()
            })
        }
        
        alert.addAction(UIAlertAction(title: "取消", style: .cancel))
        
        present(alert, animated: true)
    }
    
    private func showPasswordLogin() {
        // 导航到密码登录界面
    }
}
```

---

## 与现有认证系统集成

### 自动 Passkey 升级

在用户使用密码登录后，自动为其创建 Passkey（iOS 17+）：

```swift
// MARK: - 自动 Passkey 升级

@available(iOS 17.0, macOS 14.0, *)
final class AutomaticPasskeyUpgradeManager {
    
    private let passkeyManager: PasskeyManager
    private let apiService: APIService
    
    init(relyingPartyIdentifier: String, apiService: APIService) {
        self.passkeyManager = PasskeyManager(relyingPartyIdentifier: relyingPartyIdentifier)
        self.apiService = apiService
    }
    
    /// 密码登录成功后尝试自动升级
    func attemptAutomaticUpgrade(userInfo: UserInfo) async {
        // 检查用户是否已有 Passkey
        guard !userInfo.hasPasskey else { return }
        
        do {
            // 从后端获取注册挑战
            let challengeResponse = try await apiService.requestRegistrationChallenge(
                username: userInfo.username
            )
            
            guard let challengeData = base64URLDecode(challengeResponse.challenge),
                  let userIDData = base64URLDecode(challengeResponse.userID) else {
                return
            }
            
            // 创建条件式注册请求
            let credential = try await passkeyManager.registerPasskey(
                challenge: challengeData,
                userID: userIDData,
                username: userInfo.username,
                requestStyle: .conditional  // 条件式注册
            )
            
            // 发送给后端完成注册
            try await apiService.completeRegistration(
                credentialID: credential.credentialID,
                clientDataJSON: credential.rawClientDataJSON,
                attestationObject: credential.rawAttestationObject,
                userID: challengeResponse.userID
            )
            
            // 系统会自动显示通知告知用户 Passkey 已创建
            print("自动升级成功！")
            
        } catch {
            // 自动升级失败，不显示错误，下次再尝试
            print("自动升级失败: \(error)")
        }
    }
}

// MARK: - 组合凭证请求

extension PasskeyManager {
    
    /// 同时请求 Passkey、密码和 Sign in with Apple
    func performCombinedRequest(
        passkeyChallenge: Data,
        passwordRequest: Bool = true,
        appleIDRequest: Bool = true
    ) async throws -> ASAuthorization {
        
        var requests: [ASAuthorizationRequest] = []
        
        // 1. Passkey 请求
        let passkeyProvider = ASAuthorizationPlatformPublicKeyCredentialProvider(
            relyingPartyIdentifier: relyingPartyIdentifier
        )
        let passkeyRequest = passkeyProvider.createCredentialAssertionRequest(
            challenge: passkeyChallenge
        )
        requests.append(passkeyRequest)
        
        // 2. 密码请求
        if passwordRequest {
            let passwordProvider = ASAuthorizationPasswordProvider()
            let passwordRequest = passwordProvider.createRequest()
            requests.append(passwordRequest)
        }
        
        // 3. Sign in with Apple 请求
        if appleIDRequest {
            let appleIDProvider = ASAuthorizationAppleIDProvider()
            let appleIDRequest = appleIDProvider.createRequest()
            appleIDRequest.requestedScopes = [.fullName, .email]
            requests.append(appleIDRequest)
        }
        
        // 创建组合控制器
        let controller = ASAuthorizationController(authorizationRequests: requests)
        controller.delegate = self
        controller.presentationContextProvider = self
        
        // 执行请求
        return try await withCheckedThrowingContinuation { continuation in
            // 保存 continuation 并在回调中处理
            // ...
            controller.performRequests()
        }
    }
}

// MARK: - 处理不同类型的凭证

extension LoginCoordinator {
    
    func handleAuthorization(_ authorization: ASAuthorization) {
        switch authorization.credential {
        
        case let passkeyAssertion as ASAuthorizationPlatformPublicKeyCredentialAssertion:
            // 处理 Passkey 登录
            verifyPasskeyAssertion(passkeyAssertion)
            
        case let passwordCredential as ASPasswordCredential:
            // 处理密码登录
            loginWithPassword(
                username: passwordCredential.user,
                password: passwordCredential.password
            )
            
        case let appleIDCredential as ASAuthorizationAppleIDCredential:
            // 处理 Sign in with Apple
            loginWithApple(appleIDCredential)
            
        default:
            break
        }
    }
    
    private func verifyPasskeyAssertion(
        _ credential: ASAuthorizationPlatformPublicKeyCredentialAssertion
    ) {
        // 发送给后端验证
        // ...
    }
    
    private func loginWithPassword(username: String, password: String) {
        // 密码登录流程
        // ...
    }
    
    private func loginWithApple(_ credential: ASAuthorizationAppleIDCredential) {
        // Sign in with Apple 流程
        // ...
    }
}
```

---

## 企业环境部署

### 企业级 Passkey 配置

```swift
// MARK: - 企业环境支持

@available(iOS 17.0, macOS 14.0, *)
final class EnterprisePasskeyManager {
    
    /// 检查是否支持企业认证
    func checkEnterpriseAttestationSupport() async -> Bool {
        // 检查设备是否由组织管理
        // 这需要配合 MDM 配置
        // ...
        return false
    }
    
    /// 使用企业认证创建 Passkey
    func registerWithEnterpriseAttestation(
        challenge: Data,
        userID: Data,
        username: String
    ) async throws -> PasskeyRegistrationResponse {
        
        let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(
            relyingPartyIdentifier: relyingPartyIdentifier
        )
        
        let request = provider.createCredentialRegistrationRequest(
            challenge: challenge,
            name: username,
            userID: userID
        )
        
        // 企业环境可能需要特定的 attestation 偏好
        // request.attestationPreference = .enterprise
        
        // ...
        
        return PasskeyRegistrationResponse(
            credentialID: Data(),
            rawClientDataJSON: Data(),
            rawAttestationObject: nil
        )
    }
}

// MARK: - 后端验证企业认证

/*
 后端需要验证企业认证的 attestation statement：
 
 1. 检查 AAGUID 是否为 Apple 设备值：
    dd4ec289-e01d-41c9-bb89-70fa845d4bf2
 
 2. 检查 packed attestation statement：
    {
        "fmt": "packed",
        "attStmt": {
            "alg": -7,  // ES256
            "sig": bytes,
            "x5c": [attestnCert, caCert]
        },
        "authData": {
            "attestedCredentialData": {
                "aaguid": "dd4ec289-e01d-41c9-bb89-70fa845d4bf2"
            }
        }
    }
 
 3. 验证证书链是否追溯到组织的 CA
 */
```

---

## 最佳实践总结

### 1. 用户体验最佳实践

```swift
// MARK: - UX 最佳实践

final class PasskeyUXBestPractices {
    
    /// ✅ 应该做的：
    
    // 1. 在视图加载早期启动 AutoFill 请求
    // 确保键盘出现时 Passkey 建议已就绪
    func viewDidLoad() {
        super.viewDidLoad()
        usernameField.textContentType = .username
        startAutoFillRequest()  // 尽早启动
    }
    
    // 2. 使用条件式注册进行自动升级
    // 用户不会被打断，系统会在后台创建 Passkey
    func signInWithPassword() {
        // ... 密码登录成功后
        Task {
            await attemptAutomaticPasskeyUpgrade()
        }
    }
    
    // 3. 提供清晰的反馈
    // 告知用户 Passkey 的好处
    func showPasskeyBenefits() {
        // "使用 Passkey 登录更快更安全"
        // "无需记住密码"
        // "防钓鱼保护"
    }
    
    // 4. 优雅降级
    // 当 Passkey 不可用时提供密码选项
    func handlePasskeyUnavailable() {
        showPasswordLoginOption()
    }
    
    /// ❌ 不应该做的：
    
    // 1. 不要强制用户立即升级
    // 使用条件式注册让用户无感知升级
    
    // 2. 不要在用户取消时显示错误
    // 用户取消是正常行为
    
    // 3. 不要在没有 Associated Domains 的情况下使用
    // 这会导致功能无法工作
    
    // 4. 不要假设所有设备都支持 Passkey
    // 检查系统版本和功能可用性
}
```

### 2. 安全最佳实践

```swift
// MARK: - 安全最佳实践

final class PasskeySecurityBestPractices {
    
    /// 1. 始终使用 userVerification: "preferred"（默认）
    /// 这确保在没有生物识别的设备上也能正常工作
    func createSecureRequest() {
        let request = provider.createCredentialAssertionRequest(challenge: challenge)
        // 不要修改 userVerification 设置，使用默认值
    }
    
    /// 2. 验证后端响应
    /// - 验证 challenge 的随机性和唯一性
    /// - 验证 origin 匹配你的域名
    /// - 验证签名正确性
    func verifyServerResponse() {
        // 后端应该验证：
        // - clientDataJSON 中的 origin
        // - challenge 匹配
        // - 签名使用存储的公钥验证
    }
    
    /// 3. 安全存储凭证 ID
    /// 凭证 ID 不是敏感信息，但需要关联到用户账户
    func storeCredentialID() {
        // 存储在用户账户数据中
        // 用于后续登录时识别用户
    }
    
    /// 4. 支持凭证撤销
    /// 用户应该能够删除/撤销 Passkey
    func revokePasskey(credentialID: Data) {
        // 从后端删除该凭证
        // 从设备删除（用户可以在系统设置中操作）
    }
}
```

### 3. 实现检查清单

```markdown
## Passkey 实现检查清单

### 配置
- [ ] 在 Xcode 中启用 Associated Domains
- [ ] 配置 webcredentials:yourdomain.com
- [ ] 创建并部署 apple-app-site-association 文件
- [ ] 验证 HTTPS 可访问性
- [ ] 测试域名关联

### 后端
- [ ] 实现 WebAuthn 服务器
- [ ] 生成随机 challenge
- [ ] 验证 attestation（注册时）
- [ ] 验证 assertion（登录时）
- [ ] 安全存储公钥
- [ ] 实现凭证撤销

### iOS 应用
- [ ] 导入 AuthenticationServices
- [ ] 实现 ASAuthorizationControllerDelegate
- [ ] 实现 ASAuthorizationControllerPresentationContextProviding
- [ ] 配置用户名输入框的 textContentType
- [ ] 实现注册流程
- [ ] 实现登录流程
- [ ] 实现 AutoFill 集成
- [ ] 处理错误情况
- [ ] 测试跨设备认证

### 测试
- [ ] 在真机上测试（模拟器不支持）
- [ ] 测试 Face ID / Touch ID
- [ ] 测试设备密码回退
- [ ] 测试跨设备登录（二维码）
- [ ] 测试取消操作
- [ ] 测试网络错误
- [ ] 测试后端验证失败
```

### 4. 快速参考代码

```swift
// MARK: - 快速参考：完整登录流程

import AuthenticationServices
import SwiftUI

struct PasskeyLoginView: View {
    @State private var username = ""
    @State private var isLoading = false
    
    private let relyingPartyIdentifier = "yourdomain.com"
    
    var body: some View {
        VStack(spacing: 20) {
            TextField("用户名或邮箱", text: $username)
                .textContentType(.username)  // 关键：启用 AutoFill
                .textFieldStyle(RoundedBorderTextFieldStyle())
                .padding()
            
            Button(action: signInWithPasskey) {
                if isLoading {
                    ProgressView()
                } else {
                    Text("使用 Passkey 登录")
                }
            }
            .disabled(username.isEmpty || isLoading)
        }
        .padding()
        .task {
            // 视图出现时启动 AutoFill
            await startAutoFill()
        }
    }
    
    private func startAutoFill() async {
        // 获取 challenge 并启动 AutoFill
        // ...
    }
    
    private func signInWithPasskey() {
        isLoading = true
        Task {
            do {
                let challenge = await fetchChallenge()
                let provider = ASAuthorizationPlatformPublicKeyCredentialProvider(
                    relyingPartyIdentifier: relyingPartyIdentifier
                )
                let request = provider.createCredentialAssertionRequest(challenge: challenge)
                
                let controller = ASAuthorizationController(authorizationRequests: [request])
                // 设置 delegate 和 presentationContextProvider
                // ...
                
                controller.performRequests()
            }
            isLoading = false
        }
    }
    
    private func fetchChallenge() async -> Data {
        // 从后端获取
        Data()
    }
}
```

---

## 参考资源

### 官方文档
- [Supporting passkeys](https://developer.apple.com/documentation/authenticationservices/supporting-passkeys)
- [Connecting to a service with passkeys](https://developer.apple.com/documentation/authenticationservices/connecting-to-a-service-with-passkeys)
- [ASAuthorizationController](https://developer.apple.com/documentation/authenticationservices/asauthorizationcontroller)

### WWDC 视频
- [WWDC22 - Meet passkeys](https://developer.apple.com/videos/play/wwdc2022/10092/)
- [WWDC23 - Deploy passkeys at work](https://developer.apple.com/videos/play/wwdc2023/10263/)
- [WWDC24 - Streamline sign-in with passkey upgrades](https://developer.apple.com/videos/play/wwdc2024/10125/)

### 社区资源
- [passkeys.dev - iOS & iPadOS Reference](https://passkeys.dev/docs/reference/ios)
- [WebAuthn Specification](https://www.w3.org/TR/webauthn-2/)
- [FIDO Alliance](https://fidoalliance.org/)

---

*最后更新：2026年3月*
*适用于 iOS 16.0+, iPadOS 16.0+, macOS 13.0+*
