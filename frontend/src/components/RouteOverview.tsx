import { Map, Maximize2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { GeoPoint, ProviderRoute, TravelMode } from '../domain/trip'
import {
  loadAmapJsApi,
  type AMapMapInstance,
  type AMapNamespace,
  type AMapOverlay,
  type AMapPosition,
} from '../lib/amapJsApi'
import type { LocationEvidence } from '../services/amapPlan'

interface RouteOverviewProps {
  cityName: string
  evidence: LocationEvidence | null
  startLocationText?: string | null
}

const modeLabels: Record<TravelMode, string> = {
  WALKING: '步行',
  TRANSIT: '公共交通',
  DRIVING: '自驾',
  BICYCLING: '骑行',
  TAXI: '打车',
}

const routeColors: Record<TravelMode, string> = {
  WALKING: '#2563eb',
  TRANSIT: '#7c3aed',
  DRIVING: '#0891b2',
  BICYCLING: '#059669',
  TAXI: '#dc6b2f',
}

function position(point: GeoPoint): AMapPosition {
  return [point.longitude, point.latitude]
}

function routeSegments(route: ProviderRoute) {
  const detailed = route.steps
    .map((step) => step.polyline ?? [])
    .filter((points) => points.length >= 2)
  return detailed.length > 0 ? detailed : [[route.origin, route.destination]]
}

function markerContent(label: string, name: string, origin = false) {
  const marker = document.createElement('button')
  marker.className = `amap-route-marker${origin ? ' amap-route-marker--origin' : ''}`
  marker.type = 'button'
  marker.title = name
  marker.setAttribute('aria-label', `${label}：${name}`)
  const text = document.createElement('span')
  text.textContent = label
  marker.append(text)
  return marker
}

function infoContent(label: string, name: string, address?: string | null) {
  const card = document.createElement('div')
  card.className = 'amap-route-info'
  const title = document.createElement('strong')
  title.textContent = `${label} · ${name}`
  card.append(title)
  if (address) {
    const detail = document.createElement('span')
    detail.textContent = address
    card.append(detail)
  }
  return card
}

function addStop(
  amap: AMapNamespace,
  map: AMapMapInstance,
  point: GeoPoint,
  label: string,
  name: string,
  address: string | null,
  origin = false,
) {
  const coordinates = position(point)
  const marker = new amap.Marker({
    position: coordinates,
    anchor: 'bottom-center',
    content: markerContent(label, name, origin),
    title: name,
    zIndex: origin ? 130 : 120,
  })
  const info = new amap.InfoWindow({
    content: infoContent(label, name, address),
    offset: new amap.Pixel(0, -38),
    anchor: 'bottom-center',
  })
  marker.on('click', () => info.open(map, coordinates))
  return marker
}

function populateMap(
  amap: AMapNamespace,
  map: AMapMapInstance,
  evidence: LocationEvidence,
  startLocationText: string,
) {
  const overlays: AMapOverlay[] = []
  for (const route of evidence.routes) {
    for (const points of routeSegments(route)) {
      overlays.push(new amap.Polyline({
        path: points.map(position),
        strokeColor: routeColors[route.mode],
        strokeWeight: route.mode === 'WALKING' ? 6 : 7,
        strokeOpacity: 0.92,
        strokeStyle: route.mode === 'WALKING' ? 'dashed' : 'solid',
        lineJoin: 'round',
        lineCap: 'round',
        showDir: route.mode !== 'WALKING',
        zIndex: 80,
      }))
    }
  }

  const origin = evidence.routes[0]?.origin ?? evidence.city.cityContext.center
  overlays.push(addStop(amap, map, origin, '起', startLocationText, null, true))
  evidence.places.forEach((place, index) => {
    overlays.push(addStop(
      amap,
      map,
      place.location,
      String(index + 1),
      place.name,
      place.address,
    ))
  })
  map.add(overlays)
  map.setFitView(overlays, false, [58, 48, 76, 48], 16)
}

function AmapRouteCanvas({
  cityName,
  evidence,
  startLocationText,
  expanded = false,
}: RouteOverviewProps & { expanded?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || !evidence || evidence.routes.length === 0) return
    let disposed = false
    let map: AMapMapInstance | null = null
    void loadAmapJsApi()
      .then((amap) => {
        if (disposed) return
        map = new amap.Map(container, {
          viewMode: '2D',
          zoom: 12,
          center: position(evidence.city.cityContext.center),
          mapStyle: 'amap://styles/normal',
          resizeEnable: true,
          showLabel: true,
        })
        map.addControl(new amap.Scale())
        map.addControl(new amap.ToolBar({ position: 'RB', offset: new amap.Pixel(10, 42) }))
        populateMap(amap, map, evidence, startLocationText || '行程起点')
        window.setTimeout(() => map?.resize(), 0)
      })
      // A transient provider/network failure should not obscure route facts.
      // A later route refresh or remount retries loading the JS API.
      .catch(() => undefined)

    return () => {
      disposed = true
      map?.destroy()
    }
  }, [evidence, expanded, startLocationText])

  if (!evidence || evidence.routes.length === 0) {
    return (
      <div className={`real-route-map real-route-map--empty${expanded ? ' real-route-map--expanded' : ''}`}>
        <Map size={30} />
        <strong>真实路线尚未加载</strong>
        <span>请从新建行程进入并等待高德地点、路线请求完成。</span>
      </div>
    )
  }

  return (
    <div className={`real-route-map${expanded ? ' real-route-map--expanded' : ''}`}>
      <div aria-label={`${cityName}高德路线地图`} className="real-route-map__container" ref={containerRef} />
      <div className="real-route-map__city">{cityName} · 高德地图</div>
      <div className="real-route-map__legend" aria-label="分段路线">
        {evidence.routes.map((route, index) => (
          <span
            className={`real-route-map__legend-item real-route-map__legend-item--${route.mode.toLowerCase()}`}
            key={route.routeId}
          >
            {index + 1}. {modeLabels[route.mode]} {(route.distanceMeters / 1000).toFixed(1)} km
          </span>
        ))}
      </div>
    </div>
  )
}

export function RouteOverview({ cityName, evidence, startLocationText }: RouteOverviewProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <section className="map-card">
        <div className="map-card__toolbar">
          <span><Map size={16} /> 路线总览</span>
          <button disabled={!evidence} onClick={() => setExpanded(true)} type="button">
            <Maximize2 size={13} /> 查看大图
          </button>
        </div>
        <AmapRouteCanvas cityName={cityName} evidence={evidence} startLocationText={startLocationText} />
      </section>
      {expanded && createPortal((
        <div className="route-map-dialog" role="dialog" aria-label={`${cityName}路线大图`} aria-modal="true">
          <div className="route-map-dialog__panel">
            <div className="route-map-dialog__toolbar">
              <div>
                <span>高德路线大图</span>
                <strong>{cityName} · {evidence?.routes.length ?? 0} 段路线</strong>
              </div>
              <button aria-label="关闭路线大图" onClick={() => setExpanded(false)} type="button">
                <X size={20} />
              </button>
            </div>
            <AmapRouteCanvas cityName={cityName} evidence={evidence} startLocationText={startLocationText} expanded />
          </div>
        </div>
      ), document.body)}
    </>
  )
}
