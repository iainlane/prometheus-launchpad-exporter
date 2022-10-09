# syntax=docker/dockerfile:1

FROM python:3.10-alpine3.16

RUN apk add gcc musl-dev libffi-dev

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .

ENV PYTHONPATH=/app/src

EXPOSE 8000

ENTRYPOINT [ "python3", "-m" , "prometheus_launchpad_exporter", "--debug" ]
