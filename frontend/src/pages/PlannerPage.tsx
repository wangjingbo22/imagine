import {
  ArrowRight,
  Baby,
  CalendarDays,
  Check,
  ChevronLeft,
  Clock3,
  HeartPulse,
  MapPin,
  PersonStanding,
  Plus,
  Sparkles,
  UserRound,
  Wallet,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { tripApi } from '../api/tripApi'
import { buildAssistanceProfile } from '../api/tripContract'
import { AppShell } from '../components/AppShell'
import {
  buildNaturalLanguageParseInput,
  splitPlaceInput,
  toRecognizedFormPatch,
} from '../services/tripDraftRecognition'
import type {
  AssistanceMode,
  ConstraintProfileStatus,
  TripDraftConfirmationItem,
  TripDraftInput,
  TripDraftParseInput,
  TripDraftParseResult,
} from '../domain/trip'

const assistanceOptions: Array<{
  value: AssistanceMode
  label: string
  description: string
  icon: typeof UserRound
}> = [
  { value: 'standard', label: '普通出行', description: '按常规节奏规划', icon: UserRound },
  { value: 'family', label: '亲子同行', description: '关注午休与用餐', icon: Baby },
  { value: 'low-mobility', label: '低体力', description: '减少步行和换乘', icon: HeartPulse },
  { value: 'assisted', label: '行动辅助', description: '规避已知阶梯路线', icon: PersonStanding },
]

const interestOptions = ['历史文化', '特色餐饮', '城市漫步', '摄影', '自然风景', '博物馆']

export function PlannerPage() {
  const navigate = useNavigate()
  const [tripId] = useState(() => crypto.randomUUID())
  const [assistanceMode, setAssistanceMode] = useState<AssistanceMode>('low-mobility')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisMessage, setAnalysisMessage] = useState('')
  const [lastAnalyzedRequest, setLastAnalyzedRequest] = useState('')
  const [isConfirmingConstraints, setIsConfirmingConstraints] = useState(false)
  const [constraintStatus, setConstraintStatus] =
    useState<ConstraintProfileStatus>('DRAFT')
  const confirmedProfileJson = useRef<string | null>(null)
  const [submitError, setSubmitError] = useState('')
  const [confirmationItems, setConfirmationItems] = useState<TripDraftConfirmationItem[]>([])
  const [cityName, setCityName] = useState('北京')
  const [travelDate, setTravelDate] = useState('2026-08-26')
  const [startTime, setStartTime] = useState('09:00')
  const [endTime, setEndTime] = useState('20:00')
  const [startLocationText, setStartLocationText] = useState('北京市中心')
  const [endLocationText, setEndLocationText] = useState('北京市中心')
  const [endSameAsStart, setEndSameAsStart] = useState(true)
  const [budget, setBudget] = useState('350')
  const [interests, setInterests] = useState(['历史文化', '特色餐饮', '城市漫步'])
  const [mustVisitInput, setMustVisitInput] = useState('')
  const [avoidInput, setAvoidInput] = useState('排队过久的网红店')
  const [maxSegmentWalkMeters, setMaxSegmentWalkMeters] = useState('500')
  const [maxTransfers, setMaxTransfers] = useState('2')
  const [restIntervalMinutes, setRestIntervalMinutes] = useState('90')
  const [isEditingConstraints, setIsEditingConstraints] = useState(false)
  const [request, setRequest] = useState(
    '我一个人在北京玩一天，喜欢历史和特色餐饮，希望少走路，晚上 8 点前结束。',
  )

  const selectedMode = useMemo(
    () => assistanceOptions.find((item) => item.value === assistanceMode),
    [assistanceMode],
  )
  const draft = useMemo<TripDraftInput>(() => ({
    schemaVersion: '1.0',
    cityName: cityName.trim(),
    travelDate,
    startTime,
    endTime,
    startLocationText: startLocationText.trim(),
    endLocationText: (endSameAsStart ? startLocationText : endLocationText).trim(),
    budgetCents: Math.round(Number(budget) * 100),
    interests,
    mustVisit: splitPlaceInput(mustVisitInput),
    avoidPlaces: splitPlaceInput(avoidInput),
    assistanceMode,
    assistanceProfile: {
      maxSegmentWalkMeters: Number(maxSegmentWalkMeters),
      maxTransfers: Number(maxTransfers),
      restIntervalMinutes: Number(restIntervalMinutes),
    },
    naturalLanguageRequest: request,
  }), [
    assistanceMode,
    avoidInput,
    budget,
    cityName,
    endTime,
    endLocationText,
    endSameAsStart,
    interests,
    maxSegmentWalkMeters,
    maxTransfers,
    mustVisitInput,
    request,
    restIntervalMinutes,
    startTime,
    startLocationText,
    travelDate,
  ])
  const assistanceProfile = useMemo(
    () => buildAssistanceProfile(draft),
    [draft],
  )

  useEffect(() => {
    const confirmed = confirmedProfileJson.current
    const current = JSON.stringify(assistanceProfile)
    if (!confirmed || confirmed === current) {
      return
    }
    setConstraintStatus('DRAFT')
    void tripApi.saveConstraintDraft(tripId, assistanceProfile).catch((error: unknown) => {
      setSubmitError(error instanceof Error ? error.message : '关怀约束回退 DRAFT 失败')
    })
  }, [assistanceProfile, tripId])

  const canParse = request.trim().length > 0

  function toggleInterest(interest: string) {
    setInterests((current) =>
      current.includes(interest)
        ? current.filter((item) => item !== interest)
        : [...current, interest],
    )
  }

  function handleCityNameChange(nextCityName: string) {
    const previousCityName = cityName.trim()
    const previousDefaultLocation = `${previousCityName}市中心`
    const nextDefaultLocation = `${nextCityName.trim()}市中心`
    setCityName(nextCityName)
    setStartLocationText((current) => current === previousDefaultLocation ? nextDefaultLocation : current)
    setEndLocationText((current) => current === previousDefaultLocation ? nextDefaultLocation : current)
    setRequest((current) => {
      const previousDefault = `我一个人在${previousCityName}玩一天，喜欢历史和特色餐饮，希望少走路，晚上 8 点前结束。`
      return current === previousDefault
        ? `我一个人在${nextCityName.trim()}玩一天，喜欢历史和特色餐饮，希望少走路，晚上 8 点前结束。`
        : current
    })
  }

  function handleStartLocationChange(value: string) {
    setStartLocationText(value)
    if (endSameAsStart) setEndLocationText(value)
  }

  function handleRequestChange(value: string) {
    setRequest(value)
    setLastAnalyzedRequest('')
    setAnalysisMessage('')
    setConfirmationItems([])
  }

  function applyRecognizedFields(parsed: TripDraftParseResult['parsed']) {
    const patch = toRecognizedFormPatch(parsed)
    if (patch.cityName) setCityName(patch.cityName)
    if (patch.travelDate) setTravelDate(patch.travelDate)
    if (patch.startTime) setStartTime(patch.startTime)
    if (patch.endTime) setEndTime(patch.endTime)
    if (patch.startLocationText) setStartLocationText(patch.startLocationText)
    if (patch.endLocationText) setEndLocationText(patch.endLocationText)
    setEndSameAsStart(patch.endSameAsStart)
    if (patch.budgetYuan !== null) setBudget(patch.budgetYuan)
    setInterests(patch.interests)
    setMustVisitInput(patch.mustVisitText)
    setAvoidInput(patch.avoidPlacesText)
  }

  function naturalLanguageParseInput(): TripDraftParseInput {
    return buildNaturalLanguageParseInput({
      tripId,
      naturalLanguageRequest: request,
      assistanceMode,
      assistanceProfile: {
        maxSegmentWalkMeters: Number(maxSegmentWalkMeters),
        maxTransfers: Number(maxTransfers),
        restIntervalMinutes: Number(restIntervalMinutes),
      },
    })
  }

  async function handleAnalyzeRequest() {
    if (!canParse) {
      setSubmitError('请先输入自然语言行程需求。')
      return
    }
    setSubmitError('')
    setAnalysisMessage('')
    setIsAnalyzing(true)
    try {
      const response = await tripApi.createDraft(naturalLanguageParseInput())
      applyRecognizedFields(response.data.parsed)
      setConfirmationItems(response.data.confirmationItems)
      setLastAnalyzedRequest(request.trim())
      setAnalysisMessage(
        response.data.confirmationItems.length > 0
          ? `已识别并回填，仍有 ${response.data.confirmationItems.length} 项需要确认。`
          : '识别完成，城市、日期、时间、预算和地点限制已填入表单。',
      )
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : '自然语言识别失败，请稍后重试。')
    } finally {
      setIsAnalyzing(false)
    }
  }

  async function handleSubmit() {
    if (!canParse) {
      setSubmitError('请先输入自然语言行程需求。')
      return
    }

    if (constraintStatus !== 'CONSTRAINT_CONFIRMED') {
      setSubmitError('请先确认关怀约束，DRAFT 状态不能进入规划。')
      return
    }
    setSubmitError('')
    setIsSubmitting(true)
    try {
      const budgetNumber = Number(budget)
      let parseInput: TripDraftParseInput = {
        schemaVersion: '1.0',
        tripId,
        cityName: cityName.trim() || null,
        travelDate: travelDate || null,
        startTime: startTime || null,
        endTime: endTime || null,
        startLocationText: startLocationText.trim() || null,
        endLocationText: (endSameAsStart ? startLocationText : endLocationText).trim() || null,
        budgetCents: Number.isFinite(budgetNumber) && budgetNumber > 0
          ? Math.round(budgetNumber * 100)
          : null,
        interests,
        mustVisit: splitPlaceInput(mustVisitInput),
        avoidPlaces: splitPlaceInput(avoidInput),
        assistanceMode,
        assistanceProfile: {
          maxSegmentWalkMeters: Number(maxSegmentWalkMeters),
          maxTransfers: Number(maxTransfers),
          restIntervalMinutes: Number(restIntervalMinutes),
        },
        naturalLanguageRequest: request,
      }
      let response
      if (lastAnalyzedRequest !== request.trim()) {
        parseInput = naturalLanguageParseInput()
        response = await tripApi.createDraft(parseInput)
        applyRecognizedFields(response.data.parsed)
        setLastAnalyzedRequest(request.trim())
        setAnalysisMessage(
          response.data.confirmationItems.length > 0
            ? `已识别并回填，仍有 ${response.data.confirmationItems.length} 项需要确认。`
            : '识别完成，已使用识别结果继续生成。',
        )
      } else {
        response = await tripApi.createDraft(parseInput)
      }
      if (!response.data.canPlan || !response.data.trip) {
        setConfirmationItems(response.data.confirmationItems)
        setSubmitError('请根据确认清单补全或修正字段；确认完成前不会进入规划。')
        setIsSubmitting(false)
        return
      }
      const parsed = response.data.parsed
      if (
        !parsed.cityName || !parsed.travelDate || !parsed.startTime ||
        !parsed.endTime || !parsed.startLocationText ||
        !parsed.endLocationText || parsed.budgetCents === null
      ) {
        throw new Error('解析结果缺少生成统一 Trip 所需字段。')
      }
      const draft: TripDraftInput = {
        ...parseInput,
        cityName: parsed.cityName,
        travelDate: parsed.travelDate,
        startTime: parsed.startTime,
        endTime: parsed.endTime,
        startLocationText: parsed.startLocationText,
        endLocationText: parsed.endLocationText,
        budgetCents: parsed.budgetCents,
        interests: parsed.interests,
        mustVisit: parsed.mustVisit,
        avoidPlaces: parsed.avoidPlaces,
      }
      parseInput = {
        ...parseInput,
        cityName: parsed.cityName,
        travelDate: parsed.travelDate,
        startTime: parsed.startTime,
        endTime: parsed.endTime,
        startLocationText: parsed.startLocationText,
        endLocationText: parsed.endLocationText,
        budgetCents: parsed.budgetCents,
        interests: parsed.interests,
        mustVisit: parsed.mustVisit,
        avoidPlaces: parsed.avoidPlaces,
      }
      await tripApi.saveConstraintDraft(response.data.tripId, assistanceProfile)
      await tripApi.confirmConstraints(response.data.tripId)
      const confirmed = await tripApi.confirmDraft(parseInput)
      setConfirmationItems([])
      navigate('/generating', {
        state: { tripId: response.data.tripId, draft, trip: confirmed.data },
      })
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : '创建行程失败，请稍后重试。')
      setIsSubmitting(false)
    }
  }

  async function handleConfirmConstraints() {
    setIsConfirmingConstraints(true)
    setSubmitError('')
    try {
      await tripApi.saveConstraintDraft(tripId, assistanceProfile)
      const confirmed = await tripApi.confirmConstraints(tripId)
      confirmedProfileJson.current = JSON.stringify(confirmed.data.assistanceProfile)
      setConstraintStatus(confirmed.data.status)
    } catch (error) {
      setConstraintStatus('DRAFT')
      setSubmitError(error instanceof Error ? error.message : '确认关怀约束失败')
    } finally {
      setIsConfirmingConstraints(false)
    }
  }

  return (
    <AppShell compact>
      <main className="planner-layout">
        <aside className="planner-sidebar" data-reveal="side">
          <div>
            <span className="eyebrow eyebrow--dark"><Sparkles size={14} /> 新建行程</span>
            <h1>先说说，你想要怎样的一天？</h1>
            <p>不用担心遗漏，Agent 会把自然语言整理成可以逐项确认的约束。</p>
          </div>
          <ol className="step-list">
            {['基本行程', '预算时间', '关怀需求', '兴趣限制', '确认生成'].map((step, index) => (
              <li className={index < 3 ? 'is-complete' : index === 3 ? 'is-current' : ''} key={step}>
                <span>{index < 3 ? <Check size={15} /> : index + 1}</span>
                <div><strong>{step}</strong><small>{index === 3 ? '正在填写' : index < 3 ? '已完成' : '下一步'}</small></div>
              </li>
            ))}
          </ol>
          <div className="privacy-note">
            <HeartPulse size={18} />
            <span>关怀需求只用于本次路线校验，不用于给你贴标签。</span>
          </div>
        </aside>

        <section className="planner-panel" data-reveal="panel">
          <div className="planner-panel__header">
            <div>
              <span className="section-kicker">EDITABLE TRIP DRAFT</span>
              <h2>把偏好和限制告诉 Agent</h2>
            </div>
            <span className="save-state"><span className="status-dot" /> 已自动保存</span>
          </div>

          <div className="form-section">
            <label className="field-label" htmlFor="trip-request">自然语言描述</label>
            <div className="smart-textarea">
              <textarea id="trip-request" maxLength={300} value={request} onChange={(event) => handleRequestChange(event.target.value)} />
              <div className="smart-textarea__footer">
                <span className="smart-textarea__hint"><Sparkles size={15} /> 百炼将识别城市、日期、时间、预算和地点限制</span>
                <div className="smart-textarea__actions">
                  <span>{request.length}/300</span>
                  <button
                    disabled={isAnalyzing || !canParse}
                    onClick={handleAnalyzeRequest}
                    type="button"
                  >
                    <Sparkles size={14} />
                    {isAnalyzing ? '正在识别…' : '智能识别并填入'}
                  </button>
                </div>
              </div>
            </div>
            {analysisMessage && (
              <p className="recognition-status" role="status">
                <Check size={14} /> {analysisMessage}
              </p>
            )}
          </div>

          <div className="form-grid">
            <div className="input-card">
              <span><MapPin size={18} /> 目标城市</span>
              <input value={cityName} onChange={(event) => handleCityNameChange(event.target.value)} />
              <small>提交后解析 cityCode 与中心坐标</small>
            </div>
            <label className="input-card">
              <span><MapPin size={18} /> 当天真实起点</span>
              <input
                aria-label="当天真实起点"
                placeholder="酒店、车站或详细地址"
                value={startLocationText}
                onChange={(event) => handleStartLocationChange(event.target.value)}
              />
              <small>会在目标城市内通过高德解析坐标</small>
            </label>
            <div className="input-card">
              <span><MapPin size={18} /> 当天结束地点</span>
              <input
                aria-label="当天结束地点"
                disabled={endSameAsStart}
                placeholder="酒店、车站或详细地址"
                value={endSameAsStart ? startLocationText : endLocationText}
                onChange={(event) => setEndLocationText(event.target.value)}
              />
              <small>
                <label className="inline-check">
                  <input
                    checked={endSameAsStart}
                    onChange={(event) => {
                      setEndSameAsStart(event.target.checked)
                      if (event.target.checked) setEndLocationText(startLocationText)
                    }}
                    type="checkbox"
                  />
                  终点与起点相同
                </label>
              </small>
            </div>
            <label className="input-card">
              <span><CalendarDays size={18} /> 出行日期</span>
              <input type="date" value={travelDate} onChange={(event) => setTravelDate(event.target.value)} />
              <small>当前版本规划单日行程</small>
            </label>
            <div className="input-card">
              <span><Clock3 size={18} /> 可用时间</span>
              <div className="time-input-row">
                <input aria-label="开始时间" type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} />
                <span>至</span>
                <input aria-label="结束时间" type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} />
              </div>
              <small>Agent 将校验任务是否位于时间窗内</small>
            </div>
            <label className="input-card">
              <span><Wallet size={18} /> 总预算</span>
              <div className="money-input"><b>¥</b><input min="1" type="number" value={budget} onChange={(event) => setBudget(event.target.value)} /></div>
              <small>建议保留 15% 缓冲</small>
            </label>
          </div>

          <div className="form-section">
            <div className="field-heading">
              <div><label className="field-label">兴趣与地点限制</label><small>点击标签可选择或取消</small></div>
              <span className="verified-chip"><Plus size={13} /> 至少选择 1 项</span>
            </div>
            <div className="interest-options">
              {interestOptions.map((interest) => (
                <button
                  className={interests.includes(interest) ? 'interest-chip is-selected' : 'interest-chip'}
                  key={interest}
                  onClick={() => toggleInterest(interest)}
                  type="button"
                >
                  {interests.includes(interest) && <Check size={13} />}
                  {interest}
                </button>
              ))}
            </div>
            <div className="restriction-grid">
              <label>
                <span>必去地点</span>
                <div><MapPin size={16} /><input value={mustVisitInput} onChange={(event) => setMustVisitInput(event.target.value)} placeholder="例如：中国国家博物馆" /></div>
              </label>
              <label>
                <span>希望避开</span>
                <div><X size={16} /><input value={avoidInput} onChange={(event) => setAvoidInput(event.target.value)} placeholder="例如：排队过久的餐厅" /></div>
              </label>
            </div>
          </div>

          <div className="form-section">
            <div className="field-heading">
              <div><label className="field-label">关怀出行模式</label><small>会转换为可验证约束</small></div>
              <span className={`verified-chip constraint-status constraint-status--${constraintStatus.toLowerCase()}`}>
                {constraintStatus === 'CONSTRAINT_CONFIRMED' ? <Check size={13} /> : <Clock3 size={13} />}
                {constraintStatus === 'CONSTRAINT_CONFIRMED' ? '已确认' : 'DRAFT 待确认'}
              </span>
            </div>
            <div className="assistance-grid">
              {assistanceOptions.map(({ value, label, description, icon: Icon }) => (
                <button
                  className={assistanceMode === value ? 'assistance-card is-selected' : 'assistance-card'}
                  key={value}
                  onClick={() => setAssistanceMode(value)}
                  type="button"
                >
                  <span><Icon size={21} /></span>
                  <strong>{label}</strong>
                  <small>{description}</small>
                  {assistanceMode === value && <i><Check size={12} /></i>}
                </button>
              ))}
            </div>
          </div>

          <div className="constraint-summary">
            <div>
              <span className="constraint-summary__icon"><HeartPulse size={20} /></span>
              <div>
                <strong>{selectedMode?.label}约束已准备</strong>
                <p>单段步行不超过 {maxSegmentWalkMeters} 米 · 最多 {maxTransfers} 次换乘 · 每 {restIntervalMinutes} 分钟安排休息</p>
              </div>
            </div>
            <button onClick={() => setIsEditingConstraints((current) => !current)} type="button">
              {isEditingConstraints ? '收起细节' : '编辑细节'}
            </button>
          </div>

          {isEditingConstraints && (
            <div className="constraint-editor motion-enter">
              <label>
                <span>单段步行上限</span>
                <div><input min="100" step="50" type="number" value={maxSegmentWalkMeters} onChange={(event) => setMaxSegmentWalkMeters(event.target.value)} /><b>米</b></div>
              </label>
              <label>
                <span>最多换乘次数</span>
                <div><input min="0" max="8" type="number" value={maxTransfers} onChange={(event) => setMaxTransfers(event.target.value)} /><b>次</b></div>
              </label>
              <label>
                <span>休息间隔</span>
                <div><input min="30" step="15" type="number" value={restIntervalMinutes} onChange={(event) => setRestIntervalMinutes(event.target.value)} /><b>分钟</b></div>
              </label>
            </div>
          )}

          {confirmationItems.length > 0 && (
            <section className="draft-confirmation motion-enter" aria-live="polite">
              <div className="draft-confirmation__heading">
                <span><Sparkles size={18} /></span>
                <div>
                  <strong>还有 {confirmationItems.length} 项需要你确认</strong>
                  <p>直接在上方对应输入框修改，然后点击“重新解析并确认”。</p>
                </div>
              </div>
              <ul>
                {confirmationItems.map((item) => (
                  <li key={`${item.path}-${item.code}`}>
                    <div>
                      <strong>{item.path}</strong>
                      <span>{item.message}</span>
                    </div>
                    {item.candidates.length > 0 && (
                      <small>可选：{item.candidates.join(' / ')}</small>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <div className="constraint-confirmation-bar">
            <div>
              <strong>
                {constraintStatus === 'CONSTRAINT_CONFIRMED'
                  ? '关怀约束已锁定，可进入规划'
                  : '修改任意关怀字段后必须重新确认'}
              </strong>
              <small>确认操作幂等；重复点击不会重复迁移状态。</small>
            </div>
            <button
              className="button button--soft"
              disabled={isConfirmingConstraints}
              onClick={handleConfirmConstraints}
              type="button"
            >
              {isConfirmingConstraints ? '正在确认…' : '确认关怀约束'}
            </button>
          </div>

          <div className="planner-actions">
            <button className="button button--ghost" onClick={() => navigate('/')} type="button">
              <ChevronLeft size={18} /> 返回首页
            </button>
            <div className="planner-actions__submit">
              {submitError && <span className="form-error">{submitError}</span>}
              <button
                className="button button--primary"
                disabled={
                  isSubmitting ||
                  !canParse ||
                  constraintStatus !== 'CONSTRAINT_CONFIRMED'
                }
                onClick={handleSubmit}
                type="button"
              >
                {isSubmitting
                  ? '正在理解需求…'
                  : confirmationItems.length > 0
                    ? '重新解析并确认'
                    : '解析并确认后生成'}
                {!isSubmitting && <ArrowRight size={18} />}
              </button>
            </div>
          </div>
        </section>
      </main>
    </AppShell>
  )
}
