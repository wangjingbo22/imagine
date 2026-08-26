import { Camera, ImagePlus, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { request } from '../api/client'

type Media = { mediaId: string; taskId: string; dataUrl: string; mimeType: string; byteSize: number; createdAt: string }

async function reencode(file: File): Promise<{ dataUrl: string; mimeType: string; byteSize: number }> {
  const source = await createImageBitmap(file)
  const scale = Math.min(1, 1600 / Math.max(source.width, source.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(source.width * scale)); canvas.height = Math.max(1, Math.round(source.height * scale))
  canvas.getContext('2d')?.drawImage(source, 0, 0, canvas.width, canvas.height); source.close()
  for (const quality of [.84, .72, .6, .48]) {
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
    if (blob && blob.size <= 1_500_000) return { dataUrl: await new Promise((resolve) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsDataURL(blob) }), mimeType: 'image/jpeg', byteSize: blob.size }
  }
  throw new Error('图片压缩后仍超过 1.5MB，请选择更小的照片。')
}

export function TaskPhotoCard({ tripId, taskId }: { tripId: string; taskId: string }) {
  const input = useRef<HTMLInputElement>(null); const [media, setMedia] = useState<Media | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  useEffect(() => { void request<Media | null>(`/api/v2/trips/${tripId}/tasks/${taskId}/media`).then((item) => setMedia(item.data)).catch(() => undefined) }, [taskId, tripId])
  async function select(file?: File) { if (!file) return; setBusy(true); setError(''); try { const photo = await reencode(file); const result = await request<Media>(`/api/v2/trips/${tripId}/tasks/${taskId}/media`, { method: 'POST', body: JSON.stringify(photo) }); setMedia(result.data) } catch (caught) { setError(caught instanceof Error ? caught.message : '照片处理失败，不影响完成任务。') } finally { setBusy(false) } }
  async function remove() { setBusy(true); try { await request(`/api/v2/trips/${tripId}/tasks/${taskId}/media`, { method: 'DELETE' }); setMedia(null) } catch (caught) { setError(caught instanceof Error ? caught.message : '删除失败。') } finally { setBusy(false) } }
  return <section className="task-photo-card"><div><Camera size={18} /><span><strong>这一站留张照片</strong><small>将压缩至 1.5MB 以下并移除 EXIF；每站仅保留一张。</small></span></div>{media ? <figure><img src={media.dataUrl} alt="当前任务照片" /><figcaption>{Math.ceil(media.byteSize / 1024)} KB <button type="button" disabled={busy} onClick={() => void remove()}><Trash2 size={14} />删除</button></figcaption></figure> : <button className="button button--soft" type="button" disabled={busy} onClick={() => input.current?.click()}><ImagePlus size={16} />{busy ? '正在处理…' : '选择照片'}</button>}<input ref={input} hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => void select(event.target.files?.[0])} />{error && <p className="media-error">{error}</p>}</section>
}
