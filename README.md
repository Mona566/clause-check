# Clause Check

A small document-review API. It extracts parties, a contract date, an amount, a currency and a payment term from a short memo, checks that each quoted span really occurs in the memo, and retrieves related passages from 15 short public-procurement notes with BM25.

The service runs on AWS Lambda in `eu-west-2`, with the memo and the audit record in one DynamoDB table. `scripts/aws_bootstrap.py` creates that function, its Function URL, the table and the function role. It does not create EC2, NAT, Bedrock, S3 or RDS.

## Local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put a token in `.env` and export it. Do not commit `.env`.

```bash
set -a && source .env && set +a
pytest -q
uvicorn app.main:app --port 8000
```

```bash
curl -s http://127.0.0.1:8000/health
curl -s -H "Authorization: Bearer $API_TOKEN" -H "content-type: application/json" \
  -d '{"filename":"memo.txt","text":"Northline Borough Council awarded Harbour Analytics Ltd the work on 4 June 2025. The total amount is £18,500. Payment terms are 30 days."}' \
  http://127.0.0.1:8000/reviews
```

`GET /reviews/{id}` returns the same audit. A PDF can be sent as base64 in `content_base64`. Files over 2 MB are refused. A scan with almost no text returns `no_extractable_text`.

Extraction calls SiliconFlow when `GEMINI_API_KEY` holds a SiliconFlow key. The default model is `Qwen/Qwen2.5-7B-Instruct` and the endpoint is `https://api.siliconflow.cn/v1/chat/completions`. Real-name verification is required before a free-tier model will answer. If the model plaza shows a different free chat model, put that exact id in `GEMINI_MODEL`.

## Tests and evaluation

`pytest -q` does not call the model and does not read `eval/holdout`.

`eval/dev` has 20 memos. Change the prompt in `app/services/extract.py` at most three times, and record each score:

```bash
python -m eval.run_eval --split dev
```

`eval/holdout` has 10 memos. Do not open that folder until the prompt is frozen. Then run it once:

```bash
python -m eval.run_eval --split holdout --holdout
```

The two numbers are field accuracy and evidence validity, each over six fields. A correct amount whose quote does not support that amount counts for the first and not the second.

## Deploy later

The Lambda handler is `app.lambda_handler.handler`. After `aws configure` has an access key for this account, this command creates the function, the HTTPS Function URL, the DynamoDB table and the IAM role in eu-west-2. It copies `API_TOKEN` and `GEMINI_API_KEY` from `.env`.

```bash
.venv/bin/python scripts/aws_bootstrap.py
```

Logs contain `review_id`, stage, latency, model, token counts and `error_type`. They do not contain the memo or the extracted names and amounts.

Check the bill the next day. At this size the Lambda, DynamoDB and short CloudWatch logs stay inside the always-free quotas.


