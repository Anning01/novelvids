FROM docker:28-cli
RUN apk add --no-cache python3 git
WORKDIR /updater
COPY scripts/update/agent.py scripts/update/install_docker.py ./
ENTRYPOINT ["python3", "/updater/agent.py"]
