import { ref, computed, onBeforeUnmount } from 'vue'
import { TOTP, Secret } from 'otpauth'

/**
 * TOTP composable: 给定 secret 持续生成验证码并显示剩余秒数。
 */
export function useTotp() {
  const secret = ref('')
  const code = ref('')
  const remaining = ref(0)
  const error = ref('')

  let timer: ReturnType<typeof setInterval> | null = null
  let totp: TOTP | null = null

  function parseSecret(raw: string): Secret | null {
    const cleaned = raw.replace(/[\s-]/g, '')
    if (!cleaned) return null
    try {
      return Secret.fromBase32(cleaned.toUpperCase())
    } catch {
      // 尝试 hex
    }
    try {
      return Secret.fromHex(cleaned)
    } catch {
      return null
    }
  }

  function generate(): void {
    if (!totp) {
      code.value = ''
      remaining.value = 0
      return
    }
    code.value = totp.generate()
    const epoch = Math.floor(Date.now() / 1000)
    remaining.value = totp.period - (epoch % totp.period)
  }

  function start(rawSecret: string): void {
    stop()
    error.value = ''
    secret.value = rawSecret

    const parsed = parseSecret(rawSecret)
    if (!parsed) {
      error.value = rawSecret.trim() ? 'Secret 格式无效' : ''
      return
    }

    totp = new TOTP({ secret: parsed, digits: 6, period: 30 })
    generate()
    timer = setInterval(generate, 1000)
  }

  function stop(): void {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    totp = null
    code.value = ''
    remaining.value = 0
    error.value = ''
  }

  onBeforeUnmount(stop)

  return {
    secret,
    code: computed(() => code.value),
    remaining: computed(() => remaining.value),
    error: computed(() => error.value),
    start,
    stop,
  }
}
