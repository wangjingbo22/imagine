import type { ProviderRoute, TravelMode } from '../domain/trip'

interface SegmentRouteModePickerProps {
  route: ProviderRoute
  pending: boolean
  error: string
  notice?: string
  disabled?: boolean
  onSelect: (mode: TravelMode) => void
  onRetry: () => void
}

const modeChoices: Array<{ mode: TravelMode; label: string }> = [
  { mode: 'DRIVING', label: '打车路线' },
  { mode: 'TRANSIT', label: '公共交通' },
  { mode: 'WALKING', label: '步行' },
  { mode: 'BICYCLING', label: '骑行' },
]

export function SegmentRouteModePicker({
  route,
  pending,
  error,
  notice = '',
  disabled = false,
  onSelect,
  onRetry,
}: SegmentRouteModePickerProps) {
  const status = pending
    ? '正在更新这段路线。'
    : error
      ? `路线更新失败：${error}`
      : notice
        ? notice
      : disabled
        ? '当前 Plan V1 正在执行，路线方式已锁定。'
        : '选择路线方式后，将重新校验整份候选计划。'

  return (
    <div className="segment-route-mode-picker">
      <div aria-label="路线方式" className="segment-route-mode-picker__choices">
        {modeChoices.map(({ mode, label }) => (
          <button
            aria-pressed={route.mode === mode}
            disabled={disabled || pending}
            key={mode}
            onClick={() => {
              if (route.mode !== mode) onSelect(mode)
            }}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
      <p aria-atomic="true" aria-live="polite" className={error ? 'segment-route-mode-picker__status is-error' : 'segment-route-mode-picker__status'}>
        {status}
      </p>
      {error && (
        <button className="segment-route-mode-picker__retry" disabled={disabled || pending} onClick={onRetry} type="button">
          重试这段路线
        </button>
      )}
    </div>
  )
}
