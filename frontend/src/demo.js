// Hand-labeled prompt set (the same set used to pick the picker's 0.70 cutoff).
// simple  = a small model handles it reliably
// medium  = small model is usually fine, may miss depth or detail
// complex = multi-step reasoning, many constraints, or long/expert output; a strong model is clearly worth it
// Labels are her best judgment, not measured ground truth.

const simple = [
  'What is the capital of Australia?',
  "Translate 'thank you very much' into French.",
  'What does HTML stand for?',
  'Convert 72 degrees Fahrenheit to Celsius.',
  'Give me a synonym for the word happy.',
  'Write a Python function that returns the square of a number.',
  'What year did World War II end?',
  "Fix the grammar: 'me and him goes to the store yesterday.'",
  'List three common houseplants.',
  'What is the difference between affect and effect?',
  'How many days are in a leap year?',
  'Write a one-line greeting for a birthday card.',
  'What is the boiling point of water in Celsius?',
  'Summarize in one sentence: The meeting moved from Tuesday to Thursday at 3pm because the room is booked.',
  'Write a short poem about autumn.',
  'Write a friendly product description for a reusable water bottle in under 100 words.',
]

const medium = [
  'Explain how a hash map works and when you would use one.',
  'Write a SQL query that returns the top 3 customers by revenue in each region.',
  'Summarize the causes of the French Revolution in a paragraph.',
  'Write a Python function that checks whether a string is a palindrome, ignoring punctuation and case, and include a few tests.',
  'Explain the difference between TCP and UDP with examples.',
  'Draft a polite email asking my landlord to fix a leaking faucet.',
  'What are the pros and cons of renting versus buying a home?',
  'Write a regex that validates US phone numbers in several common formats, and explain how it works.',
  'Give me a 3-day vegetarian meal plan with high protein.',
  'Explain how vaccines train the immune system, for a high school student.',
  'Explain what a closure is in JavaScript, with an example.',
  'Compare Python and Go for building a web backend.',
  'Prove that the square root of 2 is irrational, then generalize the argument to any non-square integer.',
  'Three friends split a bill: Alice ordered $24, Bob $36, Carol $18. Tax is 8%, tip is 20% of the pre-tax total, and Carol has a $5 coupon applied before tax. Compute what each person pays and show every step.',
]

const complex = [
  'Design a distributed rate limiter that works across 50 servers, handles clock skew, and degrades gracefully if Redis goes down. Compare at least three approaches and justify your pick.',
  'Write a 1,500-word short story in the style of Raymond Carver, told from two perspectives, with an unreliable narrator and no dialogue tags.',
  'A Python async service intermittently deadlocks under load when using a thread pool and asyncio locks. Walk through the likely causes and how to diagnose each one.',
  'Derive the closed-form solution for linear regression and explain when it fails numerically.',
  'Implement a B-tree in Python with insert and delete, give the complexity analysis, and write unit tests.',
  'Analyze the tradeoffs between Raft and Paxos for a geo-distributed database across 5 regions, recommend one, and walk through failure scenarios.',
  "Create a 12-week first-marathon training plan for someone who runs 10 km per week now and has a history of knee injury, and explain the reasoning behind each week's mileage.",
  "Review this indemnification clause, identify ambiguities and risks for the vendor, and propose three rewrites with different risk allocations: 'Vendor shall indemnify Client against all losses arising from the services.'",
  "Explain the proof of Godel's first incompleteness theorem at a level a CS grad student could follow, including the diagonal lemma.",
  'Write an 800-word persuasive op-ed for congestion pricing with exactly four sections, including counterarguments, and never use the letter z.',
  'A startup has $2M runway, 8 engineers, and 3% weekly churn. Build a simple financial model and recommend whether to hire, cut, or raise, stating all assumptions.',
  'Design a database schema and API for a multi-tenant ride-sharing app with surge pricing, and explain the concurrency issues in driver assignment.',
]

export const DEMO_PROMPTS = [
  ...simple.map((text) => ({ text, label: 'simple' })),
  ...medium.map((text) => ({ text, label: 'medium' })),
  ...complex.map((text) => ({ text, label: 'complex' })),
]
