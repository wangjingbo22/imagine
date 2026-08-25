export type AMapPosition = [number, number]

export interface AMapMapInstance {
  add(overlays: unknown | unknown[]): void
  addControl(control: unknown): void
  destroy(): void
  resize(): void
  setFitView(overlays?: unknown[], immediately?: boolean, avoid?: number[], maxZoom?: number): void
}

export interface AMapOverlay {
  on(eventName: string, handler: () => void): void
}

export interface AMapInfoWindowInstance {
  open(map: AMapMapInstance, position: AMapPosition): void
}

interface AMapMapConstructor {
  new(container: HTMLElement, options: Record<string, unknown>): AMapMapInstance
}

interface AMapOverlayConstructor {
  new(options: Record<string, unknown>): AMapOverlay
}

interface AMapInfoWindowConstructor {
  new(options: Record<string, unknown>): AMapInfoWindowInstance
}

interface AMapSimpleConstructor {
  new(...args: unknown[]): unknown
}

export interface AMapNamespace {
  Map: AMapMapConstructor
  Marker: AMapOverlayConstructor
  Polyline: AMapOverlayConstructor
  InfoWindow: AMapInfoWindowConstructor
  Pixel: AMapSimpleConstructor
  Scale: AMapSimpleConstructor
  ToolBar: AMapSimpleConstructor
}

declare global {
  interface Window {
    AMap?: AMapNamespace
    _AMapSecurityConfig?: { securityJsCode: string }
    [key: `__amapReady_${string}`]: (() => void) | undefined
  }
}

const scriptId = 'amap-js-api-v2'
let loadPromise: Promise<AMapNamespace> | null = null

export function getAmapJsApiConfig() {
  return {
    key: (import.meta.env.VITE_AMAP_JS_API_KEY ?? '').trim(),
    securityJsCode: (import.meta.env.VITE_AMAP_SECURITY_JS_CODE ?? '').trim(),
  }
}

export function loadAmapJsApi(): Promise<AMapNamespace> {
  if (window.AMap) return Promise.resolve(window.AMap)
  if (loadPromise) return loadPromise

  const { key, securityJsCode } = getAmapJsApiConfig()
  if (!key || !securityJsCode) {
    return Promise.reject(new Error('缺少高德 Web端（JS API）Key 或安全密钥'))
  }

  window._AMapSecurityConfig = { securityJsCode }
  loadPromise = new Promise<AMapNamespace>((resolve, reject) => {
    const callbackName = `__amapReady_${crypto.randomUUID().replaceAll('-', '')}` as const
    const cleanup = () => {
      window[callbackName] = undefined
    }
    window[callbackName] = () => {
      cleanup()
      if (window.AMap) {
        resolve(window.AMap)
      } else {
        loadPromise = null
        reject(new Error('高德地图脚本已加载，但地图对象不可用'))
      }
    }

    const existing = document.getElementById(scriptId)
    if (existing) existing.remove()
    const script = document.createElement('script')
    script.id = scriptId
    script.async = true
    script.onerror = () => {
      cleanup()
      loadPromise = null
      script.remove()
      reject(new Error('高德地图脚本加载失败，请检查 JS API Key、网络和安全域名'))
    }
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}&plugin=AMap.Scale,AMap.ToolBar&callback=${callbackName}`
    document.head.append(script)
  })
  return loadPromise
}
