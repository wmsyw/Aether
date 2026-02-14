<template>
  <CardSection
    title="定时任务"
    description="配置系统后台定时任务"
  >
    <div class="space-y-3">
      <template
        v-for="task in scheduledTasks"
        :key="task.id"
      >
        <div
          class="group relative rounded-xl border transition-all duration-300"
          :class="task.enabled
            ? 'border-primary/30 bg-primary/[0.02] shadow-sm shadow-primary/5'
            : 'border-border bg-card hover:border-border/80'"
        >
          <!-- 主行 -->
          <div class="flex items-center gap-4 p-4">
            <!-- 左侧：开关 -->
            <div class="shrink-0">
              <Switch
                :id="`enable-${task.id}`"
                :model-value="task.enabled"
                @update:model-value="task.onToggle"
              />
            </div>

            <!-- 中间：图标、标题、描述 -->
            <div class="flex items-center gap-3 flex-1 min-w-0">
              <div
                class="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 transition-colors duration-300"
                :class="task.enabled
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground'"
              >
                <component
                  :is="task.icon"
                  class="w-4.5 h-4.5"
                />
              </div>
              <div class="flex-1 min-w-0">
                <h4 class="font-medium text-sm">
                  {{ task.title }}
                </h4>
                <p class="text-xs text-muted-foreground mt-0.5 truncate">
                  {{ task.description }}
                </p>
              </div>
            </div>

            <!-- 右侧：时间选择器 + 保存按钮 -->
            <div
              v-if="task.enabled && task.hasTimeConfig"
              class="flex items-center gap-2 shrink-0"
            >
              <Clock class="w-4 h-4 text-muted-foreground" />
              <Select
                :model-value="task.hour"
                @update:model-value="(val: string) => task.updateTime(val, task.minute)"
              >
                <SelectTrigger class="w-14 h-8 text-xs">
                  <SelectValue placeholder="时" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem
                    v-for="h in 24"
                    :key="h - 1"
                    :value="String(h - 1).padStart(2, '0')"
                  >
                    {{ String(h - 1).padStart(2, '0') }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <span class="text-sm text-muted-foreground">:</span>
              <Select
                :model-value="task.minute"
                @update:model-value="(val: string) => task.updateTime(task.hour, val)"
              >
                <SelectTrigger class="w-14 h-8 text-xs">
                  <SelectValue placeholder="分" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem
                    v-for="m in 60"
                    :key="m - 1"
                    :value="String(m - 1).padStart(2, '0')"
                  >
                    {{ String(m - 1).padStart(2, '0') }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <Button
                v-if="task.hasChanges"
                variant="default"
                size="sm"
                class="h-8 px-2.5 text-xs"
                :disabled="task.loading"
                @click="task.onSave"
              >
                <Check
                  v-if="!task.loading"
                  class="w-3.5 h-3.5"
                />
                <Loader2
                  v-else
                  class="w-3.5 h-3.5 animate-spin"
                />
              </Button>
            </div>
          </div>

          <!-- 额外配置区域（仅用户配额重置任务有） -->
          <div
            v-if="task.id === 'user-quota-reset' && task.enabled"
            class="px-4 pb-4 pt-0"
          >
            <div class="flex items-center gap-3 p-3 rounded-lg bg-muted/30 border border-border/50">
              <div class="flex items-center gap-2 text-sm">
                <span class="text-muted-foreground">重置周期</span>
                <div class="flex items-center gap-1.5">
                  <span class="text-muted-foreground">每</span>
                  <Input
                    :model-value="quotaResetIntervalDays"
                    type="number"
                    min="1"
                    step="1"
                    class="w-14 h-7 text-xs text-center px-2"
                    @update:model-value="$emit('update:quotaResetIntervalDays', Number($event))"
                  />
                  <span class="text-muted-foreground">天</span>
                </div>
              </div>
            </div>
            <p class="text-[11px] text-muted-foreground mt-2 ml-1">
              滚动计算：距离上次成功执行满 N 天后再次执行
            </p>
          </div>
        </div>
      </template>
    </div>
  </CardSection>
</template>

<script setup lang="ts">
import { Clock, Check, Loader2 } from 'lucide-vue-next'
import Button from '@/components/ui/button.vue'
import Input from '@/components/ui/input.vue'
import Switch from '@/components/ui/switch.vue'
import Select from '@/components/ui/select.vue'
import SelectTrigger from '@/components/ui/select-trigger.vue'
import SelectValue from '@/components/ui/select-value.vue'
import SelectContent from '@/components/ui/select-content.vue'
import SelectItem from '@/components/ui/select-item.vue'
import { CardSection } from '@/components/layout'
import type { Component } from 'vue'

interface ScheduledTask {
  id: string
  icon: Component
  title: string
  description: string
  enabled: boolean
  hasTimeConfig: boolean
  hour: string
  minute: string
  updateTime: (hour: string, minute: string) => void
  hasChanges: boolean
  loading: boolean
  onToggle: (enabled: boolean) => void
  onSave: () => void
}

defineProps<{
  scheduledTasks: ScheduledTask[]
  quotaResetIntervalDays: number
}>()

defineEmits<{
  'update:quotaResetIntervalDays': [value: number]
}>()
</script>
