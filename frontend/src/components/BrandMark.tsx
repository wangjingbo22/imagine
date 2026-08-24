import { MapPin } from 'lucide-react'

export function BrandMark() {
  return (
    <div className="brand-mark" aria-label="行知旅伴">
      <span className="brand-mark__icon">
        <MapPin size={17} strokeWidth={2.4} />
      </span>
      <span>行知旅伴</span>
    </div>
  )
}
