<template>
  <PageContainer>
    <PageHeader
      title="系统设置"
      description="管理系统级别的配置和参数"
    />

    <div class="mt-6 space-y-6">
      <!-- 站点信息 -->
      <SiteInfoSection
        :site-name="systemConfig.site_name"
        :site-subtitle="systemConfig.site_subtitle"
        :loading="siteInfoLoading"
        :has-changes="hasSiteInfoChanges"
        @save="saveSiteInfo"
        @update:site-name="systemConfig.site_name = $event"
        @update:site-subtitle="systemConfig.site_subtitle = $event"
      />

      <!-- 配置导出/导入 -->
      <ConfigManagementSection
        :export-loading="exportLoading"
        :import-loading="importLoading"
        @export="handleExportConfig"
        @file-select="handleConfigFileSelect"
      />

      <!-- 用户数据导出/导入 -->
      <UserDataSection
        :export-loading="exportUsersLoading"
        :import-loading="importUsersLoading"
        @export="handleExportUsers"
        @file-select="handleUsersFileSelect"
      />

      <!-- 网络代理 -->
      <ProxyConfigSection
        :proxy-node-id="systemConfig.system_proxy_node_id"
        :online-nodes="proxyNodesStore.onlineNodes"
        :loading="proxyConfigLoading"
        :has-changes="hasProxyConfigChanges"
        @save="saveProxyConfig"
        @update:proxy-node-id="systemConfig.system_proxy_node_id = $event"
      />

      <!-- 基础配置 -->
      <BasicConfigSection
        :default-user-quota-usd="systemConfig.default_user_quota_usd"
        :rate-limit-per-minute="systemConfig.rate_limit_per_minute"
        :enable-registration="systemConfig.enable_registration"
        :auto-delete-expired-keys="systemConfig.auto_delete_expired_keys"
        :enable-format-conversion="systemConfig.enable_format_conversion"
        :loading="basicConfigLoading"
        :has-changes="hasBasicConfigChanges"
        @save="saveBasicConfig"
        @update:default-user-quota-usd="systemConfig.default_user_quota_usd = $event"
        @update:rate-limit-per-minute="systemConfig.rate_limit_per_minute = $event"
        @update:enable-registration="systemConfig.enable_registration = $event"
        @update:auto-delete-expired-keys="systemConfig.auto_delete_expired_keys = $event"
        @update:enable-format-conversion="systemConfig.enable_format_conversion = $event"
      />

      <!-- 请求记录配置 -->
      <RequestLogSection
        :request-record-level="systemConfig.request_record_level"
        :max-request-body-size-k-b="maxRequestBodySizeKB"
        :max-response-body-size-k-b="maxResponseBodySizeKB"
        :sensitive-headers-str="sensitiveHeadersStr"
        :loading="logConfigLoading"
        :has-changes="hasLogConfigChanges"
        @save="saveLogConfig"
        @update:request-record-level="systemConfig.request_record_level = $event"
        @update:max-request-body-size-k-b="maxRequestBodySizeKB = $event"
        @update:max-response-body-size-k-b="maxResponseBodySizeKB = $event"
        @update:sensitive-headers-str="sensitiveHeadersStr = $event"
      />

      <!-- 请求记录清理策略 -->
      <CleanupPolicySection
        :enable-auto-cleanup="systemConfig.enable_auto_cleanup"
        :detail-log-retention-days="systemConfig.detail_log_retention_days"
        :compressed-log-retention-days="systemConfig.compressed_log_retention_days"
        :header-retention-days="systemConfig.header_retention_days"
        :log-retention-days="systemConfig.log_retention_days"
        :cleanup-batch-size="systemConfig.cleanup_batch_size"
        :audit-log-retention-days="systemConfig.audit_log_retention_days"
        :loading="cleanupConfigLoading"
        :has-changes="hasCleanupConfigChanges"
        @save="saveCleanupConfig"
        @toggle-auto-cleanup="handleAutoCleanupToggle"
        @update:detail-log-retention-days="systemConfig.detail_log_retention_days = $event"
        @update:compressed-log-retention-days="systemConfig.compressed_log_retention_days = $event"
        @update:header-retention-days="systemConfig.header_retention_days = $event"
        @update:log-retention-days="systemConfig.log_retention_days = $event"
        @update:cleanup-batch-size="systemConfig.cleanup_batch_size = $event"
        @update:audit-log-retention-days="systemConfig.audit_log_retention_days = $event"
      />

      <!-- 定时任务 -->
      <ScheduledTasksSection
        :scheduled-tasks="scheduledTasks"
        :quota-reset-interval-days="systemConfig.user_quota_reset_interval_days"
        @update:quota-reset-interval-days="systemConfig.user_quota_reset_interval_days = $event"
      />

      <!-- 系统版本信息 -->
      <SystemInfoSection :system-version="systemVersion" />
    </div>

    <!-- 导入配置对话框 -->
    <ConfigImportDialog
      :import-dialog-open="importDialogOpen"
      :import-result-dialog-open="importResultDialogOpen"
      :import-preview="importPreview"
      :import-result="importResult"
      :merge-mode="mergeMode"
      :merge-mode-select-open="mergeModeSelectOpen"
      :import-loading="importLoading"
      @confirm="confirmImport"
      @update:import-dialog-open="importDialogOpen = $event"
      @update:import-result-dialog-open="importResultDialogOpen = $event"
      @update:merge-mode="mergeMode = $event"
      @update:merge-mode-select-open="mergeModeSelectOpen = $event"
    />

    <!-- 用户数据导入对话框 -->
    <UsersImportDialog
      :import-users-dialog-open="importUsersDialogOpen"
      :import-users-result-dialog-open="importUsersResultDialogOpen"
      :import-users-preview="importUsersPreview"
      :import-users-result="importUsersResult"
      :users-merge-mode="usersMergeMode"
      :users-merge-mode-select-open="usersMergeModeSelectOpen"
      :import-users-loading="importUsersLoading"
      @confirm="confirmImportUsers"
      @update:import-users-dialog-open="importUsersDialogOpen = $event"
      @update:import-users-result-dialog-open="importUsersResultDialogOpen = $event"
      @update:users-merge-mode="usersMergeMode = $event"
      @update:users-merge-mode-select-open="usersMergeModeSelectOpen = $event"
    />
  </PageContainer>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { PageHeader, PageContainer } from '@/components/layout'
