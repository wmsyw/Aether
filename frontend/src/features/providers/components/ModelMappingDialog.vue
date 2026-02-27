<template>
  <Dialog
    :model-value="open"
    :title="editingGroup ? '编辑模型映射' : '添加模型映射'"
    :description="editingGroup ? '修改映射配置' : '将提供商模型映射到客户端模型'"
    :icon="Tag"
    size="lg"
    @update:model-value="$emit('update:open', $event)"
  >
    <div class="space-y-4">
      <!-- 目标模型选择 -->
      <div class="space-y-1.5">
        <Label class="text-xs">客户端模型</Label>
        <Select
          :model-value="formData.modelId"
          :disabled="!!editingGroup"
          @update:model-value="handleModelChange"
        >
          <SelectTrigger class="h-9">
            <SelectValue placeholder="请选择客户端模型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem
              v-for="model in models"
              :key="model.id"
              :value="model.id"
            >
              <div class="flex items-center gap-2">
                <span class="font-medium">{{ model.global_model_display_name || model.provider_model_name }}</span>
                <span class="text-xs text-muted-foreground font-mono">{{ model.provider_model_name }}</span>
              </div>
            </SelectItem>
          </SelectContent>
        </Select>
        <p class="text-xs text-muted-foreground">
          客户端请求此模型时，将路由到选中的提供商模型
        </p>
      </div>

      <!-- 映射名称选择面板 -->
      <div class="space-y-1.5">
        <Label class="text-xs">提供商模型</Label>
        <!-- 搜索栏 -->
        <div class="flex items-center gap-2">
          <div class="flex-1 relative">
            <Search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              v-model="searchQuery"
              placeholder="搜索或添加自定义提供商模型..."
              class="pl-8 h-9"
            />
          </div>
          <!-- 已选数量徽章 -->
          <span
            v-if="selectedNames.length === 0"
            class="h-7 px-2.5 text-xs rounded-md flex items-center bg-muted text-muted-foreground shrink-0"
          >
            未选择
          </span>
          <span
            v-else
            class="h-7 px-2.5 text-xs rounded-md flex items-center bg-primary/10 text-primary shrink-0"
          >
            已选 {{ selectedNames.length }} 个
          </span>
        </div>

        <!-- 模型列表 -->
        <div class="border rounded-lg overflow-hidden">
          <div class="min-h-60 max-h-80 overflow-y-auto">
            <!-- 加载中 -->
            <div
              v-if="loadingModels"
              class="flex items-center justify-center py-12"
            >
              <Loader2 class="w-6 h-6 animate-spin text-primary" />
            </div>

            <template v-else>
              <!-- 添加自定义映射名称（搜索内容不在列表中时显示） -->
              <div
                v-if="searchQuery && canAddAsCustom"
                class="px-3 py-2 border-b bg-background sticky top-0 z-30"
              >
                <div
                  class="flex items-center justify-between px-3 py-2 rounded-lg border border-dashed hover:border-primary hover:bg-primary/5 cursor-pointer transition-colors"
                  @click="addCustomName"
                >
                  <div class="flex items-center gap-2">
                    <Plus class="w-4 h-4 text-muted-foreground" />
                    <span class="text-sm font-mono">{{ searchQuery }}</span>
                  </div>
                  <span class="text-xs text-muted-foreground">添加自定义提供商模型</span>
                </div>
              </div>

              <!-- 自定义映射名称 -->
              <div v-if="customNames.length > 0">
                <div
                  class="flex items-center justify-between px-3 py-2 bg-muted sticky top-0 z-20"
                >
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-medium">自定义模型</span>
                    <span class="text-xs text-muted-foreground">({{ customNames.length }})</span>
                  </div>
                </div>
                <div class="space-y-1 p-2">
                  <div
                    v-for="name in sortedCustomNames"
                    :key="name"
                    class="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted cursor-pointer"
                    @click="toggleName(name)"
                  >
                    <div
                      class="w-4 h-4 border rounded flex items-center justify-center shrink-0"
                      :class="selectedNames.includes(name) ? 'bg-primary border-primary' : ''"
                    >
                      <Check
                        v-if="selectedNames.includes(name)"
                        class="w-3 h-3 text-primary-foreground"
                      />
                    </div>
                    <span class="text-sm font-mono truncate flex-1">{{ name }}</span>
                  </div>
                </div>
              </div>

              <!-- 空状态 -->
              <div
                v-if="showEmptyState"
                class="flex flex-col items-center justify-center py-12 text-muted-foreground"
              >
                <Tag class="w-10 h-10 mb-2 opacity-30" />
                <p class="text-sm">
                  {{ searchQuery ? '无匹配结果' : '暂无可选模型' }}
                </p>
                <p class="text-xs mt-1">
                  输入模型名称后点击添加自定义提供商模型
                </p>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <Button
        variant="outline"
        @click="$emit('update:open', false)"
      >
        取消
      </Button>
      <Button
        :disabled="submitting || !formData.modelId || selectedNames.length === 0"
        @click="handleSubmit"
      >
        <Loader2
          v-if="submitting"
          class="w-4 h-4 mr-2 animate-spin"
        />
        {{ editingGroup ? '保存' : '添加' }}
      </Button>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Tag, Loader2, Plus, Search, Check } from 'lucide-vue-next'
