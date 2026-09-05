import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'
import {
  Activity, ArrowDown, ArrowRight, ArrowUpRight, Check, CheckCheck, ChevronDown, ChevronRight,
  CircleHelp, Clock3, Code2, ExternalLink, Eye, EyeOff, Fingerprint, KeyRound,
  LayoutDashboard, LoaderCircle, LockKeyhole, LogOut, Origami, PlugZap,
  RefreshCw, Server, ShieldCheck, Terminal, UserRound, X,
} from 'lucide-react'
import { api, ApiError } from './api'
import type { Credentials, Profile, Session } from './api'
import SignalsTab from './SignalsTab'

const docs = 'https://kite.trade/docs/connect/v3/user/'
const blankCredentials: Credentials = { api_key: '', api_secret: '', request_token: '' }
const productNames: Record<string, string> = { CNC: 'Delivery', MIS: 'Intraday', NRML: 'Normal', CO: 'Cover order', BO: 'Bracket order' }
const exchangeNames: Record<string, string> = { NSE: 'National Stock Exchange', BSE: 'BSE', NFO: 'NSE Futures & Options', BFO: 'BSE Futures & Options', MCX: 'Multi Commodity Exchange', CDS: 'NSE Currency Derivatives', BCD: 'BSE Currency Derivatives', MF: 'Mutual Funds' }

function dateLabel(value: string | null) {
  return value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—'
}

function Status({ connected }: { connected: boolean }) {
  return <span className={`status ${connected ? 'connected' : ''}`}><i />{connected ? 'Connected' : 'Not connected'}</span>
}

function Notice({ children, onClose }: { children: ReactNode; onClose?: () => void }) {
  return <div className="notice" role="alert"><CircleHelp size={18} /><span>{children}</span>{onClose && <button className="icon-button" onClick={onClose} aria-label="Dismiss message"><X size={16} /></button>}</div>
}

