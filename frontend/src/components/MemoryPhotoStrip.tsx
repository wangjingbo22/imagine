import { Camera, ImageOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import { request } from '../api/client'

export type MemoryPhoto = {
  taskId: string
  dataUrl: string
  byteSize: number
  mediaId?: string
  mimeType?: string
  createdAt?: string
}

type Task = { id: string; order: number; title: string }

type MemoryPhotoStripProps = {
  tripId: string | null
  tasks: Task[]
  photos?: MemoryPhoto[]
  heading?: string
}

export function MemoryPhotoStrip({
  tripId,
  tasks,
  photos: controlledPhotos,
  heading = '旅途回忆',
}: MemoryPhotoStripProps) {
  const requestKey = tripId
    ? `${tripId}:${tasks.map((task) => task.id).join(',')}`
    : ''
  const [legacyResult, setLegacyResult] = useState<{
    requestKey: string
    photos: MemoryPhoto[]
    error: string
  } | null>(null)

  useEffect(() => {
    if (controlledPhotos !== undefined) return
    if (!tripId) return

    let live = true
    void Promise.allSettled(tasks.map(async (task) => ({
      task,
      photo: (await request<MemoryPhoto | null>(
        `/api/v2/trips/${encodeURIComponent(tripId)}/tasks/${encodeURIComponent(task.id)}/media`,
      )).data,
    }))).then((results) => {
      if (!live) return
      const loaded: MemoryPhoto[] = []
      let failedCount = 0
      let invalidBindingCount = 0
      for (const result of results) {
        if (result.status === 'rejected') {
          failedCount += 1
          continue
        }
        if (!result.value.photo) continue
        if (result.value.photo.taskId !== result.value.task.id) {
          invalidBindingCount += 1
          continue
        }
        loaded.push(result.value.photo)
      }
      setLegacyResult({
        requestKey,
        photos: loaded,
        error: failedCount > 0 || invalidBindingCount > 0
          ? `有 ${failedCount + invalidBindingCount} 个任务的照片读取失败或任务绑定无效，未展示这些照片。`
          : '',
      })
    })
    return () => { live = false }
  }, [controlledPhotos, requestKey, tasks, tripId])

  const legacyPhotos = legacyResult?.requestKey === requestKey
    ? legacyResult.photos
    : []
  const error = controlledPhotos !== undefined
    ? ''
    : !tripId
      ? '缺少 tripId，无法读取任务照片。'
      : legacyResult?.requestKey === requestKey
        ? legacyResult.error
        : ''
  const photos = controlledPhotos ?? legacyPhotos
  const taskById = new Map(tasks.map((task) => [task.id, task]))
  const unknownTaskCount = photos.filter((photo) => !taskById.has(photo.taskId)).length
  const byTask = new Map(
    photos
      .filter((photo) => taskById.has(photo.taskId))
      .map((photo) => [photo.taskId, photo]),
  )

  return <section className="summary-media">
    <div className="panel-heading">
      <div><span className="section-kicker">TASK PHOTOS</span><h2>{heading}</h2></div>
      <small>{byTask.size} 张未删除照片</small>
    </div>
    {error && <p className="summary-media__error" role="alert">{error}</p>}
    {unknownTaskCount > 0 && <p className="summary-media__error" role="alert">
      {unknownTaskCount} 张照片没有对应的任务，已停止展示。
    </p>}
    {byTask.size > 0
      ? <div className="summary-media__grid">{tasks.filter((task) => byTask.has(task.id)).map((task) => <article key={task.id}><img src={byTask.get(task.id)?.dataUrl} alt={`${task.title} 的旅行照片`} /><div><Camera size={14} /><span>第 {task.order} 站 · {task.title}</span></div></article>)}</div>
      : <div className="summary-media__empty"><ImageOff size={20} /><span><strong>这趟旅程没有保存照片</strong><small>完成率、费用与版本变化仍已完整保留在本次总结中。</small></span></div>}
  </section>
}
