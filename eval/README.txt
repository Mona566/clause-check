Synthetic memos for Clause Check. Not real contracts.

dev/     20 memos. Use these while you change the prompt, at most three times.
holdout/ 10 memos. Do not open this folder until the prompt is frozen.
         Then run the eval once.

Each memo-NN.json is the gold label for memo-NN.txt.
null means the field is absent. Do not guess a value.
Fields: buyer, supplier, contract_date, total_amount, currency, payment_terms_days.
