# Deploying CellLoop on AWS

CellLoop is designed so that proprietary R&D data never leaves the company's AWS account:
raw files go to S3 (SSE-KMS), records and embeddings live in RDS PostgreSQL with pgvector,
and both Claude and the embedding model are called through Amazon Bedrock, which does not
use inputs for model training.

```
Browser (React SPA, CloudFront + S3 or nginx)
   │  Cognito Hosted UI (PKCE) → ID token
   ▼
FastAPI on ECS Fargate / App Runner  ──►  Amazon Bedrock (Claude: extraction + Q&A; Titan v2: embeddings)
   │            │
   │            └──►  S3 bucket (raw partner files, SSE-KMS, Block Public Access)
   ▼
RDS PostgreSQL 16 + pgvector (experiments, chunks + HNSW index, audit_log)
```

## 1. Amazon Cognito

1. Create a user pool with email sign-in and MFA (required for partners is recommended).
2. Add a custom attribute `custom:organization` (string, admin-writable only).
   Set it to the partner's slug (e.g. `northgate-univ`) for partner users.
3. Create groups: `partner`, `scientist`, `leadership`, `admin`. The API maps the most
   privileged group to the role; internal groups are always organization `internal`.
4. Create an app client **without a client secret**, enable the authorization-code grant,
   scopes `openid email profile`, callback `https://<your-domain>/auth/callback`, sign-out
   URL `https://<your-domain>`.
5. Make sure the custom attribute is **not writable** by the app client, otherwise a partner
   could change their own organization.

Backend env: `AUTH_MODE=cognito`, `COGNITO_REGION`, `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`.
Frontend build args: `VITE_AUTH_MODE=cognito`, `VITE_COGNITO_DOMAIN`, `VITE_COGNITO_CLIENT_ID`, `VITE_COGNITO_REDIRECT_URI`.

## 2. RDS PostgreSQL + pgvector

- PostgreSQL 16 in private subnets, encrypted storage, automated backups.
- Run `CREATE EXTENSION IF NOT EXISTS vector;` once (see [`db/init.sql`](../db/init.sql)).
- `DATABASE_URL=postgresql+psycopg://<user>:<pass>@<endpoint>:5432/cellloop` (store in Secrets Manager).
- Tables and the HNSW cosine index are created on API start-up. Before production schema
  changes, introduce Alembic migrations.

## 3. S3

- Bucket with Block Public Access, default SSE-KMS, versioning on, and a lifecycle rule to Glacier
  for old raw files.
- Backend env: `STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_KMS_KEY_ID`.
- Files are only served through the API (`/api/documents/{id}/file`), which enforces tenant scoping
  and writes a `download` audit event; no presigned URLs are handed to browsers.

## 4. Amazon Bedrock

- In the Bedrock console, enable model access for Claude Opus 5.5 and Titan Text Embeddings V2 in your region.
- Backend env: `LLM_PROVIDER=bedrock`, `AWS_REGION`, `BEDROCK_CLAUDE_MODEL=anthropic.claude-opus-5-5`,
  `BEDROCK_EMBEDDING_MODEL=amazon.titan-embed-text-v2:0`.
- Claude is called with the Anthropic Python SDK's Bedrock client (`AnthropicBedrockMantle`), using
  structured outputs (a JSON schema generated from `experiment_schema.py`) for extraction.

## 5. IAM policy for the API task role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Bedrock",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock-mantle:*"],
      "Resource": "*"
    },
    {
      "Sid": "RawFiles",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::YOUR-CELLLOOP-BUCKET/*"
    },
    {
      "Sid": "Kms",
      "Effect": "Allow",
      "Action": ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:REGION:ACCOUNT:key/YOUR-KEY-ID"
    }
  ]
}
```

Scope the Bedrock `Resource` down to the specific model/inference-profile ARNs once they're
confirmed in your account. No `s3:DeleteObject`: raw submissions are immutable evidence.

## 6. Production checklist

- `APP_ENV=prod` (the API refuses to start with `AUTH_MODE=dev` in prod).
- `CORS_ORIGINS` set to the real frontend origin only.
- Run extraction on a queue (SQS + worker) instead of FastAPI background tasks if upload volume grows.
- Enable `INSTALL_ML=1` in the API image to use BoTorch and impedance.py.
- CloudWatch alarms on extraction failures (`ai_extraction_failed` audit events) and on review-queue age > 36 h.
