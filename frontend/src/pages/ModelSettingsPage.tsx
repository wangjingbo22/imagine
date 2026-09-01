import { Check, ChevronDown, Eye, EyeOff, KeyRound, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { deleteModelSettings, getModelSettings, saveModelSettings } from '../api/accountApi'
import { AppShell } from '../components/AppShell'
import { USER_MODEL_OPTIONS } from '../services/userLlmSettings'

export function ModelSettingsPage() {
  const navigate = useNavigate()
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('qwen-plus')
  const [baseUrl, setBaseUrl] = useState('https://dashscope.aliyuncs.com/compatible-mode/v1')
  const [showKey, setShowKey] = useState(false)
  const [notice, setNotice] = useState('')
  const selected = USER_MODEL_OPTIONS.find((item) => item.id === model) ?? USER_MODEL_OPTIONS[1]

  useEffect(() => { void getModelSettings().then(({ data }) => { if (data.model) setModel(data.model); if (data.baseUrl) setBaseUrl(data.baseUrl); if (data.keyHint) setNotice(`已绑定账户 API Key（${data.keyHint}）`) }).catch(() => navigate('/account?returnTo=%2Fmodel-settings', { replace: true })) }, [navigate])
  async function save() {
    if (!apiKey.trim()) { setNotice('请先填写 API Key。'); return }
    try { await saveModelSettings({ apiKey, model, baseUrl }); setApiKey(''); setNotice(`已绑定账户并启用 ${selected.name}。`) } catch { setNotice('保存失败；请确认已登录、地址为 HTTPS 且服务端已配置加密密钥。') }
  }
  async function clear() {
    try { await deleteModelSettings(); setApiKey(''); setNotice('已从账户移除 API Key。') } catch { setNotice('清除失败；请先登录。') }
  }
  return <AppShell compact><main className="model-settings">
    <section className="model-settings__intro"><p className="section-kicker">MODEL CONTROLS</p><h1>选择这次对话的模型</h1><p>绑定自己的 API Key 后才能使用 AI 解析行程；未配置时系统只提供非 AI 的确定性表单解析。</p></section>
    <section className="model-settings__panel">
      <div className="model-settings__title"><span><Sparkles size={19} /></span><div><h2>模型</h2><p>为自然语言行程解析选择一个模型。</p></div></div>
      <label className="model-picker"><span>当前模型</span><div><select value={model} onChange={(event) => setModel(event.target.value)} aria-label="选择模型">{USER_MODEL_OPTIONS.map((item) => <option key={item.id} value={item.id}>{item.name} — {item.description}</option>)}</select><ChevronDown size={18} /></div></label>
      <div className="model-choice"><strong>{selected.name}</strong><span>{selected.description}</span><Check size={17} /></div>
      <label className="key-input"><span>兼容 OpenAI 的 API 地址</span><div><input type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://…/v1" autoComplete="url" required /></div></label>
      <div className="model-settings__title model-settings__title--key"><span><KeyRound size={19} /></span><div><h2>API Key</h2><p>用于调用兼容 OpenAI 接口的百炼模型。</p></div></div>
      <label className="key-input"><span>API Key</span><div><input type={showKey ? 'text' : 'password'} value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-…" autoComplete="off" /><button type="button" onClick={() => setShowKey(!showKey)} aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}>{showKey ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></label>
      <p className="key-security"><ShieldCheck size={16} /> 不会写入账户资料或日志；仅以加密形式保存到当前账户。</p>
      <div className="model-settings__actions"><button className="button button--primary" type="button" onClick={save}><Check size={17} /> 保存并使用</button><button className="button button--soft" type="button" onClick={clear}><Trash2 size={17} /> 清除 Key</button></div>
      {notice && <p className="model-settings__notice" role="status">{notice}</p>}
    </section>
  </main></AppShell>
}
