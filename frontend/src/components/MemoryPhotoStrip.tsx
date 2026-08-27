import { Camera, ImageOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import { request } from '../api/client'

type Media = { taskId: string; dataUrl: string; byteSize: number }
type Task = { id: string; order: number; title: string }

export function MemoryPhotoStrip({ tripId, tasks }: { tripId: string | null; tasks: Task[] }) {
  const [photos, setPhotos] = useState<Media[]>([])
  useEffect(() => { if (!tripId) return; let live = true; void Promise.all(tasks.map(async (task) => (await request<Media | null>(`/api/v2/trips/${tripId}/tasks/${task.id}/media`)).data)).then((items) => { if (live) setPhotos(items.filter((item): item is Media => item !== null)) }).catch(() => { if (live) setPhotos([]) }); return () => { live = false } }, [tasks, tripId])
  const byTask = new Map(photos.map((photo) => [photo.taskId, photo]))
  return <section className="summary-media"><div className="panel-heading"><div><span className="section-kicker">MEMORY TIMELINE</span><h2>旅途回忆</h2></div><small>{photos.length} 张未删除照片</small></div>{photos.length ? <div className="summary-media__grid">{tasks.filter((task) => byTask.has(task.id)).map((task) => <article key={task.id}><img src={byTask.get(task.id)?.dataUrl} alt={`${task.title} 的旅行照片`} /><div><Camera size={14} /><span>第 {task.order} 站 · {task.title}</span></div></article>)}</div> : <div className="summary-media__empty"><ImageOff size={20} /><span><strong>这趟旅程没有保存照片</strong><small>完成率、费用与版本变化仍已完整保留在本次总结中。</small></span></div>}</section>
}