function Login({ onLogin, working }: { onLogin: (value: Credentials) => Promise<boolean>; working: boolean }) {
  const [form, setForm] = useState<Credentials>(blankCredentials)
  const [reveal, setReveal] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [linkError, setLinkError] = useState('')
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const credentials = Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value.trim()])) as Credentials
    setForm(blankCredentials)
    setReveal(false)
    await onLogin(credentials)
  }
  function openKite() {
    if (!form.api_key.trim()) { setLinkError('Enter your API key first to open the correct Kite login page.'); return }
    setLinkError('')
    window.open(`https://kite.zerodha.com/connect/login?v=3&api_key=${encodeURIComponent(form.api_key.trim())}`, '_blank', 'noopener,noreferrer')
  }
  return <>
    <div className="page-heading"><div><div className="eyebrow">LET’S GET CONNECTED</div><h1>Your account. Your workspace.</h1><p>Connect to Zerodha to bring your account into focus.</p></div><span className="heading-mark"><Origami size={18} /> KITE CONNECT <span>v3</span></span></div>
    <div className="login-grid">
      <section className="panel login-panel">
        <div className="panel-heading"><span className="square-icon orange"><PlugZap size={22} /></span><div><h2>Connect your account</h2><p>Enter your Kite Connect credentials to continue.</p></div></div>
        <form onSubmit={submit} autoComplete="off">
          <div className="field"><label htmlFor="api-key">API Key</label><div className="input-wrap"><KeyRound size={17} /><input id="api-key" name="api_key" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} placeholder="Enter your API key" required maxLength={256} spellCheck={false} disabled={working} /></div><p>Available in your <a href="https://developers.kite.trade/" target="_blank" rel="noreferrer">Kite developer console <ArrowUpRight size={12} /></a></p></div>
          <div className="field"><label htmlFor="api-secret">API Secret <LockKeyhole size={12} /></label><div className="input-wrap"><LockKeyhole size={17} /><input id="api-secret" name="api_secret" type={reveal ? 'text' : 'password'} value={form.api_secret} onChange={e => setForm({ ...form, api_secret: e.target.value })} placeholder="Enter your API secret" required maxLength={512} autoComplete="new-password" spellCheck={false} disabled={working} /><button className="icon-button" type="button" onClick={() => setReveal(!reveal)} aria-label={reveal ? 'Hide API secret' : 'Show API secret'} aria-pressed={reveal}>{reveal ? <EyeOff size={17} /> : <Eye size={17} />}</button></div></div>
          <div className="field"><div className="label-row"><label htmlFor="request-token">Request Token</label><button type="button" className="text-button" onClick={openKite} disabled={working}>Get request token <ArrowUpRight size={13} /></button></div><div className="input-wrap"><Fingerprint size={18} /><input id="request-token" name="request_token" type="password" value={form.request_token} onChange={e => setForm({ ...form, request_token: e.target.value })} placeholder="Paste your request token" required maxLength={512} autoComplete="new-password" spellCheck={false} disabled={working} /></div><p>The one-time token from your Kite login redirect URL.</p></div>
          {linkError && <p className="field-error" role="alert">{linkError}</p>}
          <button className="primary-button" type="submit" disabled={working}>{working ? <><LoaderCircle className="spin" size={18} /> Connecting…</> : <>Login to workspace <ArrowRight size={18} /></>}</button>
          <div className="form-footnote"><ShieldCheck size={15} /><span>Your access token stays on the backend.</span></div>
        </form>
      </section>
      <aside className="connection-guide">
        <div className="guide-eyebrow"><span className="tiny-line" /> A WORKSPACE THAT REMEMBERS</div>
        <h2>Log in once.<br /><span>Stay in your flow.</span></h2>
        <p className="guide-intro">Refresh the page. Refine your code.<br />Your saved session comes right back.</p>
        <div className="flow-step"><span className="flow-icon"><KeyRound size={19} /></span><div><h3>Connect with Kite</h3><p>Use your credentials and a fresh request token.</p></div></div>
        <div className="flow-connector"><ArrowDown size={14} /></div>
        <div className="flow-step"><span className="flow-icon"><Server size={19} /></span><div><h3>Saved securely on your backend</h3><p>Your access token never reaches the browser.</p></div></div>
        <div className="flow-connector"><ArrowDown size={14} /></div>
        <div className="flow-step"><span className="flow-icon"><LayoutDashboard size={19} /></span><div><h3>Make yourself at home</h3><p>View your profile, products, and exchanges.</p></div></div>
        <div className="session-note"><Clock3 size={18} /><p><strong>A small note on sessions</strong>Kite sessions expire at 6 AM the next day. When yours expires, just connect again.</p></div>
      </aside>
    </div>
    <section className={`setup-help ${helpOpen ? 'is-open' : ''}`}>
      <button className="help-trigger" onClick={() => setHelpOpen(!helpOpen)} aria-expanded={helpOpen} aria-controls="setup-steps"><span className="square-icon"><Terminal size={20} /></span><span><strong>First time using Kite Connect?</strong><span>Three quick steps to get your credentials ready.</span></span><span className="help-label">Setup guide</span><ChevronDown size={18} /></button>
      {helpOpen && <ol id="setup-steps" className="setup-steps"><li><strong>Create a Kite Connect app.</strong> In the <a href="https://developers.kite.trade/" target="_blank" rel="noreferrer">developer console <ExternalLink size={12} /></a>, create or select an app. Copy its API key and secret.</li><li><strong>Set your redirect URL.</strong> Use <code>http://127.0.0.1:5173/login</code> in the developer console. Enter your API key above and choose “Get request token”.</li><li><strong>Complete the Kite login.</strong> Copy the <code>request_token</code> value from the redirected URL into this form. Submit promptly; request tokens expire in a few minutes.</li></ol>}
    </section>
  </>
}

