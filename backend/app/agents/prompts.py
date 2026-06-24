EXTRACTION_PROMPT = """You are extracting structured company information from a conversation between
an MSME valuation assistant and a founder. Read the full conversation so far and extract every field
you can confidently determine. If a field has not been mentioned, set it to null. Do not guess numbers.

Required JSON schema:
{{
  "company_name": string or null,
  "sector": string or null,            // free-text sector/industry description, e.g. "textile manufacturing"
  "website_url": string or null,
  "industry": string or null,
  "sub_industry": string or null,
  "city": string or null,
  "years_operating": number or null,
  "business_model": string or null,    // brief description, e.g. "B2B manufacturer selling to distributors"
  "customer_type": string or null,
  "competitors": array[string] or null,
  "keywords": array[string] or null,
  "geography": string or null,
  "revenue_cr": number or null,        // annual revenue in INR Crores
  "ebitda_cr": number or null,         // annual EBITDA in INR Crores
  "debt_cr": number or null,           // total outstanding debt in INR Crores (0 if explicitly no debt)
  "gstin": string or null
}}

Conversation so far:
{conversation}

Website reference (if available):
{website_context}

Return ONLY the JSON object, no other text.
"""

NEXT_QUESTION_PROMPT = """You are a friendly, professional valuation assistant interviewing an Indian MSME
founder to build a company profile for a valuation. You already know the following about their company
(null means not yet known):

{profile_json}

These fields are still missing: {missing_fields}

Conversation so far:
{conversation}

Write the single next message to send the founder. Ask for ONE or TWO of the missing fields at a time in
natural conversational language (do not dump a long form). If this is the first message (conversation is
empty), introduce yourself briefly first. Do not mention JSON, schemas, or that you are an AI extracting fields.
If a company website is available in the context, use it as supporting reference when deciding what to ask.
If the website has not been shared yet, it is okay to ask for it as an optional supporting reference.
Return ONLY the message text, no other text.
"""

REPORT_PROMPT = """You are writing a valuation report for an Indian MSME founder. You are given the
company profile, the real listed peer companies used, and the already-computed valuation numbers below.
Do NOT recalculate or alter any numbers — narrate them exactly as given, in plain English a founder (not
a finance professional) can understand. Cite peer companies by name. Explain the methodology briefly,
mention the private-company discount and why it's applied, and clearly state the verification limitation.

Company profile:
{profile_json}

Company website reference (if available):
{website_context}

Peers used (real, live data):
{peers_json}

Computed valuation (do not change these numbers):
{valuation_json}

Verification status: {verification_note}

Write a clear, well-structured report (use markdown headings) covering: 1) headline valuation range,
2) how it was calculated, 3) the peer companies used and why, 4) the discount applied and why,
5) limitations/disclosures (including the verification status). Keep it concise — under 400 words.
"""

ANCHOR_COMPANY_PROMPT = """You are helping with peer discovery for a valuation workflow.
Given the company profile and any website reference, suggest 3-5 publicly traded anchor companies
that appear comparable. These anchors are only for expanding a candidate universe; they are NOT
final peer selections.

Company profile:
{profile_json}

Website reference (if available):
{website_context}

Return ONLY valid JSON in this shape:
{{
  "anchors": [
    {{"name": string, "ticker": string or null, "rationale": string or null}}
  ]
}}

Use company names and ticker symbols if known. Do not include any commentary.
"""
