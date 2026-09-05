# AI Recruiter infrastructure

The React frontend is deployed as static files in a private S3 bucket and served
through CloudFront. Requests under `/api/*` are forwarded by CloudFront to the
existing Application Load Balancer.

## Production resources

- Frontend bucket: `ai-recruiter-frontend-765761474007`
- CloudFront distribution: `E2D9QVT3763I47`
- Public hostname: `ai.adrianguerra.net`
- API origin hostname: `origin-ai.adrianguerra.net`
- CloudFormation stack: `ai-recruiter-frontend-static`
- Region for S3, ECS and ALB: `us-east-2`
- Region for the CloudFront ACM certificate: `us-east-1`

`ai.adrianguerra.net` has Route 53 A and AAAA aliases to CloudFront.
`origin-ai.adrianguerra.net` has an A alias to the ALB and its own ACM
certificate attached to the HTTPS listener.

## Frontend deployment

The `Frontend CI/CD` GitHub Actions workflow builds with `VITE_API_URL=/api`,
syncs immutable assets to S3, publishes `index.html` without browser caching and
then creates a CloudFront invalidation.

## Cost controls

- The frontend ECS service and its EventBridge Scheduler schedules were removed.
- The ALB and backend ECS service use `us-east-2a` and `us-east-2b` only.
- Both ECR repositories retain only the 10 most recent images and expire
  untagged images after seven days.
