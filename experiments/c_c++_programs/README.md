# Run
```
TIMEOUT=60s ANTHROPIC_API_KEY=xxx docker-compose up \
    --build \
    --scale bc-concolic=1 \
    --scale bc-symcc=3 \
    --scale tcpdump-symcc=3 \
    --scale tcpdump-marco=3 \
    bc-concolic bc-symcc tcpdump-symcc tcpdump-marco
```

# Stop and remove all containers
```
docker-compose down
```