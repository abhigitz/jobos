# JobOS

## Configuration

### Required Environment Variables
- `DATABASE_URL` - PostgreSQL connection string
- `JWT_SECRET` - Secret key for JWT tokens
- `ANTHROPIC_API_KEY` - Claude API key

### Optional Environment Variables
- `REDIS_URL` - Redis connection for persistent rate limiting
  - If not set, rate limits use in-memory storage (resets on restart)
  - Required for multi-instance deployments
- `JOBOS_DEBUG` - Set to "true" to enable debug logging

### Scheduler Limitations

JobOS uses APScheduler with in-memory job store. Current limitations:
- **Single instance only** - Running multiple instances will duplicate scheduled tasks
- **No persistence** - Missed jobs during downtime are not recovered

For production multi-instance deployment, consider:
- Using APScheduler with Redis/PostgreSQL job store
- External scheduler (Celery Beat, cron, Cloud Scheduler)
