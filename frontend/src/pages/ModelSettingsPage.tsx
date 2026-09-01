import { Check, Eye, EyeOff, KeyRound, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { deleteModelSettings, getModelSettings, saveModelSettings } from '../api/accountApi'
import { ApiError } from '../api/client'
import { AppShell } from '../components/AppShell'

export function ModelSettingsPage() {
  const navigate = useNavigate()
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('qwen-plus')
  const [baseUrl, setBaseUrl] = useState('https://dashscope.aliyuncs.com/compatible-mode/v1')
  const [showKey, setShowKey] = useState(false)
  const [notice, setNotice] = useState('')

  function saveErrorMessage(error: unknown): string {
    if (error instanceof ApiError) return error.message
    return '保存失败，请检查网络连接后重试。'
  }

  useEffect(() => {
    void getModelSettings()
      .then(({ data }) => {
        if (data.model) setModel(data.model)
        if (data.baseUrl) setBaseUrl(data.baseUrl)
        if (data.configured) setNotice('已绑定账户模型设置。')
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.code === 'ACCOUNT_SESSION_REQUIRED') {
          navigate('/account?returnTo=%2Fmodel-settings', { replace: true })
          return
        }
        setNotice('暂时无法读取模型设置，请重试。')
      })
  }, [navigate])
  async function save() {
    if (!apiKey.trim()) { setNotice('请先填写 API Key。'); return }
    if (!model.trim()) { setNotice('请填写模型名称。'); return }
    if (!baseUrl.trim()) { setNotice('请填写模型 API 地址。'); return }
    try { await saveModelSettings({ apiKey, model: model.trim(), baseUrl: baseUrl.trim() }); setApiKey(''); navigate('/', { replace: true }) } catch (error) { setNotice(`保存失败：${saveErrorMessage(error)}`) }
  }
  async function clear() {
    try { await deleteModelSettings(); setApiKey(''); setNotice('已从账户移除 API Key。') } catch { setNotice('清除失败；请先登录。') }
  }
  return <AppShell compact><main className="model-settings">
    <section className="model-settings__intro"><p className="section-kicker">MODEL CONTROLS</p><h1>配置这次对话的模型</h1><p>绑定自己的 API Key 后才能使用 AI 解析行程；未配置时不能生成行程。</p></section>
    <section className="model-settings__panel">
      <div className="model-settings__title"><span><Sparkles size={19} /></span><div><h2>模型连接</h2><p>填写你的模型名称和兼容 OpenAI 的 API 地址。</p></div></div>
      <label className="key-input"><span>模型名称</span><div><input type="text" value={model} onChange={(event) => setModel(event.target.value)} placeholder="例如：qwen-plus 或 gpt-4.1-mini" autoComplete="off" required /></div></label>
      <label className="key-input"><span>兼容 OpenAI 的 API 地址</span><div><input type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://example.com/v1" autoComplete="url" required /></div></label>
      <div className="model-settings__title model-settings__title--key"><span><KeyRound size={19} /></span><div><h2>API Key</h2><p>用于调用你填写的模型 API。</p></div></div>
      <label className="key-input"><span>API Key</span><div><input type={showKey ? 'text' : 'password'} value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-…" autoComplete="off" /><button type="button" onClick={() => setShowKey(!showKey)} aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}>{showKey ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></label>
      <p className="key-security"><ShieldCheck size={16} /> 不会写入账户资料或日志；仅以加密形式保存到当前账户。</p>
      <div className="model-settings__actions"><button className="button button--primary" type="button" onClick={save}><Check size={17} /> 保存并使用</button><button className="button button--soft" type="button" onClick={clear}><Trash2 size={17} /> 清除 Key</button></div>
      {notice && <p className="model-settings__notice" role="status">{notice}</p>}
    </section>
  </main></AppShell>
}
