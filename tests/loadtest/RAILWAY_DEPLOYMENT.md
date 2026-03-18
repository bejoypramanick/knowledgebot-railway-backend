# 🚂 Railway Deployment Guide - Stockholm Load Test

## Overview
Deploy the Locust load test directly on Railway for realistic, cloud-based load testing of your customer chat endpoint.

## Benefits of Railway Deployment
- **Realistic Network Conditions**: Test from Railway's infrastructure
- **Scalable Resources**: Auto-scaling based on load
- **Persistent Testing**: Keep tests running without local machine dependency
- **Team Access**: Share test results via public URL
- **Cost Effective**: Pay only for usage during testing

## Quick Deploy to Railway

### Option 1: Deploy from GitHub (Recommended)

1. **Push to GitHub** (if not already done):
   ```bash
   git add tests/loadtest/
   git commit -m "Add Railway deployment for load testing"
   git push
   ```

2. **Deploy on Railway**:
   - Go to [Railway.app](https://railway.app)
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your repository
   - Choose the `tests/loadtest` directory as root
   - Railway will auto-detect the Dockerfile and deploy

3. **Configure Environment Variables** (Optional):
   ```
   TARGET_HOST=https://api-gateway-common.up.railway.app
   TARGET_USERS=20
   CHATS_PER_USER=5
   ```

### Option 2: Railway CLI Deploy

1. **Install Railway CLI**:
   ```bash
   npm install -g @railway/cli
   railway login
   ```

2. **Deploy from loadtest directory**:
   ```bash
   cd tests/loadtest
   railway project create stockholm-load-test
   railway up
   ```

## Configuration Files

### `Dockerfile`
- Multi-stage Python build optimized for Railway
- Installs Locust and dependencies
- Exposes port 8080 for web UI

### `railway.toml`
- Railway-specific deployment configuration
- Health checks and restart policies
- Environment variable definitions

### `start.sh`
- Railway startup script with logging
- Handles environment variable injection
- Configures Locust for cloud deployment

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TARGET_HOST` | `https://api-gateway-common.up.railway.app` | API endpoint to test |
| `TARGET_USERS` | `20` | Number of concurrent users |
| `CHATS_PER_USER` | `5` | Conversations per user |
| `PORT` | `8080` | Railway-assigned port |
| `LOCUST_WEB_HOST` | `0.0.0.0` | Web UI host binding |

## Access Your Deployed Test

Once deployed, Railway will provide a public URL like:
- **Main Dashboard**: `https://stockholm-load-test-production.up.railway.app/`
- **Detailed Results**: `https://stockholm-load-test-production.up.railway.app/test-results`
- **JSON API**: `https://stockholm-load-test-production.up.railway.app/test-results/json`

## Running Tests on Railway

### 1. Access Web UI
- Open your Railway deployment URL
- Configure test parameters:
  - **Users**: 20 (or your TARGET_USERS value)
  - **Spawn Rate**: 2 users/second
  - **Host**: Pre-configured to your API gateway

### 2. Start Load Test
- Click "Start swarming"
- Monitor real-time metrics
- View detailed results at `/test-results`

### 3. Export Results
- **PDF Reports**: Professional formatted reports
- **CSV Data**: Raw data for analysis
- **JSON API**: Programmatic access for monitoring

## Monitoring and Logs

### Railway Dashboard
- **Metrics**: CPU, Memory, Network usage
- **Logs**: Real-time application logs
- **Deployments**: Version history and rollbacks

### Application Logs
```bash
# View logs via Railway CLI
railway logs

# Or check Railway dashboard → Deployments → Logs
```

### Health Checks
Railway automatically monitors:
- HTTP health check on `/`
- 300-second timeout
- Auto-restart on failure (max 3 retries)

## Scaling Configuration

### Automatic Scaling
Railway automatically scales based on:
- CPU usage
- Memory consumption
- Request volume

### Manual Scaling
```bash
# Scale via Railway CLI
railway scale --replicas 2

# Or use Railway dashboard → Settings → Scaling
```

## Cost Optimization

### Resource Limits
Set appropriate limits in Railway dashboard:
- **CPU**: 1-2 vCPU for load testing
- **Memory**: 1-2 GB RAM
- **Network**: Monitor egress for API calls

### Usage Monitoring
- Track usage in Railway dashboard
- Set spending limits if needed
- Stop deployment when testing complete

## Troubleshooting

### Common Issues

1. **Port Binding Error**
   ```
   Solution: Ensure LOCUST_WEB_HOST=0.0.0.0 and PORT=$PORT
   ```

2. **Health Check Failures**
   ```
   Solution: Verify Locust web UI starts on correct port
   Check logs for startup errors
   ```

3. **API Connection Issues**
   ```
   Solution: Verify TARGET_HOST environment variable
   Check API gateway accessibility from Railway
   ```

### Debug Commands
```bash
# Check environment variables
railway variables

# View real-time logs
railway logs --tail

# Connect to running container
railway shell
```

## Security Considerations

### Network Security
- Railway deployments are public by default
- Consider IP restrictions for sensitive tests
- Use environment variables for sensitive config

### API Rate Limiting
- Monitor API gateway rate limits
- Adjust test parameters if hitting limits
- Consider distributed testing for higher loads

## Advanced Configuration

### Custom Domains
```bash
# Add custom domain via Railway CLI
railway domain add your-loadtest.yourdomain.com
```

### Multiple Environments
```bash
# Create staging environment
railway environment create staging
railway up --environment staging
```

### Automated Deployments
Set up GitHub Actions for automated deployments:
```yaml
# .github/workflows/deploy-loadtest.yml
name: Deploy Load Test
on:
  push:
    paths: ['tests/loadtest/**']
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: railway up --service loadtest
```

## Cleanup

### Stop Deployment
```bash
# Via Railway CLI
railway down

# Or via Railway dashboard → Settings → Delete Service
```

### Remove Project
```bash
railway project delete stockholm-load-test
```

## Support

- **Railway Docs**: [docs.railway.app](https://docs.railway.app)
- **Railway Discord**: Community support
- **GitHub Issues**: Report deployment issues

---

**Ready to deploy?** Push your changes and deploy to Railway for cloud-based load testing! 🚀