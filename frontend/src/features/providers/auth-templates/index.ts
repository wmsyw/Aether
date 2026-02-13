/**
 * 提供商认证模板
 *
 * Schema-Driven 模式：后端返回 JSON Schema（含 x-* 扩展字段），
 * 前端根据 schema 动态渲染表单、构建请求、格式化显示。
 * 新增架构只需后端一个文件，前端零改动。
 */

export * from './types'
export * from './schema-utils'
export { executeFieldHook } from './field-hooks'
