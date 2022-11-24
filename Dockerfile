# syntax=docker/dockerfile:1

FROM python:3.11-alpine3.16

# hadolint ignore=DL3018
RUN apk add --no-cache gcc musl-dev libffi-dev

RUN rm -rf /var/cache/apk/*

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app/src

EXPOSE 8000

ENTRYPOINT [ "python3", "-m" , "prometheus_launchpad_exporter", "--debug" ]
