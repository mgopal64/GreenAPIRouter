// Hand-labeled prompt set (the same set used to pick the picker's 0.70 cutoff).
// simple  = a small model handles it reliably
// complex = multi-step reasoning, many constraints, or long/expert output; a strong model is clearly worth it
// Labels are her best judgment, not measured ground truth.

const simple = [
  "Here's a note from a call: 'Customer called around 2pm saying she moved last month and her new card still hasn't shown up. She's checked with her old building and the mailroom, and says she's been waiting about three weeks. She was polite but a little worried because she has a trip coming up.' What was the customer's main problem?",
  "What does 'pending' mean on a card transaction?",
  'Why do gas stations sometimes place a bigger hold on my card than what I actually spent?',
  "Translate to Spanish: 'Your replacement card has shipped and should arrive in 7 to 10 days.'",
  "What's the customer asking for in this email? 'Hi, I was charged twice for the same dinner on the 14th. Can someone take a look? Thanks.'",
]

const complex = [
  "Reply to a customer who was charged a $35 late fee even though autopay is on. Under 90 words, no exclamation marks, don't promise the fee will be waived, mention that autopay issues get logged, and end with exactly one next step.",
  "Write a SQL query for a table called transactions (customer_id, amount, merchant_category, posted_at). Return customer_id and total_spend for the last 90 days only. Exclude refunds (negative amounts) and the 'travel' category, keep only customers over $2,000, sort highest first, and use no subqueries.",
  "Return only JSON with the keys merchant, amount_cents, and date from this note. Dates must be ISO 8601, amounts must be integers, use null for anything missing, and never guess. Note: 'Customer says FitZone Gym charged her $89.99 on March 3 after she canceled.'",
  "Write a balance transfer email under 120 words. Include the intro APR, fee, and standard APR. Never use 'free' or 'guaranteed.' Add [DISCLOSURE], one call to action, and no mention of competitors.",
  "Write three fraud alert text messages for a card ending in 1234. Each must be under 25 words, contain no links, never ask for a PIN or full card number, and tell the customer to reply YES or NO.",
]

export const DEMO_PROMPTS = [
  ...simple.map((text) => ({ text, label: 'simple' })),
  ...complex.map((text) => ({ text, label: 'complex' })),
]