function UserTab({ profile, refreshing, onRefresh }: { profile: Profile | null; refreshing: boolean; onRefresh: () => void }) {
  if (!profile) return <div className="panel profile-empty"><UserRound size={32} /><h2>{refreshing ? 'Loading your profile…' : 'Your profile is not available yet'}</h2><p>{refreshing ? 'Fetching your account details from Kite.' : 'Try refreshing to retrieve your account details.'}</p><button className="secondary-button" onClick={onRefresh} disabled={refreshing}><RefreshCw size={16} className={refreshing ? 'spin' : ''} /> Refresh profile</button></div>
  const initials = profile.user_name.trim().split(/\s+/).map(part => part[0]).slice(0, 2).join('').toUpperCase() || 'U'
  return <>
    <section className="panel identity-card"><div className="profile-avatar">{initials}<span><Check size={11} /></span></div><div className="identity-details"><span className="eyebrow">ZERODHA ACCOUNT</span><h2>{profile.user_name}</h2><div className="identity-id">User ID <code>{profile.user_id}</code></div></div><span className="account-badge"><ShieldCheck size={15} /> Authenticated</span></section>
    <div className="profile-grid">
      <section className="panel"><div className="section-heading"><div><h2>Account details</h2><p>Your profile, directly from Kite.</p></div><UserRound size={19} /></div><dl className="detail-list"><div><dt>User Name</dt><dd>{profile.user_name}</dd></div><div><dt>User ID</dt><dd><code>{profile.user_id}</code></dd></div><div><dt>Connection</dt><dd><Status connected /></dd></div></dl><div className="panel-caption"><LockKeyhole size={14} /> Profile information is read-only.</div></section>
      <section className="panel"><div className="section-heading"><div><h2>Products <span className="count">{profile.products.length}</span></h2><p>Products enabled on your account.</p></div><CheckCheck size={19} /></div><div className="product-list">{profile.products.length ? profile.products.map(product => <div className="product-row" key={product}><span className="product-code">{product}</span><span>{productNames[product] || product}</span><Check size={15} /></div>) : <p className="empty-copy">No products are enabled on this account.</p>}</div></section>
      <section className="panel exchanges-panel"><div className="section-heading"><div><h2>Exchanges <span className="count">{profile.exchanges.length}</span></h2><p>Markets available to your account.</p></div><Origami size={20} /></div><div className="exchange-grid">{profile.exchanges.length ? profile.exchanges.map(exchange => <div className="exchange" key={exchange}><div><strong>{exchange}</strong><span className="enabled-dot" /></div><span>{exchangeNames[exchange] || 'Enabled exchange'}</span></div>) : <p className="empty-copy">No exchanges are enabled on this account.</p>}</div></section>
    </div>
  </>
}

function SessionTab({ session }: { session: Session }) {
  return <div className="session-grid"><section className="panel"><div className="section-heading"><div><h2>Your current session</h2><p>Ready to pick up where you left off.</p></div><ShieldCheck size={21} /></div><dl className="detail-list"><div><dt>Status</dt><dd><Status connected /></dd></div><div><dt>Connected at</dt><dd>{dateLabel(session.saved_at)}</dd></div><div><dt>Session storage</dt><dd>Backend only</dd></div><div><dt>Restore on reload</dt><dd className="positive"><Check size={15} /> Enabled</dd></div></dl></section><section className="panel session-explainer"><span className="square-icon orange"><RefreshCw size={21} /></span><h2>Keep building, stay connected.</h2><p>Your saved session survives page refreshes, frontend updates, and backend restarts in this browser.</p><div className="session-note"><Clock3 size={18} /><p><strong>Sessions have a daily expiry</strong>Kite expires access tokens at 6 AM the next day. A logout or revocation can end the session earlier.</p></div><a className="inline-link" href={docs} target="_blank" rel="noreferrer">Read about Kite sessions <ArrowUpRight size={15} /></a></section></div>
}

