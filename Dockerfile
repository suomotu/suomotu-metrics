FROM python:3.12-slim

WORKDIR /app
COPY suomotu_metrics ./suomotu_metrics

ENV PYTHONUNBUFFERED=1
VOLUME /data

ENTRYPOINT ["python", "-m", "suomotu_metrics"]