import { useProxyNodesStore } from '@/stores/proxy-nodes'

// Composables
import { useSystemConfig } from './system-settings/composables/useSystemConfig'
import { useConfigExportImport } from './system-settings/composables/useConfigExportImport'
import { useScheduledTasks } from './system-settings/composables/useScheduledTasks'

// Section components
import SiteInfoSection from './system-settings/SiteInfoSection.vue'
import ConfigManagementSection from './system-settings/ConfigManagementSection.vue'
import UserDataSection from './system-settings/UserDataSection.vue'
import ProxyConfigSection from './system-settings/ProxyConfigSection.vue'
import BasicConfigSection from './system-settings/BasicConfigSection.vue'
import RequestLogSection from './system-settings/RequestLogSection.vue'
import CleanupPolicySection from './system-settings/CleanupPolicySection.vue'
import ScheduledTasksSection from './system-settings/ScheduledTasksSection.vue'
import SystemInfoSection from './system-settings/SystemInfoSection.vue'

// Dialog components
import ConfigImportDialog from './system-settings/ConfigImportDialog.vue'
import UsersImportDialog from './system-settings/UsersImportDialog.vue'

const proxyNodesStore = useProxyNodesStore()

// System config composable
const {
  systemConfig,
  systemVersion,
  siteInfoLoading,
  proxyConfigLoading,
  basicConfigLoading,
  logConfigLoading,
  cleanupConfigLoading,
  hasSiteInfoChanges,
  hasProxyConfigChanges,
  hasBasicConfigChanges,
  hasLogConfigChanges,
  hasCleanupConfigChanges,
  maxRequestBodySizeKB,
  maxResponseBodySizeKB,
  sensitiveHeadersStr,
  loadSystemConfig,
  loadSystemVersion,
  saveSiteInfo,
  saveProxyConfig,
  saveBasicConfig,
  saveLogConfig,
  saveCleanupConfig,
  handleAutoCleanupToggle,
} = useSystemConfig()

// Config export/import composable
const {
  exportLoading,
  importLoading,
  importDialogOpen,
  importResultDialogOpen,
  importPreview,
  importResult,
  mergeMode,
  mergeModeSelectOpen,
  handleExportConfig,
  handleConfigFileSelect,
  confirmImport,
  exportUsersLoading,
  importUsersLoading,
  importUsersDialogOpen,
  importUsersResultDialogOpen,
  importUsersPreview,
  importUsersResult,
  usersMergeMode,
  usersMergeModeSelectOpen,
  handleExportUsers,
  handleUsersFileSelect,
  confirmImportUsers,
} = useConfigExportImport(systemConfig)

// Scheduled tasks composable
const {
  scheduledTasks,
  initPreviousValues,
} = useScheduledTasks(systemConfig)

onMounted(async () => {
  await Promise.all([
    loadSystemConfig(),
    loadSystemVersion(),
    proxyNodesStore.ensureLoaded(),
  ])
  // 配置加载完成后初始化定时任务的原始值
  initPreviousValues()
})
</script>
