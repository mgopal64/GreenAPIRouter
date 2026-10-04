// Hand-labeled prompt set (the same set used to pick the picker's 0.70 cutoff).
// simple  = a small model handles it reliably
// complex = multi-step reasoning, many constraints, or long/expert output; a strong model is clearly worth it
// Labels are her best judgment, not measured ground truth.

const simple = [
  'Convert 72 degrees Fahrenheit to Celsius.',
  'Write a Python function that returns the square of a number.',
  'What is the difference between affect and effect?',
  'Summarize in one sentence: The meeting moved from Tuesday to Thursday at 3pm because the room is booked.',
  'Write a short poem about autumn.',
]

const complex = [
  'Design a distributed rate limiter that works across 50 servers, handles clock skew, and degrades gracefully if Redis goes down. Compare at least three approaches and justify your pick.',
  'A Python async service intermittently deadlocks under load when using a thread pool and asyncio locks. Walk through the likely causes and how to diagnose each one.',
  'Derive the closed-form solution for linear regression and explain when it fails numerically.',
  'Write an 800-word persuasive op-ed for congestion pricing with exactly four sections, including counterarguments, and never use the letter z.',
  'Design a database schema and API for a multi-tenant ride-sharing app with surge pricing, and explain the concurrency issues in driver assignment.',
]

export const DEMO_PROMPTS = [
  ...simple.map((text) => ({ text, label: 'simple' })),
  ...complex.map((text) => ({ text, label: 'complex' })),
]
