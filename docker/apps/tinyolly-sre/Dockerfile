# TinyOlly SRE agent. Self-contained: the build context is THIS directory, so it builds the same
# inside tinyolly and after being moved to its own repo.
#   docker build -t tinyolly/sre:latest docker/apps/tinyolly-sre
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sre/ sre/
COPY playbook.md .
ENV PLAYBOOK_FILE=/app/playbook.md PORT=8080
EXPOSE 8080
CMD ["python", "-u", "-m", "sre"]
