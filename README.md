# WordBash Multiplayer CDK Infrastructure

AWS CDK v2 Python app that deploys infrastructure for a multiplayer WordBash game with ECS Fargate services and DynamoDB.

## Architecture

- **NetworkStack**: VPC with public/private subnets across 2 AZs, NAT gateway
- **DataStack**: DynamoDB table `wordbash_games` with on-demand billing
- **ComputeStack**: ECS Fargate cluster, ALB with HTTP/WebSocket support, two services:
  - Web Service: React SPA and API (`/api/*`, `/`)
  - Game Service: WebSocket server (`/ws/*`)

## Prerequisites

- Node.js (for CDK CLI)
- Python 3.11+
- AWS credentials configured
- AWS CDK v2 installed: `npm install -g aws-cdk`

## Setup

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Bootstrap CDK (first time only)
cdk bootstrap
```

## Configuration

Edit `cdk.json` context to customize:
- `web_image_path`: Path to web service Docker context (default: `../web`)
- `game_image_path`: Path to game service Docker context (default: `../game`)
- `keep_data`: Set to `true` to retain DynamoDB table on stack deletion

## Deployment

```bash
# Deploy all stacks
cdk deploy --all

# Deploy specific stack
cdk deploy WordBashComputeStack
```

## Expected Outputs

After deployment, note these CloudFormation outputs:
- **AlbDnsName**: Load balancer DNS name
- **WebServiceUrl**: `https://{alb_dns}` - Main web application
- **WebSocketUrl**: `wss://{alb_dns}/ws` - WebSocket endpoint
- **DynamoDbTableName**: DynamoDB table name
- **WsEndpointParamPath**: SSM parameter path for WS endpoint

## Health Checks

- Web Service: `https://{alb_dns}/api/healthz`
- Game Service: `https://{alb_dns}/ws/healthz` (via HTTP before WebSocket upgrade)

## Container Requirements

Your application containers should:
- Listen on port 8080
- Implement `/healthz` endpoint returning HTTP 200
- Use environment variables:
  - `AWS_REGION`, `LOG_LEVEL`, `DDB_TABLE_NAME`
  - Web Service also gets: `WS_ENDPOINT_PARAM`, `API_BASE_URL`

## WebSocket Support

The ALB automatically handles WebSocket upgrade for `/ws/*` paths. Target group configured with:
- Sticky sessions enabled
- Extended idle timeout for long-lived connections
- Health checks on HTTP endpoint before upgrade

## Updating Images

```bash
# Redeploy to update container images
cdk deploy WordBashComputeStack
```

## Viewing Logs

CloudWatch log groups (14-day retention):
- `/aws/ecs/wordbash-web`
- `/aws/ecs/wordbash-game`

## TODO

- [ ] Add ACM certificate for custom domain
- [ ] Enable ALB access logs
- [ ] Add Route53 hosted zone for custom domain
- [ ] Consider Application Auto Scaling for more granular scaling policies

## Cleanup

```bash
cdk destroy --all
```

Note: DynamoDB table will be deleted unless `keep_data: true` is set in `cdk.json`.