import {
  Button,
  Input,
  Label,
  Dialog,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui'
import { useToast } from '@/composables/useToast'
import { parseApiError } from '@/utils/errorParser'
import {
  type Model,
  type ProviderModelAlias,
} from '@/api/endpoints'
import { updateModel } from '@/api/endpoints/models'

export interface AliasGroup {
  model: Model
  /** @deprecated */
  apiFormatsKey: string
  /** @deprecated */
  apiFormats: string[]
  aliases: ProviderModelAlias[]
}

const props = defineProps<{
  open: boolean
  providerId: string
  /** @deprecated */
  providerApiFormats?: string[]
  models: Model[]
  editingGroup?: AliasGroup | null
  preselectedModelId?: string | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'saved': []
}>()

const { error: showError, success: showSuccess } = useToast()

// 状态
const submitting = ref(false)
const loadingModels = ref(false)

// 搜索
const searchQuery = ref('')

// 表单数据
const formData = ref<{
  modelId: string
}>({
  modelId: ''
})

// 选中的映射名称
const selectedNames = ref<string[]>([])

// 自定义名称列表（手动添加的）
const allCustomNames = ref<string[]>([])

// 自定义名称列表
const customNames = computed(() => {
  return allCustomNames.value
})

// 排序后的自定义名称
const sortedCustomNames = computed(() => {
  const search = searchQuery.value.toLowerCase().trim()
  if (!search) return customNames.value

  const matched: string[] = []
  const unmatched: string[] = []
  for (const name of customNames.value) {
    if (name.toLowerCase().includes(search)) {
      matched.push(name)
    } else {
      unmatched.push(name)
    }
  }
  return [...matched, ...unmatched]
})

// 判断搜索内容是否可以作为自定义名称添加
const canAddAsCustom = computed(() => {
  const search = searchQuery.value.trim()
  if (!search) return false
  if (selectedNames.value.includes(search)) return false
  if (allCustomNames.value.includes(search)) return false
  return true
})

// 空状态判断
const showEmptyState = computed(() => {
  return customNames.value.length === 0
})

// 切换名称选中状态
function toggleName(name: string) {
  const idx = selectedNames.value.indexOf(name)
  if (idx === -1) {
    selectedNames.value.push(name)
  } else {
    selectedNames.value.splice(idx, 1)
  }
}

// 添加自定义名称
function addCustomName() {
  const name = searchQuery.value.trim()
  if (name && !selectedNames.value.includes(name)) {
    selectedNames.value.push(name)
    if (!allCustomNames.value.includes(name)) {
      allCustomNames.value.push(name)
    }
    searchQuery.value = ''
  }
}

// 监听打开状态
watch(() => props.open, async (isOpen) => {
  if (isOpen) {
    initForm()
  }
})

// 初始化表单
function initForm() {
  if (props.editingGroup) {
    formData.value = {
      modelId: props.editingGroup.model.id
    }
    const existingNames = props.editingGroup.aliases.map(a => a.name)
    selectedNames.value = [...existingNames]
    allCustomNames.value = [...existingNames]
  } else {
    formData.value = {
      modelId: props.preselectedModelId || ''
    }
    selectedNames.value = []
    allCustomNames.value = []
  }
  searchQuery.value = ''
}

// 处理模型选择变更
function handleModelChange(value: string) {
  formData.value.modelId = value
}

// 生成作用域唯一键
function getApiFormatsKey(formats: string[] | undefined): string {
  if (!formats || formats.length === 0) return ''
  return [...formats].sort().join(',')
}

// 提交表单
async function handleSubmit() {
  if (submitting.value) return
  if (!formData.value.modelId || selectedNames.value.length === 0) return

  submitting.value = true
  try {
    const targetModel = props.models.find(m => m.id === formData.value.modelId)
    if (!targetModel) {
      showError('模型不存在', '错误')
      return
    }

    const currentAliases = targetModel.provider_model_mappings || []
    let newAliases: ProviderModelAlias[]

    const buildAliases = (names: string[]): ProviderModelAlias[] => {
      return names.map((name) => ({
        name: name.trim(),
        priority: 1
      }))
    }

    if (props.editingGroup) {
      const oldApiFormatsKey = props.editingGroup.apiFormatsKey
      const oldAliasNames = new Set(props.editingGroup.aliases.map(a => a.name))

      const filteredAliases = currentAliases.filter((a: ProviderModelAlias) => {
        const currentKey = getApiFormatsKey(a.api_formats)
        return !(currentKey === oldApiFormatsKey && oldAliasNames.has(a.name))
      })

      const existingNames = new Set(filteredAliases.map((a: ProviderModelAlias) => a.name))
      const duplicates = selectedNames.value.filter(name => existingNames.has(name))
      if (duplicates.length > 0) {
        showError(`以下映射名称已存在：${duplicates.join(', ')}`, '错误')
        return
      }

      newAliases = [
        ...filteredAliases,
        ...buildAliases(selectedNames.value)
      ]
    } else {
      const existingNames = new Set(currentAliases.map((a: ProviderModelAlias) => a.name))
      const duplicates = selectedNames.value.filter(name => existingNames.has(name))
      if (duplicates.length > 0) {
        showError(`以下映射名称已存在：${duplicates.join(', ')}`, '错误')
        return
      }
      newAliases = [
        ...currentAliases,
        ...buildAliases(selectedNames.value)
      ]
    }

    await updateModel(props.providerId, targetModel.id, {
      provider_model_mappings: newAliases
    })

    showSuccess(props.editingGroup ? '映射组已更新' : '映射已添加')
    emit('update:open', false)
    emit('saved')
  } catch (err: unknown) {
    showError(parseApiError(err, '操作失败'), '错误')
  } finally {
    submitting.value = false
  }
}
</script>
