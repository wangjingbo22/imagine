import {
  ArrowRight,
  BrainCircuit,
  Check,
  ChevronRight,
  Compass,
  HeartHandshake,
  Route,
  ShieldCheck,
  Sparkles,
  Users,
  WalletCards,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { AppShell } from '../components/AppShell'

const capabilities = [
  { icon: WalletCards, label: '预算约束', detail: '每一笔都算得清' },
  { icon: HeartHandshake, label: '关怀出行', detail: '把照顾写进路线' },
  { icon: Route, label: '动态重规划', detail: '变化发生后依然从容' },
]

export function HomePage() {
  return (
    <AppShell>
      <main>
        <section className="hero-section">
          <div className="aurora aurora--one" />
          <div className="aurora aurora--two" />
          <div className="hero-grid" aria-hidden="true" />
          <div className="hero-content" data-reveal="hero-copy">
            <div className="eyebrow">
              <Sparkles size={15} />
              预算约束与关怀出行 AI Agent
            </div>
            <h1>
              旅途不该只是攻略，
              <br />
              <span>而是一套会照顾你的计划。</span>
            </h1>
            <p className="hero-copy">
              从预算、时间到同行人的体力与休息需求，行知旅伴把每个真实限制变成可验证的路线，
              并在旅途中随时为变化重新规划。
            </p>
            <div className="hero-actions">
              <Link className="button button--primary button--large" to="/plan">
                开始规划旅程
                <ArrowRight size={19} />
              </Link>
              <a className="button button--ghost button--large" href="#experience">
                看看它如何工作
              </a>
            </div>
            <div className="hero-proof">
              <span><Check size={15} /> 全国城市通用</span>
              <span><Check size={15} /> 关怀约束可验证</span>
              <span><Check size={15} /> 计划版本可回退</span>
            </div>
          </div>

          <div className="hero-visual" data-reveal="hero-visual" aria-label="旅行计划预览">
            <div className="orbit orbit--one" />
            <div className="orbit orbit--two" />
            <article className="floating-card floating-card--plan glass-card">
              <div className="floating-card__top">
                <span className="mini-label">真实数据生成流程</span>
                <span className="pass-chip"><ShieldCheck size={13} /> 高德 Web 服务</span>
              </div>
              <div className="route-preview">
                <span className="route-preview__line" />
                {['解析目标城市', '检索同城 POI', '规划逐段路线'].map((place, index) => (
                  <div className="route-preview__stop" key={place}>
                    <span>{index + 1}</span>
                    <div>
                      <strong>{place}</strong>
                      <small>{['cityCode', 'ONLINE', 'fetchedAt'][index]}</small>
                    </div>
                  </div>
                ))}
              </div>
              <div className="budget-row">
                <span>费用状态</span>
                <strong>未知项待确认</strong>
                <div><i style={{ width: '84%' }} /></div>
              </div>
            </article>
            <article className="floating-card floating-card--agent glass-card">
              <span className="agent-orb"><BrainCircuit size={23} /></span>
              <div>
                <small>Agent 正在检查</small>
                <strong>老人步行上限</strong>
              </div>
              <span className="loading-bars"><i /><i /><i /></span>
            </article>
            <article className="floating-card floating-card--care glass-card">
              <HeartHandshake size={20} />
              <div><strong>少走 770 米</strong><small>调整后更轻松</small></div>
            </article>
          </div>
        </section>

        <section className="capability-strip" data-reveal="fade" id="experience">
          {capabilities.map(({ icon: Icon, label, detail }) => (
            <article key={label}>
              <span><Icon size={21} /></span>
              <div><strong>{label}</strong><small>{detail}</small></div>
            </article>
          ))}
        </section>

        <section className="experience-section">
          <div className="section-heading" data-reveal="fade">
            <span>ONE INTELLIGENT JOURNEY</span>
            <h2>从一句话，到真正走得通的一天</h2>
            <p>不是生成一段文字，而是理解、验证、执行与调整组成的完整闭环。</p>
          </div>
          <div className="mode-grid">
            <Link className="mode-card mode-card--active" data-reveal="card" to="/plan">
              <div className="mode-card__visual solo-visual">
                <Compass size={42} />
                <span className="route-dash route-dash--a" />
                <span className="route-dash route-dash--b" />
              </div>
              <div className="mode-card__content">
                <span className="mode-tag">推荐体验</span>
                <h3>一个人出发</h3>
                <p>告诉 Agent 预算、时间与偏好，得到一份经过硬约束校验的专属计划。</p>
                <span className="mode-link">立即开始 <ChevronRight size={17} /></span>
              </div>
            </Link>
            <Link className="mode-card mode-card--active" data-reveal="card" to="/plan?mode=group">
              <div className="mode-card__visual group-visual">
                <Users size={42} />
                <span className="avatar-bubble avatar-bubble--a" />
                <span className="avatar-bubble avatar-bubble--b" />
                <span className="avatar-bubble avatar-bubble--c" />
              </div>
              <div className="mode-card__content">
                <span className="mode-tag mode-tag--neutral">Sprint 2</span>
                <h3>和朋友一起</h3>
                <p>协调 2—3 人的兴趣、预算与体力差异，让每一次妥协都有清晰理由。</p>
                <span className="mode-link">创建多人行程 <ChevronRight size={17} /></span>
              </div>
            </Link>
          </div>
        </section>
      </main>
      <footer className="footer">
        <span>行知旅伴 · 让计划理解真实的人</span>
        <span>2026 北京林业大学暑期实训</span>
      </footer>
    </AppShell>
  )
}
