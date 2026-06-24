export interface PeerCompany {
  ticker: string
  name: string
  sector_tag: string
  sector: string | null
  sector_key: string | null
  industry: string | null
  industry_key: string | null
  country: string | null
  revenue_growth: number | null
  enterprise_value_cr: number | null
  full_time_employees: number | null
  long_business_summary: string | null
  ev_ebitda: number | null
  ev_revenue: number | null
  ebitda_margin: number | null
  market_cap_cr: number | null
  revenue_cr: number | null
  source: string
  similarity_score: number | null
  ranking_rationale: string | null
}

export interface ValuationRange {
  low_cr: number
  median_cr: number
  high_cr: number
}

export interface CompanyProfile {
  company_name: string | null
  sector: string | null
  nse_sector_tag: string | null
  website_url: string | null
  city: string | null
  years_operating: number | null
  business_model: string | null
  revenue_cr: number | null
  ebitda_cr: number | null
  debt_cr: number | null
  gstin: string | null
}

export interface ValuationReport {
  profile: CompanyProfile
  peers_used: PeerCompany[]
  median_ev_ebitda: number | null
  median_ev_revenue: number | null
  enterprise_value_cr: number | null
  equity_value_pre_discount_cr: number | null
  discount_applied: number
  equity_value_post_discount_cr: number | null
  range: ValuationRange | null
  methodology_notes: string[]
  verified: boolean
  verification_note: string
  narrative: string
}

export interface ChatResponse {
  stage: 'interview' | 'report_ready'
  message: string
  profile: CompanyProfile
  report: ValuationReport | null
}

export async function createSession(): Promise<{ session_id: string; message: string }> {
  const res = await fetch('/api/session', { method: 'POST' })
  if (!res.ok) throw new Error('Failed to create session')
  return res.json()
}

export async function sendMessage(sessionId: string, message: string): Promise<ChatResponse> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  })
  if (!res.ok) throw new Error('Failed to send message')
  return res.json()
}
