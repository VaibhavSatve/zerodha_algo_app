import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Activity, ArrowDown, ArrowUp, CircleHelp, Clock3, ListFilter, LoaderCircle, Search, ScanLine } from 'lucide-react'
import { api, ApiError } from './api'
import type { ScanParameters, ScanResult, Timeframe } from './api'
import './signals.css'

const timeframes: Record<Timeframe, string> = { '5minute': '5 Minute', '15minute': '15 Minute', '60minute': '1 Hour', '4hour': '4 Hour' }
const defaults: ScanParameters = { short_ema: 6, long_ema: 21, timeframe: '5minute', lookback_days: 30, max_stocks: 100 }
const price = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const generatedTime = (value: string) => new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))

export default function SignalsTab({ onExpired }: { onExpired: (message: string) => void }) {
  const [parameters, setParameters] = useState(defaults)
  const [result, setResult] = useState<ScanResult | null>(null)
  const [scanning, setScanning] = useState(false)
  const pending = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'All' | 'Bullish' | 'Bearish'>('All')

  function change<K extends keyof ScanParameters>(name: K, value: ScanParameters[K]) {
    setParameters(current => ({ ...current, [name]: value }))
    // Never label older EMA values with newly edited periods.
    setResult(null)
    setError('')
  }

  async function generate(event: FormEvent) {
    event.preventDefault()
    if (pending.current) return
    if (parameters.short_ema >= parameters.long_ema) { setError('Short EMA must be smaller than Long EMA.'); return }
    pending.current = true
    setScanning(true); setError(''); setResult(null)
    try { const response = await api.signals(parameters); if (mounted.current) setResult(response) }
    catch (err) {
      if (!mounted.current) return
      const message = err instanceof Error ? err.message : 'Could not generate signals. Please try again.'
      if (err instanceof ApiError && err.status === 401) onExpired(message)
      else setError(message)
    } finally { pending.current = false; if (mounted.current) setScanning(false) }
  }

  const query = search.trim().toLowerCase()
  const rows = result?.signals.filter(row => (filter === 'All' || row.crossover_type === filter)
    && (row.ticker.toLowerCase().includes(query) || row.company.toLowerCase().includes(query))) ?? []
  const shown = result?.parameters ?? parameters

  return <div className="signals-tab">
    <section className="panel scanner-settings" aria-labelledby="scanner-title">
      <div className="scanner-heading"><span className="square-icon orange"><Activity size={21} /></span><div><h2 id="scanner-title">Nifty 100 crossover scanner</h2><p>Strategy: EMA {shown.short_ema || "—"}/{shown.long_ema || "—"} + MACD 12/26/9 Confirmation</p></div><span className="scanner-market"><span /> NSE EQUITY</span></div>
      <form onSubmit={generate}>
        <fieldset disabled={scanning} className="scanner-fields">
          <legend className="sr-only">Scanner parameters</legend>
          <label>Short EMA<input type="number" min="1" max="100" step="1" required value={parameters.short_ema || ''} onChange={event => change('short_ema', Number(event.target.value))} /></label>
          <label>Long EMA<input type="number" min="1" max="100" step="1" required value={parameters.long_ema || ''} onChange={event => change('long_ema', Number(event.target.value))} /></label>
          <label>Timeframe<select value={parameters.timeframe} onChange={event => change('timeframe', event.target.value as Timeframe)}>{Object.entries(timeframes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>Lookback Days<input type="number" min="1" max="90" step="1" required value={parameters.lookback_days || ''} onChange={event => change('lookback_days', Number(event.target.value))} /></label>
          <label>Max Stocks<input type="number" min="1" max="100" step="1" required value={parameters.max_stocks || ''} onChange={event => change('max_stocks', Number(event.target.value))} /></label>
          <button className="primary-button generate-signals" disabled={scanning} type="submit">{scanning ? <><LoaderCircle size={17} className="spin" /> Scanning…</> : <><ScanLine size={17} /> Generate Signals</>}</button>
        </fieldset>
        <div className="scanner-hint"><Clock3 size={14} /><p>Both crossovers on the same completed candle · Times in IST · Up to 100 stocks in alphabetical order. A full scan can take several minutes.</p></div>
        {parameters.timeframe === '4hour' && <p className="four-hour-note">4-hour bars follow the NSE session: 09:15–13:15, then a shorter closing bar from 13:15–15:30.</p>}
      </form>
    </section>

    {error && <div className="notice" role="alert"><CircleHelp size={18} /><span>{error}</span></div>}

    <div className="signal-summary" aria-label="Scan summary">
      <div><span>Stocks Scanned</span><strong>{result?.stocks_scanned ?? '—'}<small>{result ? ` / ${result.stocks_selected} selected` : ' / 100 universe'}</small></strong></div>
      <div><span>Signals Found</span><strong>{result?.signals_found ?? '—'}</strong></div>
      <div><span>Bullish Signals</span><strong className="bullish-text">{result?.bullish_signals ?? '—'}<ArrowUp size={16} /></strong></div>
      <div><span>Bearish Signals</span><strong className="bearish-text">{result?.bearish_signals ?? '—'}<ArrowDown size={16} /></strong></div>
      <div><span>Selected Timeframe</span><strong className="summary-label">{timeframes[shown.timeframe]}</strong></div>
      <div><span>Last Generated · IST</span><strong className="summary-label">{result ? generatedTime(result.generated_at) : 'Not yet'}</strong></div>
    </div>

    {result && result.warnings.length > 0 && <details className="scan-warnings"><summary><CircleHelp size={16} />{result.warnings.length} stock{result.warnings.length === 1 ? '' : 's'} could not be analyzed · View details</summary><ul>{result.warnings.map((warning, index) => <li key={index}>{warning.ticker && <strong>{warning.ticker}: </strong>}{warning.message}</li>)}</ul></details>}

    <section className="panel signals-results" aria-labelledby="results-title" aria-busy={scanning}>
      <div className="results-toolbar"><div><h2 id="results-title">Latest confirmed signals <span className="count">{result?.signals_found ?? 0}</span></h2><p>Latest EMA + MACD crossover in the same direction, on the same candle, per stock.</p></div><div className="signal-filters"><label className="signal-search"><Search size={16} /><span className="sr-only">Search by ticker or company</span><input type="search" placeholder="Search ticker or company" value={search} onChange={event => setSearch(event.target.value)} /></label><label className="signal-filter"><ListFilter size={16} /><span className="sr-only">Crossover filter</span><select value={filter} onChange={event => setFilter(event.target.value as typeof filter)}><option>All</option><option>Bullish</option><option>Bearish</option></select></label></div></div>
      <div className="signals-table-scroll" tabIndex={0} role="region" aria-label="Ranked crossover results">
        <table className="signals-table"><caption className="sr-only">Nifty 100 EMA + MACD confirmed crossovers ranked by candle start date and time in IST</caption><thead><tr><th scope="col">Rank</th><th scope="col">Ticker</th><th scope="col">Company</th><th scope="col">Timeframe</th><th scope="col">Signal Type</th><th scope="col">Crossover Date</th><th scope="col">Crossover Time · IST</th><th scope="col" className="number">Close</th><th scope="col" className="number">EMA {shown.short_ema || '—'}</th><th scope="col" className="number">EMA {shown.long_ema || '—'}</th><th scope="col" className="number">MACD</th><th scope="col" className="number">MACD Signal</th></tr></thead>
          <tbody>{rows.map(row => <tr key={row.ticker}><td className="rank-cell">{row.rank.toString().padStart(2, '0')}</td><th scope="row" className="ticker-cell">{row.ticker}</th><td className="company-cell" title={row.company}>{row.company}</td><td><span className="timeframe-badge">{timeframes[row.timeframe]}</span></td><td><span className={`crossover-badge ${row.crossover_type.toLowerCase()}`}>{row.crossover_type === 'Bullish' ? <ArrowUp size={13} /> : <ArrowDown size={13} />}{row.crossover_type}</span></td><td>{row.crossover_date}</td><td className="time-cell">{row.crossover_time}</td><td className="number close-cell">{price.format(row.close)}</td><td className="number">{price.format(row.short_ema)}</td><td className="number">{price.format(row.long_ema)}</td><td className="number">{price.format(row.macd)}</td><td className="number">{price.format(row.macd_signal)}</td></tr>)}</tbody>
        </table>
      </div>
      {scanning ? <div className="signals-empty" role="status"><LoaderCircle size={29} className="spin" /><h3>Scanning Nifty 100 stocks...</h3><p>Checking completed candles for simultaneous EMA + MACD crossovers.<br />You can switch dashboard tabs while this scan runs.</p><span className="scan-indicator" /></div>
        : !result ? <div className="signals-empty"><span className="empty-scan-icon"><ScanLine size={28} /></span><h3>Your next scan starts here</h3><p>Choose your EMA periods and timeframe,<br />then select Generate Signals.</p></div>
          : rows.length === 0 ? <div className="signals-empty" role="status"><Search size={27} /><h3>{result.stocks_analyzed === 0 ? 'No stocks could be analyzed' : result.signals_found === 0 ? 'No confirmed crossovers in this period' : 'No matching signals'}</h3><p>{result.stocks_analyzed === 0 ? 'Review the details above, check historical-data access, and try again.' : result.signals_found === 0 ? 'No same-candle EMA + MACD confirmation was found. Try a longer lookback or a different timeframe.' : 'Try another ticker, company, or crossover filter.'}</p></div> : null}
      <div className="results-footnote"><span>{result ? `${rows.length} of ${result.signals_found} signals · ${result.stocks_analyzed} stocks analyzed` : 'Results appear after your first scan'}</span><span>Candle start times · Prices in INR</span></div>
    </section>
  </div>
}
