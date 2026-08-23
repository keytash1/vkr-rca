FROM golang:1.26-alpine AS build

ARG SERVICE
WORKDIR /src

COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal

RUN test -n "${SERVICE}" && \
    CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/service "./cmd/${SERVICE}"

FROM alpine:3.23

RUN apk add --no-cache ca-certificates && \
    addgroup -S app && \
    adduser -S -G app app

COPY --from=build /out/service /usr/local/bin/service

USER app
ENTRYPOINT ["/usr/local/bin/service"]