export default function App() {
  const [session, setSession] = useState<Session>({ authenticated: false, saved_at: null })
  const [profile, setProfile] = useState<Profile | null>(null)
  const [checking, setChecking] = useState(true)
  const [restoreFailed, setRestoreFailed] = useState(false)
  const [working, setWorking] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'user' | 'signals' | 'session'>('user')
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const refreshInFlight = useRef(false)
  const changeRoute = useCallback((authenticated: boolean) => {
    const path = authenticated ? '/dashboard' : '/login'
    if (window.location.pathname !== path) window.history.replaceState(null, '', path)
  }, [])

  const refreshProfile = useCallback(async () => {
    if (refreshInFlight.current) return
    refreshInFlight.current = true
    setRefreshing(true)
    setError('')
    try { setProfile(await api.profile()); setLastUpdated(new Date()) }
    catch (err) {
      if (err instanceof ApiError && err.status === 401) { setSession({ authenticated: false, saved_at: null }); setProfile(null); changeRoute(false) }
      setError(err instanceof Error ? err.message : 'Could not load your profile.')
    } finally { refreshInFlight.current = false; setRefreshing(false) }
  }, [changeRoute])

  useEffect(() => {
    let active = true
    api.session().then(value => {
      if (!active) return
      setSession(value); changeRoute(value.authenticated)
      if (value.authenticated) void refreshProfile()
    }).catch(err => { if (active) { setError(err.message); setRestoreFailed(true) } }).finally(() => { if (active) setChecking(false) })
    return () => { active = false }
  }, [changeRoute, refreshProfile])

  async function retrySession() {
    setChecking(true); setError(''); setRestoreFailed(false)
    try {
      const value = await api.session()
      setSession(value); changeRoute(value.authenticated)
      if (value.authenticated) await refreshProfile()
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not check your saved session.'); setRestoreFailed(true) }
    finally { setChecking(false) }
  }

  async function login(credentials: Credentials) {
    setWorking(true); setError(''); setRestoreFailed(false)
    try {
      const value = await api.login(credentials)
      setSession(value); setTab('user'); changeRoute(true)
      await refreshProfile()
      return true
    } catch (err) { setError(err instanceof Error ? err.message : 'Login failed. Please try again.'); return false }
    finally { setWorking(false) }
  }

  async function logout() {
    setWorking(true); setError('')
    try { await api.logout(); setSession({ authenticated: false, saved_at: null }); setProfile(null); setLastUpdated(null); changeRoute(false) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not disconnect. Please try again.') }
    finally { setWorking(false) }
  }

  function tabKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const tabs = ['user', 'signals', 'session'] as const
    const next = event.key === 'Home' ? 'user' : event.key === 'End' ? 'session' : tabs[(tabs.indexOf(tab) + (event.key === 'ArrowRight' ? 1 : 2)) % tabs.length]
    setTab(next); document.getElementById(`tab-${next}`)?.focus()
    if (next === 'user') void refreshProfile()
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href={session.authenticated ? '/dashboard' : '/login'}><span className="brand-icon"><Origami size={26} /></span><span>kite<span className="brand-sub">workspace</span></span></a>
      <div className="workspace-switch"><span className="workspace-icon"><Code2 size={18} /></span><span>Personal workspace<small>Local development</small></span><span className="workspace-key">L</span></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Main navigation"><button className="nav-item active" onClick={() => { setTab('user'); if (session.authenticated) void refreshProfile() }}><LayoutDashboard size={18} /><span>Dashboard</span><ChevronRight size={15} /></button></nav>
      <div className="sidebar-bottom"><div className="sidebar-tip"><span className="tip-heading"><ShieldCheck size={17} /> Private by design</span><p>Your connection stays on this machine. Your token stays on the backend.</p></div><a className="nav-item docs-link" href={docs} target="_blank" rel="noreferrer"><CircleHelp size={18} /><span>Documentation</span><ArrowUpRight size={15} /></a><div className="sidebar-account"><span className="small-avatar"><UserRound size={18} /></span><span><strong>{profile?.user_name || 'Your account'}</strong><Status connected={session.authenticated} /></span>{session.authenticated && <button className="icon-button" aria-label="Disconnect account" onClick={logout} disabled={working || refreshing}><LogOut size={17} /></button>}</div></div>
    </aside>
    <div className="workspace-main"><header className="topbar"><div className="breadcrumbs"><span>Workspace</span><ChevronRight size={14} /><strong>{session.authenticated ? 'Dashboard' : 'Connection'}</strong></div><div className="topbar-right"><span className="local-badge"><span />Local environment</span><span className="topbar-divider" /><ShieldCheck size={18} /></div></header>
      <main>
        {error && <Notice onClose={() => setError('')}>{error}{restoreFailed && <button className="retry-button" onClick={retrySession} disabled={checking || working}><RefreshCw size={14} /> Retry saved session</button>}</Notice>}
        {checking ? <div className="loading-view" role="status"><LoaderCircle size={26} className="spin" /><h2>Checking your saved session</h2><p>Getting your workspace ready…</p></div> : !session.authenticated ? <Login onLogin={login} working={working} /> : <>
          <div className="page-heading"><div><div className="eyebrow">YOUR WORKSPACE</div><h1>{tab === 'signals' ? 'Market signals' : 'Account overview'}</h1><p>{tab === 'signals' ? 'Explore Nifty 100 momentum, one crossover at a time.' : 'Your Kite profile and connection, in one place.'}</p></div>{tab === 'signals' ? <span className="heading-mark"><Activity size={18} /> NIFTY 100</span> : <button className="secondary-button" onClick={refreshProfile} disabled={refreshing || working}><RefreshCw size={16} className={refreshing ? 'spin' : ''} />{refreshing ? 'Refreshing…' : 'Refresh profile'}</button>}</div>
          <div className="tabs-row"><div className="tabs" role="tablist" aria-label="Account dashboard"><button id="tab-user" role="tab" aria-selected={tab === 'user'} aria-controls="panel-user" tabIndex={tab === 'user' ? 0 : -1} onKeyDown={tabKey} onClick={() => { setTab('user'); void refreshProfile() }}><UserRound size={17} /> User</button><button id="tab-signals" role="tab" aria-selected={tab === 'signals'} aria-controls="panel-signals" tabIndex={tab === 'signals' ? 0 : -1} onKeyDown={tabKey} onClick={() => setTab('signals')}><Activity size={17} /> Signals</button><button id="tab-session" role="tab" aria-selected={tab === 'session'} aria-controls="panel-session" tabIndex={tab === 'session' ? 0 : -1} onKeyDown={tabKey} onClick={() => setTab('session')}><ShieldCheck size={17} /> Session</button></div><span className="updated" aria-live="polite">{tab === 'signals' ? 'Completed candles · IST' : lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Waiting for profile'}</span></div>
          <div id="panel-user" role="tabpanel" aria-labelledby="tab-user" tabIndex={0} hidden={tab !== 'user'}><UserTab profile={profile} refreshing={refreshing} onRefresh={refreshProfile} /></div>
          <div id="panel-signals" role="tabpanel" aria-labelledby="tab-signals" tabIndex={0} hidden={tab !== 'signals'}><SignalsTab onExpired={message => { setSession({ authenticated: false, saved_at: null }); setProfile(null); setLastUpdated(null); setError(message); changeRoute(false) }} /></div>
          <div id="panel-session" role="tabpanel" aria-labelledby="tab-session" tabIndex={0} hidden={tab !== 'session'}><SessionTab session={session} /></div>
        </>}
        <footer className="page-footer"><span><Origami size={15} /> Built for your Kite connection.</span><span><LockKeyhole size={12} /> Local workspace <i /> Backend-only token storage</span></footer>
      </main>
    </div>
  </div>
}
