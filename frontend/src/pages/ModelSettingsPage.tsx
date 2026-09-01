import { Check, Eye, EyeOff, KeyRound, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
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
  const [saving, setSaving] = useState(false)

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
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!apiKey.trim()) { setNotice('请先填写 API Key。'); return }
    if (!model.trim()) { setNotice('请填写模型名称。'); return }
    if (!baseUrl.trim()) { setNotice('请填写模型 API 地址。'); return }
    setSaving(true)
    try { await saveModelSettings({ apiKey, model: model.trim(), baseUrl: baseUrl.trim() }); setApiKey(''); navigate('/', { replace: true }) } catch (error) { setNotice(`保存失败：${saveErrorMessage(error)}`) } finally { setSaving(false) }
  }
  async function clear() {
    try { await deleteModelSettings(); setApiKey(''); setNotice('已从账户移除 API Key。') } catch { setNotice('清除失败；请先登录。') }
  }
  return <AppShell compact><main className="model-settings">
    <section className="model-settings__intro"><p className="section-kicker">ACCOUNT MODEL</p><h1>账户模型设置</h1><p>百炼可作为默认预设；你也可以绑定自己的兼容 OpenAI 模型服务。未绑定时不会发起模型调用。</p></section>
    <form className="model-settings__panel" onSubmit={(event) => void save(event)}>
      <div className="model-settings__title"><span><Sparkles size={19} /></span><div><h2>模型连接</h2><p>填写你的模型名称和兼容 OpenAI 的 API 地址。</p></div></div>
      <label className="key-input"><span>模型名称</span><div><input type="text" value={model} onChange={(event) => setModel(event.target.value)} placeholder="例如：qwen-plus 或 gpt-4.1-mini" autoComplete="off" required /></div></label>
      <label className="key-input"><span>兼容 OpenAI 的 API 地址</span><div><input type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://example.com/v1" autoComplete="url" required /></div></label>
      <div className="model-settings__title model-settings__title--key"><span><KeyRound size={19} /></span><div><h2>API Key</h2><p>用于调用你填写的模型 API。</p></div></div>
      <label className="key-input"><span>API Key</span><div><input type={showKey ? 'text' : 'password'} value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-…" autoComplete="off" /><button type="button" onClick={() => setShowKey(!showKey)} aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}>{showKey ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></label>
      <p className="key-security"><ShieldCheck size={16} /> API Key 仅加密保存；绑定第三方服务后，该服务会收到 API Key 及完成模型调用所需的行程文本。</p>
      <div className="model-settings__actions"><button className="button button--primary" type="submit" disabled={saving}><Check size={17} /> {saving ? '正在验证并保存' : '保存并使用'}</button><button className="button button--soft" type="button" onClick={clear} disabled={saving}><Trash2 size={17} /> 清除 Key</button></div>
      {notice && <p className="model-settings__notice" role={notice.startsWith('保存失败') ? 'alert' : 'status'}>{notice}</p>}
    </form>
  </main></AppShell>
}
